"""Fetch a frozen Japanese review queue and retain exact official metadata.

HTML stays in the local cache. Published artifacts contain factual identity
fields and response hashes only. Unknown or absent rarity icons stay unknown.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_jp_source_conflicts import TITLE, SET, RARITY_ICON, compact
from pokemon_index.card_rarity import OFFICIAL_ICON_RARITIES

URL = re.compile(r"https://www\.pokemon-card\.com/card-search/details\.php/card/(\d+)")
NUMBER = re.compile(r"(\d{1,3})\s*&nbsp;\s*/\s*&nbsp;\s*([A-Za-z0-9-]+)\s*&nbsp;")


def parse_page(raw: bytes) -> dict:
    body = raw.decode("utf-8")
    titles = TITLE.findall(body)
    identity = re.findall(r'<div class="subtext Text-fjalla">(.*?)</div>', body, re.S)
    if len(titles) != 1 or len(identity) != 1:
        raise ValueError("official page lacks one exact card identity block")
    logos, numbers = list(SET.finditer(identity[0])), list(NUMBER.finditer(identity[0]))
    if not logos or len(logos) != len(numbers) or any(x[1].upper() != x[2].upper() for x in logos):
        raise ValueError("official identity has missing or ambiguous set/number")
    name = html.unescape(re.sub(r"<[^>]+>", "", titles[0])).strip()
    if not name:
        raise ValueError("official name missing")
    entries = []
    for i, (logo, number) in enumerate(zip(logos, numbers)):
        end = logos[i + 1].start() if i + 1 < len(logos) else len(identity[0])
        if not logo.end() <= number.start() < number.end() <= end:
            raise ValueError("official set/number block order is ambiguous")
        segment = identity[0][logo.start():end]
        icons = sorted(set(RARITY_ICON.findall(segment)))
        rarity = OFFICIAL_ICON_RARITIES.get(icons[0]) if len(icons) == 1 else None
        role = re.findall(r"\((上|下|左|右)\)", segment)
        if len(role) > 1:
            raise ValueError("ambiguous numbered part role")
        entries.append(dict(set_code=logo[1].upper(), collector_number=number[1].zfill(3) + "/" + number[2].upper(),
            part_role=role[0] if role else None, rarity_icons=icons, rarity=rarity,
            rarity_status="recognized_icon" if rarity else "unrecognized_icon" if icons else "no_rarity_icon"))
    if len({(x['set_code'], x['collector_number']) for x in entries}) != len(entries):
        raise ValueError("duplicate official numbered coordinates")
    authors = re.findall(r'<div class="author">(.*?)</div>', body, re.S)
    if len(authors) != 1:
        raise ValueError("official illustrator block missing or ambiguous")
    author = re.findall(r'<a[^>]+href="/card-search/index\.php\?regulation_illust=all&illust=[^"]+"[^>]*>(.*?)</a>', authors[0], re.S)
    artists = sorted(set(html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in author))
    if any(not x or len(x) > 160 for x in artists):
        raise ValueError("ambiguous official illustrator")
    dex = re.findall(r'<div class="card Text-fjalla">\s*<h4>No\.(\d{1,4})[\s　]', body)
    if len(dex) > 1:
        raise ValueError("ambiguous official character number")
    return dict(name=name, numbered_entries=entries,
                page_kind="single_number" if len(entries) == 1 else "numbered_parts",
                illustrators=artists,
                dex_id=int(dex[0]) if dex and 1 <= int(dex[0]) <= 9999 else None)


def fetch(url, cache):
    match = URL.fullmatch(url)
    if not match:
        raise ValueError("official URL outside allowlist")
    path, receipt = cache / (match[1] + ".html"), cache / (match[1] + ".receipt.json")
    if path.exists() and receipt.exists():
        raw, metadata = path.read_bytes(), json.loads(receipt.read_text())
        if metadata["url"] != url or hashlib.sha256(raw).hexdigest() != metadata["page_sha256"]:
            raise ValueError("official cache receipt differs")
        return raw, metadata
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "pokemon-commerce-internal-review/1"})
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.geturl() != url:
                    raise ValueError("official page redirected")
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("official page exceeds size limit")
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            time.sleep(2 ** attempt)
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    metadata = dict(url=url, page_sha256=hashlib.sha256(raw).hexdigest(),
                    fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path.write_bytes(raw)
    receipt.write_text(json.dumps(metadata, indent=2) + "\n")
    return raw, metadata


def audit(queue_path, cache, output):
    if output.exists():
        raise FileExistsError(output)
    cache.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in queue_path.read_text().splitlines()]
    if len(rows) != len({(r["set_code"], r["collector_number"]) for r in rows}):
        raise ValueError("queue contains duplicate number groups")
    def check(row):
        result = dict(queue=row, decision="pending", official=None)
        try:
            raw, receipt = fetch(row["candidate_official_url"], cache)
            result["page_receipt"] = receipt
            observed = parse_page(raw)
            selected = [x for x in observed['numbered_entries'] if x['set_code'] == row['set_code'] and x['collector_number'] == row['collector_number']]
            if len(selected) != 1:
                result['official'] = {**receipt, **observed}
                result['decision'] = 'identity_conflict'
                return result
            observed.update(selected[0])
            result["official"] = {**receipt, **observed}
            agrees = observed["set_code"] == row["set_code"] and observed["collector_number"] == row["collector_number"]
            names = [row["name"], row["reference"]["name"]] + [r["name"] for r in row["catalog_records"]]
            if agrees and all(compact(observed["name"]) == compact(x) for x in names):
                result["decision"] = "exact_metadata_agreement"
            else:
                result["decision"] = "identity_conflict"
        except Exception as exc:
            result.update(decision="fetch_or_parse_hold", error_type=type(exc).__name__, error=str(exc)[:250])
        time.sleep(0.12)
        return result
    results = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(check, row): index for index, row in enumerate(rows)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            if len(results) % 50 == 0:
                print(json.dumps(dict(reviewed=len(results), total=len(rows), decisions=dict(Counter(x['decision'] for x in results.values())))), flush=True)
    output.write_text("".join(json.dumps(results[i], ensure_ascii=False, sort_keys=True) + "\n" for i in range(len(rows))))
    report = dict(queue_sha256=hashlib.sha256(queue_path.read_bytes()).hexdigest(),
                  audit_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                  reviewed=len(rows), decisions=dict(Counter(x["decision"] for x in results.values())),
                  rarity_icons=dict(Counter(icon for x in results.values() if x["official"] for icon in x["official"].get("rarity_icons", []))),
                  scope="exact official metadata only; no physical finish/copy, cross-region or market approval")
    output.with_suffix(".summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.queue, args.cache, args.output), ensure_ascii=False, indent=2))

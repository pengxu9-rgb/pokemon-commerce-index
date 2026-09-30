"""Compare pinned Japanese card names and verify material conflicts at official pages.

The output is internal factual metadata only. Gemini/search can discover leads,
but only an exact official set/number page can settle a catalog correction.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import subprocess
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

TCGDEX_REVISION = "a211f11f3ba57d56c65c5ac33be35b77d3280757"
PTCG_REVISION = "bc5a2698eb9af858feb0280d579fd5fd0f0273e2"
NUMBER = re.compile(r"(\d{1,3})&nbsp;/&nbsp;([A-Za-z0-9-]+)&nbsp;")
TITLE = re.compile(r'<h1[^>]*class="Heading1 mt20"[^>]*>(.*?)</h1>', re.S)
SET = re.compile(r'/card/regulation_logo_1/([^/]+)\.gif"[^>]*alt="([^"]+)"')
RARITY_ICON = re.compile(r'/card/rarity/(ic_[a-z0-9_]+\.gif)', re.I)


def compact(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name)).casefold()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def official_record(url: str, set_code: str, number: str) -> dict:
    parsed = urllib.parse.urlparse(url)
    if (parsed.scheme != "https" or parsed.hostname != "www.pokemon-card.com"
            or not re.fullmatch(r"/card-search/details\.php/card/\d+", parsed.path)
            or parsed.query or parsed.fragment):
        raise ValueError("official card URL is not allowlisted")
    request = urllib.request.Request(url, headers={"User-Agent": "pokemon-commerce-internal-review/1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        if response.geturl() != url:
            raise ValueError("official card page redirected")
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("official page too large")
    body = raw.decode("utf-8")
    title, card_set, card_number = TITLE.search(body), SET.search(body), NUMBER.search(body)
    if not all((title, card_set, card_number)):
        raise ValueError("official page lacks exact card identity")
    name = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
    observed_number = f"{card_number.group(1).zfill(3)}/{card_number.group(2)}"
    if (card_set.group(1).upper() != set_code or card_set.group(2).upper() != set_code
            or observed_number.upper() != number):
        raise ValueError("official page set or number disagrees with source")
    rarity_icons = sorted(set(RARITY_ICON.findall(body)))
    return {"url": url, "page_sha256": hashlib.sha256(raw).hexdigest(),
            "name": name, "set_code": set_code, "collector_number": number,
            "rarity_icons": rarity_icons}


def audit(base_path: Path, reference_path: Path, ptcg_repo: Path,
          verify_official: bool = False) -> dict:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ptcg_repo, text=True).strip() != PTCG_REVISION:
        raise ValueError("PTCG checkout differs from pinned revision")
    base, refs = defaultdict(set), defaultdict(list)
    for row in rows(base_path):
        if row["provenance"].startswith(f"tcgdex:{TCGDEX_REVISION}:"):
            base[(row["set_code"], row["collector_number"])].add(row["name"])
    for row in rows(reference_path):
        if row["set_code"] and row["collector_number"]:
            refs[(row["set_code"], row["collector_number"])].append(row)
    results, counts = [], Counter()
    for (set_code, number), evidence in sorted(refs.items()):
        names = sorted({row["name"] for row in evidence})
        existing = sorted(base.get((set_code, number), []))
        if not existing or set(existing) & set(names):
            continue
        classification = ("format_only" if {compact(x) for x in existing}
                          & {compact(x) for x in names} else "material_name_difference")
        entry = {"set_code": set_code, "collector_number": number,
                 "tcgdex_names": existing, "ptcg_names": names,
                 "classification": classification,
                 "ptcg_provenance": [r["provenance"] for r in evidence]}
        if verify_official and classification == "material_name_difference":
            found = []
            for row in evidence:
                provenance = row["provenance"]
                path, expected = provenance.split(":sha256:", 1)
                relative = path.split(":", 2)[2]
                if not re.fullmatch(r"data_jp/[A-Za-z0-9-]+/[A-Za-z0-9-]+\.json", relative):
                    raise ValueError("PTCG reference path is not allowlisted")
                source_bytes = (ptcg_repo / relative).read_bytes()
                if hashlib.sha256(source_bytes).hexdigest() != expected:
                    raise ValueError("PTCG reference source hash changed")
                official_url = json.loads(source_bytes).get("url", "")
                found.append(official_record(official_url, set_code, number))
            if len({r["name"] for r in found}) != 1:
                raise ValueError("official records disagree for one set/number")
            entry["official_records"] = found
            official_name = found[0]["name"]
            if compact(official_name) in {compact(x) for x in existing}:
                entry["official_support"] = "tcgdex_base_name"
            elif compact(official_name) in {compact(x) for x in names}:
                entry["official_support"] = "ptcg_name"
            else:
                entry["official_support"] = "neither"
            counts["official_exact_pages_checked"] += len(found)
            counts["official_support_" + entry["official_support"]] += 1
            if any("ic_prismstar.gif" in record["rarity_icons"] for record in found):
                counts["official_prismstar_groups"] += 1
        counts[classification] += 1
        results.append(entry)
    return {"scope": "internal card-name comparison; no images, listings or price evidence",
            "tcgdex_revision": TCGDEX_REVISION, "ptcg_revision": PTCG_REVISION,
            "base_sha256": hashlib.sha256(base_path.read_bytes()).hexdigest(),
            "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
            "verified_at": datetime.now(timezone.utc).isoformat() if verify_official else None,
            "counts": dict(sorted(counts.items())), "conflicts": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--ptcg-repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-official", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = audit(args.base, args.reference, args.ptcg_repo.resolve(), args.verify_official)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

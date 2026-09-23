"""Cache TCGdex set API responses and freeze minimal English identity fields.

This supplements the pinned source extract. List-only API cards have no proven
finish identity and must not become offer-match eligible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.tcgdex.net/v2/en/"


def _get(cache: Path, endpoint: str) -> tuple[dict | list, str, str]:
    cache.mkdir(parents=True, exist_ok=True)
    stem = endpoint.replace("/", "__")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", stem):
        raise ValueError(f"unsafe endpoint: {endpoint}")
    path = cache / f"{stem}.json"
    timestamp = cache / f"{stem}.fetched_at"
    if path.exists() and timestamp.exists():
        raw = path.read_bytes()
        fetched_at = timestamp.read_text().strip()
    else:
        url = BASE + endpoint
        for attempt in range(4):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "pokemon-commerce-index/0.1"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read()
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt == 3:
                    raise RuntimeError(f"API request failed: {endpoint}") from exc
                time.sleep(2 ** attempt)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.write_bytes(raw)
        timestamp.write_text(fetched_at + "\n")
    return json.loads(raw), fetched_at, hashlib.sha256(raw).hexdigest()


def snapshot(cache: Path, existing_sets: Path, reference_path: Path,
             sets_path: Path, audit_path: Path) -> dict:
    for path in (reference_path, sets_path, audit_path):
        if path.exists():
            raise FileExistsError(path)
    existing = {json.loads(line)["set_code"].upper()
                for line in existing_sets.read_text(encoding="utf-8").splitlines()}
    listed, list_at, list_sha = _get(cache, "sets")
    digital, digital_at, digital_sha = _get(cache, "series/tcgp")
    if not isinstance(listed, list) or digital.get("id") != "tcgp":
        raise ValueError("unexpected API set/series response")
    digital_ids = {item["id"].upper() for item in digital["sets"]}
    targets = sorted((item["id"] for item in listed
                      if item["id"].upper() not in existing | digital_ids), key=str.upper)
    results = {}
    # Three concurrent requests keep the free API load modest. Responses are cached.
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_get, cache, f"sets/{set_id}"): set_id for set_id in targets}
        for future in as_completed(futures):
            set_id = futures[future]
            payload, fetched_at, sha = future.result()
            if payload.get("id", "").upper() != set_id.upper() or payload.get("serie", {}).get("id") == "tcgp":
                raise ValueError(f"API set identity changed: {set_id}")
            results[set_id] = (payload, fetched_at, sha)
    rights = "https://github.com/tcgdex/cards-database/blob/master/LICENSE"
    references, sets, gaps = [], [], []
    for set_id in targets:
        payload, fetched_at, sha = results[set_id]
        official = payload.get("cardCount", {}).get("official")
        name = payload.get("name")
        if not isinstance(official, int) or official < 0 or not isinstance(name, str) or not name:
            raise ValueError(f"set metadata incomplete: {set_id}")
        provenance = f"tcgdex-api:v2:en:sets/{set_id}:sha256:{sha}"
        sets.append({"language": "en", "set_code": set_id, "name": name,
                     "release_date": payload.get("releaseDate"),
                     "official_card_count": official, "provenance": provenance,
                     "rights_reference": rights, "display_allowed": False,
                     "fetched_at": fetched_at})
        cards = payload.get("cards")
        if not isinstance(cards, list):
            raise ValueError(f"set lacks card list: {set_id}")
        for item in cards:
            local = urllib.parse.unquote(str(item.get("localId") or ""))
            card_name = item.get("name")
            card_id = item.get("id")
            if (not re.fullmatch(r"[A-Za-z0-9!?]+", local)
                    or not isinstance(card_name, str) or not card_name
                    or not isinstance(card_id, str) or not card_id):
                gaps.append({"set_code": set_id, "source_card_id": item.get("id"),
                             "reason": "card lacks usable name or collector id"})
                continue
            width = max(3, len(local), len(str(official)))
            denominator = str(official).zfill(width) if official else set_id
            numerator = local.zfill(width) if local.isdigit() else local.upper()
            references.append({"source": "tcgdex-api", "source_card_id": card_id,
                               "set_code": set_id, "collector_number": f"{numerator}/{denominator}",
                               "name": card_name, "rarity": None,
                               "provenance": provenance, "rights_reference": rights,
                               "display_allowed": False, "match_eligible": False})
    for path, rows in ((reference_path, references), (sets_path, sets)):
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"api": BASE, "set_list_fetched_at": list_at,
              "set_list_sha256": list_sha, "digital_series_fetched_at": digital_at,
              "digital_series_sha256": digital_sha,
              "excluded_existing_sets": len(existing), "excluded_digital_sets": len(digital_ids),
              "fetched_sets": len(sets), "reference_rows": len(references),
              "gap_rows": len(gaps), "gaps": gaps,
              "scope": "API set/card identity list only; no variant or image data",
              "display_approved": False, "match_eligible": False}
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return {key: value for key, value in report.items() if key != "gaps"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--existing-sets", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--sets", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.cache, args.existing_sets, args.reference,
                              args.sets, args.audit), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

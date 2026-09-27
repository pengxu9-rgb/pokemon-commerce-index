"""Select a balanced, provisional 100-printing eBay Browse pilot cohort.

This is a coverage sample, not a claim about demand or sales. Real listing
volume will determine which identities to curate after licensed access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pokemon_index import core
from scripts.relationship_pilot import write_jsonl

CHARACTERS = {
    "en": ("Pikachu", "Charizard", "Eevee", "Mewtwo", "Gengar"),
    "ja": ("ピカチュウ", "リザードン", "イーブイ", "ミュウツー", "ゲンガー"),
}
PER_BUCKET = 10


def build(db) -> tuple[list[dict], dict]:
    rows, counts = [], Counter()
    for language, characters in CHARACTERS.items():
        for character in characters:
            candidates = db.execute("""SELECT c.card_id,c.name,c.language,c.set_code,
                c.collector_number,c.variant,c.provenance,s.release_date
                FROM card c LEFT JOIN catalog_set_localized s
                  ON s.language=c.language AND s.set_code=c.set_code
                WHERE c.language=? AND c.name LIKE ? AND c.match_eligible=1
                ORDER BY COALESCE(s.release_date,'') DESC,c.card_id""",
                (language, character + "%")).fetchall()
            candidates = [row for row in candidates if
                          re.fullmatch(r"[0-9]{3}/[0-9]{3}", row["collector_number"])
                          and row["variant"] not in {"unverified_multi_record", "unverified"}]
            by_set = defaultdict(list)
            for row in candidates:
                by_set[row["set_code"]].append(row)
            selected = []
            set_order = sorted(by_set, key=lambda code: (
                by_set[code][0]["release_date"] or "", code), reverse=True)
            while len(selected) < PER_BUCKET and set_order:
                remaining = []
                for code in set_order:
                    if len(selected) == PER_BUCKET:
                        break
                    selected.append(by_set[code].pop(0))
                    if by_set[code]:
                        remaining.append(code)
                set_order = remaining
            if len(selected) != PER_BUCKET:
                raise ValueError(f"insufficient exact catalog cards: {language} {character}")
            for row in selected:
                identity = {key: row[key] for key in
                            ("card_id", "name", "language", "set_code", "collector_number", "variant")}
                identity["catalog_provenance_sha256"] = hashlib.sha256(
                    row["provenance"].encode()).hexdigest()
                identity.update({"character_bucket": character,
                                 "marketplace": "EBAY_US",
                                 "query": f"Pokemon {row['name']} {row['set_code']} {row['collector_number']} "
                                          + ("Japanese" if language == "ja" else "English"),
                                 "selection_status": "provisional_coverage_sample",
                                 "offer_matching_status": "photo_review_required"})
                if len(identity["query"]) > 120:
                    raise ValueError("eBay pilot query exceeds probe limit")
                rows.append(identity)
                counts[f"{language}:{character}"] += 1
    if len(rows) != 100 or len({row["card_id"] for row in rows}) != 100:
        raise ValueError("pilot has duplicate or missing target identities")
    rows.sort(key=lambda row: (row["language"], row["character_bucket"], row["card_id"]))
    return rows, {"targets": len(rows), "buckets": dict(sorted(counts.items())),
                  "distinct_sets": len({(row["language"],row["set_code"]) for row in rows}),
                  "marketplace": "EBAY_US", "planned_days": 14,
                  "planned_search_calls_per_day": 100,
                  "observed_market_demand": False,
                  "scope": "provisional exact-printing coverage sample; no API observations or prices"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.audit.exists():
        raise FileExistsError("pilot outputs must be new")
    with core.connect(args.db) as db:
        rows, report = build(db)
    write_jsonl(args.output, rows)
    args.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()

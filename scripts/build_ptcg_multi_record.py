"""Preserve same-name, multi-record Japanese identities without inventing finishes.

The source can contain several records for one set and collector number. These
are internal discovery candidates only. A set with even one name collision is
excluded wholesale because its set code may describe several distinct decks.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def build(reference_path: Path, gaps_path: Path, candidates_path: Path,
          audit_path: Path) -> dict:
    if candidates_path.exists() or audit_path.exists():
        raise FileExistsError("output already exists")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in reference_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row["set_code"] and row["collector_number"]:
            groups[(row["set_code"], row["collector_number"])].append(row)
    keys = []
    for line in gaps_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if row.get("reason") == "multiple source records share set and number":
            keys.append((row["set_code"], row["collector_number"]))
    conflicting_sets = {
        set_code for set_code, number in keys
        if len({row["name"] for row in groups[(set_code, number)]}) != 1
    }
    candidates = []
    excluded_conflicts = 0
    excluded_sets = 0
    for set_code, number in sorted(keys):
        rows = groups[(set_code, number)]
        if len(rows) < 2:
            raise ValueError(f"gap is not a multi-record group: {set_code} {number}")
        if len({row["name"] for row in rows}) != 1:
            excluded_conflicts += 1
            continue
        if set_code in conflicting_sets:
            excluded_sets += 1
            continue
        rights = {row["rights_reference"] for row in rows}
        if len(rights) != 1 or any(row["display_allowed"] or row["match_eligible"] for row in rows):
            raise ValueError(f"unexpected source policy: {set_code} {number}")
        rarities = {row["rarity"] for row in rows}
        candidates.append({
            "language": "ja", "set_code": set_code, "collector_number": number,
            "variant": "unverified_multi_record", "name": rows[0]["name"],
            "rarity": next(iter(rarities)) if len(rarities) == 1 else None,
            "attributes": {"source_jp_ids": sorted(row["source_jp_id"] for row in rows),
                           "source_record_count": len(rows),
                           "printing_variant_unresolved": True},
            "provenance": "|".join(sorted(row["provenance"] for row in rows)),
            "rights_reference": rights.pop(), "display_allowed": False,
            "match_eligible": False,
        })
    audit = {"source": "ptcg-jp-reference.jsonl and ptcg-jp-gaps.jsonl",
             "scope": "internal set-and-number discovery candidates; finish unresolved",
             "multi_record_groups": len(keys), "new_candidates": len(candidates),
             "candidate_sets": len({row["set_code"] for row in candidates}),
             "excluded_name_conflicts": excluded_conflicts,
             "excluded_whole_conflicting_sets": excluded_sets,
             "conflicting_set_codes": sorted(conflicting_sets),
             "display_approved": False, "match_eligible": False}
    with candidates_path.open("x", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--gaps", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.reference, args.gaps, args.candidates, args.audit),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

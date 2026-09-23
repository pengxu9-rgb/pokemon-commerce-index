"""Turn frozen TCGdex API card summaries into unverified English families.

The set API omits finish/printing evidence. One set-and-number candidate may
cover multiple printings; none is eligible for automated offer resolution.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def build(reference_path: Path, existing_cards: Path, output: Path, audit_path: Path) -> dict:
    if output.exists() or audit_path.exists():
        raise FileExistsError("output already exists")
    existing = set()
    for line in existing_cards.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        existing.add((row["set_code"].upper(), row["collector_number"]))
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for line in reference_path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        grouped[(row["set_code"].upper(), row["collector_number"])].append(row)
    candidates = []
    conflicts = []
    for (set_code, number), rows in sorted(grouped.items()):
        if (set_code, number) in existing:
            raise ValueError(f"API candidate overlaps pinned source: {set_code} {number}")
        names = {row["name"] for row in rows}
        if len(names) != 1:
            conflicts.append({"set_code": set_code, "collector_number": number,
                              "source_card_ids": [row["source_card_id"] for row in rows],
                              "reason": "different names at same set and number"})
            continue
        rights = {row["rights_reference"] for row in rows}
        if len(rights) != 1 or any(row["display_allowed"] or row["match_eligible"] for row in rows):
            raise ValueError(f"unexpected source policy: {set_code} {number}")
        candidates.append({
            "language": "en", "set_code": set_code, "collector_number": number,
            "variant": "unverified_api_family", "name": rows[0]["name"],
            "rarity": None, "attributes": {
                "source_card_ids": sorted(row["source_card_id"] for row in rows),
                "printing_variant_unresolved": True},
            "provenance": "|".join(sorted({row["provenance"] for row in rows})),
            "rights_reference": rights.pop(), "display_allowed": False,
            "match_eligible": False,
        })
    with output.open("x", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"source": "tcgdex-api:v2:en:sets", "scope": "internal English set-and-number families",
              "reference_groups": len(grouped), "candidate_families": len(candidates),
              "candidate_sets": len({row["set_code"] for row in candidates}),
              "name_conflicts": len(conflicts), "conflicts": conflicts,
              "display_approved": False, "match_eligible": False}
    audit_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return {key: value for key, value in report.items() if key != "conflicts"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--existing-cards", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.reference, args.existing_cards, args.output, args.audit),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

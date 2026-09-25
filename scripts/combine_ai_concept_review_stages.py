"""Combine completed v6 stage reviews for sequential candidate scheduling.

The source stage files remain immutable. The combined files are working inputs
for concept_review_staged and never add review decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def combine(catalog: Path, stages: list[int], output: Path) -> None:
    if not stages or stages != list(range(1, max(stages) + 1)):
        raise ValueError("stages must be contiguous starting at 1")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"concept-review-v6-through-stage{max(stages)}"
    all_ids: set[str] = set()
    for reviewer in ("astra", "sol", "gemini"):
        rows: list[dict[str, str]] = []
        fields: list[str] | None = None
        for stage in stages:
            path = catalog / f"concept-review-v6-stage{stage}-{reviewer}.csv"
            with path.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if fields is None:
                    fields = reader.fieldnames
                elif fields != reader.fieldnames:
                    raise ValueError(f"review columns changed: {path}")
                rows.extend(reader)
        ids = [row["proposal_id"] for row in rows]
        if len(ids) != len(set(ids)) or (all_ids and set(ids) != all_ids):
            raise ValueError(f"duplicate or inconsistent review coverage: {reviewer}")
        all_ids = set(ids)
        with (output / f"{stem}-{reviewer}.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    audits = [json.loads((catalog / f"concept-review-v6-stage{stage}-gemini-audit.json")
                         .read_text(encoding="utf-8")) for stage in stages]
    first = audits[0]
    shared_keys = ("model", "project", "location", "prompt_version", "pinned_revision", "scope")
    if any(any(audit.get(key) != first.get(key) for key in shared_keys) for audit in audits):
        raise ValueError("Gemini audit context changed across stages")
    evidence = [row for audit in audits for row in audit["rows"]]
    if len(evidence) != len(all_ids) or {row["proposal_id"] for row in evidence} != all_ids:
        raise ValueError("Gemini evidence does not cover combined reviews")
    counts: Counter[str] = Counter()
    for audit in audits:
        counts.update(audit["decisions"])
    combined = {key: first[key] for key in shared_keys}
    combined.update({
        "review_rows": len(evidence),
        "decisions": dict(sorted(counts.items())),
        "images_included": sum(audit["images_included"] for audit in audits),
        "image_sides_total": sum(audit["image_sides_total"] for audit in audits),
        "rows": evidence,
    })
    (output / f"{stem}-gemini-audit.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stages": stages, "review_rows": len(evidence),
                      "images_included": combined["images_included"]}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--stages", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    combine(args.catalog, args.stages, args.output)


if __name__ == "__main__":
    main()

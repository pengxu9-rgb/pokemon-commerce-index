"""Upgrade existing pinned set seeds to three-digit Japanese collector numbers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pokemon_index.core import normalize_collector_number
from scripts.build_tcgdex_batch import aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-dir", type=Path, default=Path("catalog"))
    args = parser.parse_args()
    catalog = args.catalog_dir
    updated = 0
    for audit_path in sorted(catalog.glob("ja-*-audit.json")):
        seed_path = audit_path.with_name(audit_path.name.replace("-audit.json", ".jsonl"))
        rows = [json.loads(line) for line in seed_path.read_text(encoding="utf-8").splitlines()]
        for row in rows:
            normalized = normalize_collector_number(row["collector_number"])
            updated += normalized != row["collector_number"]
            row["collector_number"] = normalized
        keys = [(row["language"], row["set_code"], row["collector_number"], row["variant"])
                for row in rows]
        if len(keys) != len(set(keys)):
            raise ValueError(f"normalization creates duplicate identity in {seed_path.name}")
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["collector_number_format"] = "three_digit_minimum"
        seed_path.with_suffix(".jsonl.tmp").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
        seed_path.with_suffix(".jsonl.tmp").replace(seed_path)
        audit_path.with_suffix(".json.tmp").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        audit_path.with_suffix(".json.tmp").replace(audit_path)
    report = aggregate(catalog, catalog / "coverage-report.json",
                       catalog / "ja-selected-modern.jsonl")
    print(json.dumps({"collector_numbers_updated": updated,
                      "sets": report["sets"], "printings": report["priceable_printings"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

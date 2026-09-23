"""Build selected Japanese sets and write an audited aggregate seed."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from .build_tcgdex_set import build


def aggregate(catalog_dir: Path, report_path: Path, aggregate_path: Path) -> dict:
    audits = []
    rows = []
    identities = set()
    for audit_path in sorted(catalog_dir.glob("ja-*-audit.json")):
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        seed_path = audit_path.with_name(audit_path.name.replace("-audit.json", ".jsonl"))
        if not seed_path.exists():
            raise ValueError(f"seed missing for {audit_path.name}")
        seeds = [json.loads(line) for line in seed_path.read_text(encoding="utf-8").splitlines()]
        if len(seeds) != audit["normalized_printings"]:
            raise ValueError(f"audit count mismatch for {seed_path.name}")
        audits.append(audit)
        for row in seeds:
            key = (row["language"], row["set_code"].upper(), row["collector_number"], row["variant"])
            if key in identities:
                raise ValueError(f"duplicate normalized identity across sets: {key}")
            identities.add(key)
            rows.append(row)
    rows.sort(key=lambda row: (row["set_code"], row["collector_number"], row["variant"]))
    report = {
        "sets": len(audits),
        "source_files": sum(audit["source_files_fetched"] for audit in audits),
        "parsed_source_files": sum(audit["source_files_parsed"] for audit in audits),
        "priceable_printings": len(rows),
        "variant_counts": dict(sorted(Counter(row["variant"] for row in rows).items())),
        "display_approved": False,
        "set_coverage": [{"set_id": audit["set_id"],
                          "source_files": audit["source_files_fetched"],
                          "parsed": audit["source_files_parsed"],
                          "printings": audit["normalized_printings"],
                          "variant_counts": audit["variant_counts"],
                          "errors": len(audit["errors"])} for audit in audits],
    }
    target_manifest = catalog_dir / "phase1-targets.json"
    if target_manifest.exists():
        targets = json.loads(target_manifest.read_text(encoding="utf-8"))
        loaded = {audit["set_id"] for audit in audits}
        report["target_scope"] = targets["scope"]
        report["target_sets"] = len(targets["set_ids"])
        report["missing_target_sets"] = sorted(set(targets["set_ids"]) - loaded)
    aggregate_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                              encoding="utf-8")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build selected pinned TCGdex sets")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--catalog-dir", default="catalog")
    parser.add_argument("--set-path", action="append", default=[])
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()
    catalog = Path(args.catalog_dir)
    catalog.mkdir(parents=True, exist_ok=True)
    failures = []
    for set_path in args.set_path:
        name = set_path.rsplit("/", 1)[-1].lower()
        output = catalog / f"ja-{name}.jsonl"
        audit_path = catalog / f"ja-{name}-audit.json"
        if output.exists() and audit_path.exists():
            print(f"SKIP {set_path}: files already exist", flush=True)
            continue
        try:
            audit = build(set_path, args.revision, output, audit_path, None,
                          args.batch_size, args.cache_dir)
            print(f"DONE {set_path}: {audit['source_files_parsed']} files, "
                  f"{audit['normalized_printings']} printings, "
                  f"{len(audit['errors'])} errors", flush=True)
        except Exception as exc:
            failures.append({"set_path": set_path, "error": type(exc).__name__,
                             "message": str(exc)})
            print(f"FAILED {set_path}: {type(exc).__name__}: {exc}", flush=True)
    report = aggregate(catalog, catalog / "coverage-report.json",
                       catalog / "ja-selected-modern.jsonl")
    report["fetch_failures"] = failures
    (catalog / "coverage-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                                    encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()

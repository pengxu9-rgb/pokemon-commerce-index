"""Summarize post-label source fidelity without deleting frozen question rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.public_question_sandbox_v2 import FIELDS

STATUSES = {"faithful", "inferred_case", "mismatch", "unverifiable"}


def summarize(source_path: Path, audit_path: Path, silver_path: Path) -> dict:
    source_rows = read_jsonl(source_path)
    source_ids = [row["id"] for row in source_rows]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("duplicate source question IDs")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if audit.get("schema") != "pokemon.public-question-source-fidelity.v1":
        raise ValueError("unsupported source-fidelity audit schema")
    if audit.get("source_sha256") != sha_file(source_path):
        raise ValueError("source-fidelity audit does not match source file")
    items = audit.get("items")
    if not isinstance(items, list) or len(items) != len(source_ids):
        raise ValueError("audit must cover every source question")
    by_id = {}
    for item in items:
        if (not isinstance(item, dict) or set(item) != {"id", "status", "reason"}
                or item.get("status") not in STATUSES or
                not isinstance(item.get("reason"), str) or not item["reason"].strip()
                or item.get("id") in by_id):
            raise ValueError("invalid source-fidelity audit item")
        by_id[item["id"]] = item
    if set(by_id) != set(source_ids):
        raise ValueError("audit IDs do not match source questions")
    silver = json.loads(silver_path.read_text(encoding="utf-8"))
    results = silver.get("results")
    if (silver.get("schema") != "pokemon.public-question-silver.v2"
            or not isinstance(results, list) or
            len(results) != len(source_ids) or
            {row["id"] for row in results} != set(source_ids)):
        raise ValueError("v2 silver report does not match source questions")
    faithful = [row for row in results if by_id[row["id"]]["status"] == "faithful"]
    jointly_reviewed = [row for row in faithful if row["status"] != "review_failed"]
    return {"schema": "pokemon.public-question-fidelity-summary.v1",
            "source_sha256": sha_file(source_path),
            "audit_sha256": sha_file(audit_path),
            "silver_sha256": sha_file(silver_path),
            "all_source_posts": len(source_ids),
            "fidelity_counts": dict(sorted(Counter(
                item["status"] for item in items).items())),
            "faithful_source_posts": len(faithful),
            "faithful_jointly_reviewed": len(jointly_reviewed),
            "faithful_field_agreement": {key: {
                "agreed": sum(key not in row["disagreements"]
                              for row in jointly_reviewed),
                "denominator": len(jointly_reviewed)} for key in FIELDS},
            "flagged_ids": [item["id"] for item in items
                            if item["status"] != "faithful"],
            "interpretation": "Post-label source-fidelity filter; exploratory only, because audit followed model review"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--silver", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("fidelity summary already exists")
    result = summarize(args.source, args.audit, args.silver)
    args.output.write_text(json.dumps(result, ensure_ascii=False,
                                      sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "all_source_posts", "fidelity_counts", "flagged_ids")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

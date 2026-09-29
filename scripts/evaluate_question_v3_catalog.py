"""Replay frozen v3 facts through a pinned catalog without making accuracy claims."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

from pokemon_index import catalog_question_resolver, question_routing_v3
from scripts.public_question_sandbox import read_jsonl, sha_file


def evaluate(frozen_dir: Path, facts_path: Path, catalog_path: Path,
             output: Path) -> dict:
    if output.exists():
        raise FileExistsError("route report must use a new path")
    manifest_path = frozen_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "blind_sha256": frozen_dir / "blind_questions.jsonl",
        "source_index_sha256": frozen_dir / "source_index.jsonl",
        "preflight_report_sha256": frozen_dir / "preflight_report.json",
        "v3_planner_sha256": Path(question_routing_v3.__file__),
        "catalog_resolver_sha256": Path(catalog_question_resolver.__file__),
        "catalog_snapshot_sha256": catalog_path,
    }
    for field, path in required.items():
        if manifest.get(field) != sha_file(path):
            raise ValueError(f"frozen {field} differs from manifest")
    questions = {row["id"]: row for row in read_jsonl(frozen_dir / "blind_questions.jsonl")}
    splits = {row["id"]: row["split"] for row in read_jsonl(
        frozen_dir / "source_index.jsonl")}
    facts_rows = read_jsonl(facts_path)
    if (len(facts_rows) != len(questions) or
            len({row.get("id") for row in facts_rows}) != len(facts_rows) or
            {row["id"] for row in facts_rows} != set(questions) or
            set(splits) != set(questions)):
        raise ValueError("frozen questions and fact rows differ")
    rows = []
    with closing(sqlite3.connect(f"{catalog_path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        for item in facts_rows:
            source = questions[item["id"]]
            if item.get("question_sha256") != source["question_sha256"]:
                raise ValueError("fact row is bound to a different question")
            if item.get("status") != "ok":
                rows.append({"id": item["id"], "split": splits[item["id"]],
                             "fact_status": item.get("status"), "catalog_status": None,
                             "actions": []})
                continue
            facts = question_routing_v3.validate_facts(item["facts"])
            plan = catalog_question_resolver.plan_question_with_catalog(db, facts)
            resolution = plan["catalog_lookup"]["resolution"]
            for step in plan["steps"]:
                if (step["action"] in {"retrieve_live_offers", "retrieve_verified_sales"}
                        and step["status"] != "blocked"):
                    raise ValueError("market evidence became ready without a capability")
            rows.append({"id": item["id"], "split": splits[item["id"]],
                         "fact_status": "ok", "object_type": facts["object_type"],
                         "primary_goal": facts["primary_goal"],
                         "catalog_status": resolution["status"],
                         "catalog_reason": plan["catalog_lookup"]["reason"],
                         "candidate_ids": resolution["candidate_ids"],
                         "matched_total": plan["catalog_lookup"]["matched_total"],
                         "actions": [{"action": step["action"], "status": step["status"]}
                                     for step in plan["steps"]]})
    report = {"schema": "pokemon.question-v3-catalog-replay.v1",
              "role": "fresh frozen cohort diagnostic; no independent fact truth or answer accuracy",
              "manifest_sha256": sha_file(manifest_path),
              "facts_sha256": sha_file(facts_path),
              "catalog_snapshot_sha256": manifest["catalog_snapshot_sha256"],
              "questions": len(rows),
              "valid_facts": sum(row["fact_status"] == "ok" for row in rows),
              "catalog_statuses": dict(sorted(Counter(row["catalog_status"]
                  for row in rows if row["catalog_status"] is not None).items())),
              "by_split": {split: sum(row["split"] == split for row in rows)
                           for split in ("development", "holdout")},
              "rows": rows}
    output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", type=Path, required=True)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--catalog-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.frozen_dir, args.facts, args.catalog_db, args.output)
    print(json.dumps({key: report[key] for key in (
        "questions", "valid_facts", "catalog_statuses", "by_split")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Compare independent fact extraction for a preflighted question cohort.

This measures agreement on structured input to the deterministic planner. It
is not a target-agent score or a human accuracy estimate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pokemon_index import question_routing
from pokemon_index.question_routing import REQUIRED_FACTS, plan_question, validate_facts
from scripts.public_question_sandbox import ROOT, read_jsonl, sha_file
from scripts.public_question_sandbox_v2 import SCHEMA

FIELDS = tuple(sorted(REQUIRED_FACTS))


def merge(frozen_dir: Path, astra_path: Path, gemini_path: Path,
          output: Path) -> dict:
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError("fact agreement report needs a new path outside the repository")
    manifest_path = frozen_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            sha_file(frozen_dir / "source_index.jsonl") != manifest["source_index_sha256"]):
        raise ValueError("frozen cohort differs from its manifest")
    questions = {row["id"]: row for row in read_jsonl(frozen_dir / "blind_questions.jsonl")}
    sources = {row["id"]: row for row in read_jsonl(frozen_dir / "source_index.jsonl")}
    if questions.keys() != sources.keys():
        raise ValueError("source index and blind question IDs differ")
    reviews = {}
    for family, path in (("astra", astra_path), ("google", gemini_path)):
        rows = read_jsonl(path)
        if len(rows) != len(questions) or len({row.get("id") for row in rows}) != len(rows):
            raise ValueError(f"{family} must review each question exactly once")
        for row in rows:
            question = questions.get(row.get("id"))
            if (question is None or row.get("question_sha256") != question["question_sha256"]
                    or row.get("model_family") != family):
                raise ValueError(f"{family} review is not bound to the frozen question")
            if row.get("status") == "ok":
                validate_facts(row.get("facts"))
            elif row.get("status") != "error" or row.get("facts") is not None:
                raise ValueError("review must contain valid facts or an explicit error")
            reviews[(family, row["id"])] = row
    results = []
    for item_id, question in questions.items():
        left, right = reviews["astra", item_id], reviews["google", item_id]
        valid = left["status"] == right["status"] == "ok"
        disagreements = ([key for key in FIELDS
                          if left["facts"][key] != right["facts"][key]] if valid else [])
        plan_left = plan_question(left["facts"]) if left["status"] == "ok" else None
        plan_right = plan_question(right["facts"]) if right["status"] == "ok" else None
        plan_signature = lambda p: None if p is None else (
            p["scope_status"], p["answer_mode"], tuple(s["action"] for s in p["steps"]))
        results.append({"id": item_id, "language": question["language"],
                        "split": sources[item_id]["split"],
                        "status": "review_failed" if not valid else
                                  "silver_agreed" if not disagreements else "disputed",
                        "disagreements": disagreements,
                        "plan_agrees": valid and plan_signature(plan_left) == plan_signature(plan_right),
                        "silver_facts": left["facts"] if valid and not disagreements else None})
    valid_rows = [row for row in results if row["status"] != "review_failed"]
    report = {"schema": "pokemon.public-question-facts-silver.v1",
              "manifest_sha256": sha_file(manifest_path),
              "astra_sha256": sha_file(astra_path),
              "gemini_sha256": sha_file(gemini_path),
              "planner_sha256": sha_file(Path(question_routing.__file__)),
              "questions": len(results), "jointly_reviewed": len(valid_rows),
              "status_counts": dict(sorted(Counter(r["status"] for r in results).items())),
              "field_agreement": {key: sum(key not in row["disagreements"]
                                           for row in valid_rows) for key in FIELDS},
              "deterministic_plan_agreement": sum(row["plan_agrees"] for row in valid_rows),
              "results": results,
              "interpretation": "Independent AI fact agreement; planner gates are deterministic; not human accuracy or market truth"}
    output.write_text(json.dumps(report, ensure_ascii=False,
                                 sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", type=Path, required=True)
    parser.add_argument("--astra", type=Path, required=True)
    parser.add_argument("--gemini", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = merge(args.frozen_dir, args.astra, args.gemini, args.output)
    print(json.dumps({key: report[key] for key in (
        "questions", "jointly_reviewed", "status_counts", "field_agreement",
        "deterministic_plan_agreement")}, ensure_ascii=False))


if __name__ == "__main__":
    main()

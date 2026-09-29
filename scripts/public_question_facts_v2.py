"""Compare independent v2 fact extraction on a frozen question cohort.

This measures inter-model agreement and deterministic plan agreement, not
truth, target-agent accuracy, visual review, or live market performance.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pokemon_index import question_routing_v2 as routing
from scripts.public_question_sandbox import ROOT, read_jsonl, sha_file
from scripts.public_question_sandbox_v2 import SCHEMA
from scripts import vertex_public_question_facts_v2 as extractor

FIELDS = ("object_type", "primary_goal", "transaction_context", "media_state",
          "language_mentions", "merchant_ref", "destination") + tuple(
              "identity_tokens." + field for field in sorted(routing.TOKEN_FIELDS))


def _field(facts: dict, field: str):
    value = facts["identity_tokens"][field.split(".", 1)[1]] if field.startswith(
        "identity_tokens.") else facts[field]
    return tuple(sorted(value)) if isinstance(value, list) else value


def _plan_signature(facts: dict) -> tuple:
    plan = routing.plan_question(facts)
    return (plan["scope_status"], plan["answer_mode"],
            tuple((step["action"], step["status"]) for step in plan["steps"]))


def _breakdown(rows: list[dict], key: str) -> dict:
    result = {}
    for value in sorted({row[key] for row in rows}):
        part = [row for row in rows if row[key] == value]
        result[value] = {
            "questions": len(part),
            "jointly_reviewed": sum(row["status"] != "review_failed" for row in part),
            "exact_fact_agreement": sum(row["status"] == "silver_agreed" for row in part),
            "plan_agreement": sum(row["plan_agrees"] for row in part)}
    return result


def merge(frozen_dir: Path, astra_path: Path, gemini_path: Path,
          output: Path) -> dict:
    if output.exists() or output.resolve().is_relative_to(ROOT):
        raise ValueError("v2 fact report needs a new path outside the repository")
    manifest_path = frozen_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    planner_sha = sha_file(Path(routing.__file__))
    extractor_sha = sha_file(Path(extractor.__file__))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            sha_file(frozen_dir / "source_index.jsonl") != manifest["source_index_sha256"] or
            manifest.get("planner_sha256") != planner_sha or
            manifest.get("v2_fact_extractor_sha256") != extractor_sha):
        raise ValueError("frozen cohort or v2 code differs from manifest")
    if ("preflight_report_sha256" in manifest and
            sha_file(frozen_dir / "preflight_report.json") !=
            manifest["preflight_report_sha256"]):
        raise ValueError("source preflight changed")
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
                raise ValueError(f"{family} review is not bound to frozen question")
            if row.get("status") == "ok":
                routing.validate_facts(row.get("facts"))
                expected_media = extractor.MEDIA_FROM_BLIND[question["media_state"]]
                if row["facts"]["media_state"] != expected_media:
                    raise ValueError(f"{family} review claims unavailable media")
            elif row.get("status") != "error" or row.get("facts") is not None:
                raise ValueError("review must have valid facts or explicit error")
            reviews[family, row["id"]] = row
    results = []
    for item_id, question in questions.items():
        left, right = reviews["astra", item_id], reviews["google", item_id]
        valid = left["status"] == right["status"] == "ok"
        disagreements = ([field for field in FIELDS
                          if _field(left["facts"], field) != _field(right["facts"], field)]
                         if valid else [])
        results.append({
            "id": item_id, "language": question["language"],
            "split": sources[item_id]["split"],
            "status": "review_failed" if not valid else
                      "silver_agreed" if not disagreements else "disputed",
            "disagreements": disagreements,
            "plan_agrees": valid and _plan_signature(left["facts"]) == _plan_signature(right["facts"]),
            "silver_facts": left["facts"] if valid and not disagreements else None})
    valid_rows = [row for row in results if row["status"] != "review_failed"]
    report = {
        "schema": "pokemon.public-question-facts-silver.v2",
        "manifest_sha256": sha_file(manifest_path),
        "astra_sha256": sha_file(astra_path),
        "gemini_sha256": sha_file(gemini_path),
        "planner_sha256": planner_sha,
        "extractor_sha256": extractor_sha,
        "questions": len(results), "jointly_reviewed": len(valid_rows),
        "status_counts": dict(sorted(Counter(row["status"] for row in results).items())),
        "field_agreement": {field: sum(field not in row["disagreements"] for row in valid_rows)
                            for field in FIELDS},
        "deterministic_plan_agreement": sum(row["plan_agrees"] for row in valid_rows),
        "by_split": _breakdown(results, "split"),
        "by_language": _breakdown(results, "language"),
        "results": results,
        "interpretation": "Independent AI fact agreement on a frozen question cohort; not human accuracy or market truth"}
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
        "questions", "jointly_reviewed", "status_counts",
        "deterministic_plan_agreement", "by_split", "by_language")},
        ensure_ascii=False))


if __name__ == "__main__":
    main()

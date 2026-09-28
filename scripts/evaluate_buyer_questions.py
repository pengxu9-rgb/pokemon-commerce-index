"""Evaluate frozen buyer-question routing predictions against independent labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pokemon_index import buyer_questions, core


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{number}: expected an object")
                rows.append(value)
    return rows


def _indexed(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    indexed = {}
    for row in rows:
        item_id = row.get("id")
        if not isinstance(item_id, str) or not item_id or item_id in indexed:
            raise ValueError(f"{label} IDs must be nonempty and unique")
        indexed[item_id] = row
    return indexed


def _label(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
            "question_type", "card_id", "target_language"}:
        raise ValueError("question label requires type, card ID and target language")
    kind, card_id, language = (value[key] for key in
                               ("question_type", "card_id", "target_language"))
    if kind != "unsupported" and kind not in buyer_questions.QUESTION_TYPES:
        raise ValueError("unsupported gold question type")
    if card_id is not None and (not isinstance(card_id, str) or not card_id):
        raise ValueError("card ID must be a nonempty string or null")
    if language not in (None, "ja", "en"):
        raise ValueError("unsupported target language")
    if kind == "unsupported" and (card_id is not None or language is not None):
        raise ValueError("unsupported questions must not have a card or target language")
    return value


def evaluate(db: sqlite3.Connection, gold_rows: list[dict[str, Any]],
             prediction_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gold = _indexed(gold_rows, "gold")
    predictions = _indexed(prediction_rows, "prediction")
    if not gold or gold.keys() != predictions.keys():
        raise ValueError("predictions must cover every frozen gold question exactly once")
    results = []
    for item_id, row in gold.items():
        if not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError("gold question text is required")
        expected = _label(row.get("adjudicated"))
        reviewers = row.get("reviewers")
        if (not isinstance(reviewers, list) or len(reviewers) != 2
                or any(not isinstance(review, dict) or not isinstance(review.get("id"), str)
                       or not review["id"].strip() for review in reviewers)
                or reviewers[0]["id"].casefold() == reviewers[1]["id"].casefold()
                or any(_label(review.get("label")) != expected for review in reviewers)):
            raise ValueError("gold requires two distinct agreeing independent review records")
        predicted = predictions[item_id]
        kind = predicted.get("question_type")
        card_id = predicted.get("card_id")
        language = predicted.get("target_language")
        if kind is not None and kind not in buyer_questions.QUESTION_TYPES:
            raise ValueError("prediction has unsupported question type")
        if card_id is not None and (not isinstance(card_id, str) or not card_id):
            raise ValueError("predicted card ID must be a nonempty string or null")
        if language not in (None, "ja", "en"):
            raise ValueError("prediction has unsupported target language")
        if kind is None and (card_id is not None or language is not None):
            raise ValueError("abstention cannot select a card or language")
        error = None
        status = None
        if kind is not None:
            try:
                status = buyer_questions.plan_card_question(db, kind, card_id, language)["status"]
            except ValueError as exc:
                error = str(exc)
        intent_correct = (kind == expected["question_type"] if kind is not None
                          else expected["question_type"] == "unsupported")
        card_correct = card_id == expected["card_id"]
        language_correct = language == expected["target_language"]
        results.append({"id": item_id, "intent_correct": intent_correct,
                        "card_correct": card_correct,
                        "target_language_correct": language_correct,
                        "premature_card_selection": expected["card_id"] is None and card_id is not None,
                        "abstained": kind is None, "plan_status": status,
                        "error": error,
                        "joint_correct": intent_correct and card_correct and language_correct
                                         and error is None})
    return {"schema": "pokemon.buyer-question-eval.v1", "questions": len(results),
            "intent_correct": sum(row["intent_correct"] for row in results),
            "card_correct": sum(row["card_correct"] for row in results),
            "joint_correct": sum(row["joint_correct"] for row in results),
            "premature_card_selections": sum(row["premature_card_selection"] for row in results),
            "abstentions": sum(row["abstained"] for row in results),
            "invalid_plan_inputs": sum(row["error"] is not None for row in results),
            "results": results,
            "interpretation": "Frozen question routing evaluation; not offer, price or image accuracy"}


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def run(db_path: Path, manifest_path: Path, gold_path: Path,
        prediction_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    db = core.connect(":memory:")
    try:
        actual = {
            "printings": source.execute("SELECT COUNT(*) FROM card").fetchone()[0],
            "relationship_assertions": source.execute(
                "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0],
            "verified_relationships": source.execute(
                "SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0],
        }
        if any(manifest["expected"].get(key) != value for key, value in actual.items()):
            raise ValueError("catalog snapshot differs from frozen manifest")
        source.backup(db)
        report = evaluate(db, read_jsonl(gold_path), read_jsonl(prediction_path))
    finally:
        source.close()
        db.close()
    report["source_sha256"] = {name: _sha256(path) for name, path in (
        ("catalog_db", db_path), ("catalog_manifest", manifest_path),
        ("gold", gold_path), ("predictions", prediction_path))}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("evaluation report already exists")
    report = run(args.db, args.manifest, args.gold, args.predictions)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("questions", "joint_correct", "premature_card_selections", "abstentions")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()

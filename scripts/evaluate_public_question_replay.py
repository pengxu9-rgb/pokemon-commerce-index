"""Score a target question router against independently agreed v2 AI fields.

Predictions must be produced without reading source URLs or reviewer labels.
This checks routing decisions only; it does not grade free-text answer claims.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts.public_question_sandbox_v2 import (ACTORS, IDENTITY_STATES, INTENTS,
                                                NEXT_ACTIONS, OBJECT_TYPES,
                                                SCHEMA)

ROUTE_FIELDS = ("actor", "object_type", "primary_intent", "identity_state",
                "next_action")
OPTIONS = {"actor": ACTORS, "object_type": OBJECT_TYPES,
           "primary_intent": INTENTS, "identity_state": IDENTITY_STATES,
           "next_action": NEXT_ACTIONS}


def _rows(path: Path, expected: dict[str, dict], family: str | None = None) -> dict[str, dict]:
    rows = read_jsonl(path)
    if len(rows) != len(expected) or len({row.get("id") for row in rows}) != len(rows):
        raise ValueError("input must cover every frozen question exactly once")
    by_id = {}
    for row in rows:
        question = expected.get(row.get("id"))
        if not question or row.get("question_sha256") != question["question_sha256"]:
            raise ValueError("input does not match frozen question")
        if family and row.get("model_family") != family:
            raise ValueError("review model family mismatch")
        by_id[row["id"]] = row
    return by_id


def evaluate(frozen_dir: Path, astra_path: Path, gemini_path: Path,
             predictions_path: Path) -> dict:
    manifest = json.loads((frozen_dir / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema") != SCHEMA or
            sha_file(frozen_dir / "blind_questions.jsonl") != manifest["blind_sha256"] or
            sha_file(frozen_dir / "source_index.jsonl") != manifest["source_index_sha256"]):
        raise ValueError("frozen question cohort changed")
    questions = {row["id"]: row for row in read_jsonl(frozen_dir / "blind_questions.jsonl")}
    indexes = {row["id"]: row for row in read_jsonl(frozen_dir / "source_index.jsonl")}
    if questions.keys() != indexes.keys():
        raise ValueError("source index does not match blind questions")
    astra = _rows(astra_path, questions, "astra")
    gemini = _rows(gemini_path, questions, "google")
    predictions = _rows(predictions_path, questions)
    results = []
    for item_id, question in questions.items():
        a, g, p = astra[item_id], gemini[item_id], predictions[item_id]
        if p.get("status") not in {"routed", "abstained", "error"}:
            raise ValueError("prediction status must be routed, abstained or error")
        if p["status"] == "routed":
            route = p.get("route")
            if not isinstance(route, dict) or set(route) != set(ROUTE_FIELDS):
                raise ValueError("routed prediction needs all route fields")
            if any(route[key] not in OPTIONS[key] for key in ROUTE_FIELDS):
                raise ValueError("prediction uses an unsupported route value")
        elif p.get("route") is not None:
            raise ValueError("abstained or errored prediction cannot supply a route")
        selected = p.get("selected_card_id")
        if selected is not None and (p["status"] != "routed" or
                                     not isinstance(selected, str) or not selected):
            raise ValueError("selected_card_id requires a routed prediction")
        if a.get("status") == "ok" and g.get("status") == "ok":
            agreed = {key: a["label"][key] for key in ROUTE_FIELDS
                      if a["label"][key] == g["label"][key]}
        else:
            agreed = {}
        matches = {key: p["status"] == "routed" and p["route"][key] == value
                   for key, value in agreed.items()}
        identity_states = {row["label"]["identity_state"] for row in (a, g)
                           if row.get("status") == "ok"}
        possible_premature = selected is not None and (not identity_states or
                              any(state != "exact_in_text" for state in identity_states))
        results.append({"id": item_id, "split": indexes[item_id]["split"],
                        "language": question["language"],
                        "prediction_status": p["status"],
                        "agreed_fields": sorted(agreed), "field_matches": matches,
                        "selected_card_id": selected,
                        "possible_premature_card_selection": possible_premature})
    by_split = {}
    for split in ("development", "holdout"):
        subset = [row for row in results if row["split"] == split]
        by_split[split] = {
            "questions": len(subset),
            "prediction_status": dict(sorted(Counter(
                row["prediction_status"] for row in subset).items())),
            "possible_premature_card_selections": sum(
                row["possible_premature_card_selection"] for row in subset),
            "fields": {key: {
                "evaluable": sum(key in row["agreed_fields"] for row in subset),
                "matched": sum(row["field_matches"].get(key, False) for row in subset)}
                for key in ROUTE_FIELDS},
        }
    return {"schema": "pokemon.public-question-replay.v2",
            "question_count": len(results),
            "source_sha256": {"manifest": sha_file(frozen_dir / "manifest.json"),
                              "astra": sha_file(astra_path),
                              "gemini": sha_file(gemini_path),
                              "predictions": sha_file(predictions_path)},
            "by_split": by_split, "results": results,
            "interpretation": "Agreement with dual-AI silver routing fields, not human accuracy or answer-text safety"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", type=Path, required=True)
    parser.add_argument("--astra", type=Path, required=True)
    parser.add_argument("--gemini", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("replay report already exists")
    report = evaluate(args.frozen_dir, args.astra, args.gemini, args.predictions)
    args.output.write_text(json.dumps(report, ensure_ascii=False,
                                sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"question_count": report["question_count"],
                      "by_split": report["by_split"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

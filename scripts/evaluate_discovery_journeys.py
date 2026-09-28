"""Replay hand-authored buyer journeys against a frozen internal catalog."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from pokemon_index import core, discovery_graph

SCHEMA = "pokemon.discovery-buyer-journeys.v1"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def evaluate(db: sqlite3.Connection, suite: dict[str, Any]) -> dict[str, Any]:
    if suite.get("schema") != SCHEMA:
        raise ValueError("unknown buyer journey schema")
    journeys = suite.get("journeys")
    if not isinstance(journeys, list) or not journeys:
        raise ValueError("buyer journey suite is empty")
    ids = [row.get("id") for row in journeys]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("buyer journey IDs must be nonempty and unique")
    results = []
    for journey in journeys:
        steps = journey.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("every buyer journey needs steps")
        session_id = "eval:" + journey["id"]
        owner = "offline-journey-evaluator"
        previous_candidates: set[str] = set()
        for position, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("expect"), dict):
                raise ValueError("journey step and expected result must be objects")
            target = step.get("target_card_id")
            if target and target not in previous_candidates:
                raise ValueError("selected target was not shown in the preceding step")
            row = {"session_id": session_id, "owner_key": owner,
                   "expected_version": position, "constraints": step.get("constraints", {})}
            if target:
                row["target_card_id"] = target
            if "status" in step:
                row["status"] = step["status"]
            discovery_graph.save_exploration(db, row)
            decision = discovery_graph.exploration_decision(db, session_id, owner)
            previous_candidates = {card["card_id"] for card in decision["candidate_cards"]}
            expected = step["expect"]
            question = decision["next_question"]
            actual_next = question["field"] if question else None
            errors = []
            for field, actual in (("code", decision["code"]),
                                  ("next_field", actual_next),
                                  ("ready_for_offer_tracking", decision["ready_for_offer_tracking"])):
                if field in expected and expected[field] != actual:
                    errors.append(f"{field}: expected {expected[field]!r}, got {actual!r}")
            if decision["candidate_count"] < expected.get("min_candidates", 0):
                errors.append("candidate count below expected minimum")
            if ("max_candidates" in expected and
                    decision["candidate_count"] > expected["max_candidates"]):
                errors.append("candidate count above expected maximum")
            if expected.get("required_card_id") and expected["required_card_id"] not in previous_candidates:
                errors.append("required card not shown among returned candidates")
            for basis in expected.get("basis_contains", []):
                if basis not in decision["candidate_basis"]:
                    errors.append(f"missing candidate basis: {basis}")
            for basis in expected.get("basis_absent", []):
                if basis in decision["candidate_basis"]:
                    errors.append(f"unexpected candidate basis: {basis}")
            for field in expected.get("pending_market_filters", []):
                if field not in decision["pending_market_filters"]:
                    errors.append(f"missing pending market filter: {field}")
            if expected.get("next_prompt_contains") and (not question or
                    expected["next_prompt_contains"] not in question["prompt"]):
                errors.append("next prompt lacks required phrase")
            if "no live offers" not in decision["scope"]:
                errors.append("discovery decision omitted its market-data scope")
            results.append({"journey_id": journey["id"], "step": position + 1,
                            "utterance": step.get("utterance"),
                            "passed": not errors, "errors": errors,
                            "candidate_count": decision["candidate_count"],
                            "code": decision["code"], "next_field": actual_next,
                            "candidate_basis": decision["candidate_basis"]})
    passed = sum(row["passed"] for row in results)
    return {"schema": SCHEMA, "journeys": len(journeys), "steps": len(results),
            "passed": passed, "failed": len(results) - passed, "results": results,
            "interpretation": "Hand-authored structured intent regression, not real-user relevance or natural-language parsing accuracy"}


def run(catalog_db: Path, catalog_manifest: Path, suite_path: Path) -> dict[str, Any]:
    manifest = json.loads(catalog_manifest.read_text(encoding="utf-8"))
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    source = sqlite3.connect(f"file:{catalog_db.resolve()}?mode=ro", uri=True)
    db = core.connect(":memory:")
    try:
        expected = manifest.get("expected", {})
        counts = {
            "printings": source.execute("SELECT COUNT(*) FROM card").fetchone()[0],
            "match_eligible": source.execute(
                "SELECT COUNT(*) FROM card WHERE match_eligible=1").fetchone()[0],
            "relationship_assertions": source.execute(
                "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0],
            "verified_relationships": source.execute(
                "SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0],
            "ai_artwork_proposals": source.execute(
                """SELECT COUNT(*) FROM card_relationship_assertion
                WHERE relation_type='same_artwork' AND review_status='proposed'
                AND asserted_by='ai-artwork-review-v1'""").fetchone()[0],
        }
        if any(counts[key] != expected.get(key) for key in counts):
            raise ValueError("catalog snapshot differs from build manifest")
        source.backup(db)
        report = evaluate(db, suite)
    finally:
        source.close()
        db.close()
    report["catalog_db_sha256"] = _sha256(catalog_db)
    report["catalog_manifest_sha256"] = _sha256(catalog_manifest)
    report["suite_sha256"] = _sha256(suite_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("buyer journey report already exists")
    report = run(args.db, args.manifest, args.suite)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("journeys", "steps", "passed", "failed")},
                     ensure_ascii=False))
    if report["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

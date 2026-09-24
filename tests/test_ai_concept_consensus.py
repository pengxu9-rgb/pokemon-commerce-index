import copy
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core
from scripts import compile_ai_concept_consensus as compiler
from scripts.relationship_pilot import read_jsonl


ROOT = Path(__file__).resolve().parents[1]


class AiConceptConsensusTests(unittest.TestCase):
    def setUp(self):
        self.queue = read_jsonl(ROOT / "catalog/concept-review-v2-queue.jsonl")
        self.astra = compiler._csv_by_id(ROOT / "catalog/concept-review-v2-ai-triage.csv")
        self.sol = compiler._csv_by_id(ROOT / "catalog/concept-review-v2-sol-review.csv")

    def test_agreement_imports_attributed_concepts_not_verified_printings(self):
        bundle, edges = compiler.compile_consensus(
            self.queue, self.astra, self.sol, "2026-09-24T09:00:00Z")
        self.assertEqual(len(bundle["review_events"]), 39)
        self.assertEqual(len(bundle["concept_revisions"]), 21)
        self.assertEqual(len(edges), 21)
        self.assertTrue(all(edge["review_status"] == "proposed" and
                            edge["relation_type"] == "collecting_alternative"
                            for edge in edges))
        self.assertTrue(all(event["review"]["review_basis"] ==
                            compiler.REVIEW_BASIS for event in bundle["review_events"]))
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        core.init_db(db)
        self.assertEqual(core.import_concept_review_bundle(db, bundle),
                         {"review_events": 39, "concept_revisions": 21})
        self.assertEqual(core.import_concept_review_bundle(db, bundle),
                         {"review_events": 0, "concept_revisions": 0})
        db.close()

    def test_disagreement_or_changed_source_fails_closed(self):
        sol = copy.deepcopy(self.sol)
        pid = self.queue[0]["proposal_id"]
        sol[pid]["suggested_decision"] = "reject"
        with self.assertRaisesRegex(ValueError, "disagree"):
            compiler.compile_consensus(self.queue, self.astra, sol,
                                       "2026-09-24T09:00:00Z")
        astra = copy.deepcopy(self.astra)
        astra[pid]["source_snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "pinned evidence"):
            compiler.compile_consensus(self.queue, astra, self.sol,
                                       "2026-09-24T09:00:00Z")

    def test_later_batch_defers_disagreement_and_requires_both_source_digests(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v3-queue.jsonl")[:2]
        astra = {row["proposal_id"]: {
            "proposal_id": row["proposal_id"],
            "source_snapshot_sha256": row["source_snapshot_sha256"],
            "suggested_decision": "approve", "rationale": "independent first review",
            "evidence_limits": "source text only",
        } for row in queue}
        sol = copy.deepcopy(astra)
        sol[queue[1]["proposal_id"]]["suggested_decision"] = "reject"
        bundle, edges = compiler.compile_consensus(
            queue, astra, sol, "2026-09-24T09:00:00Z", "v3", True)
        self.assertEqual((len(bundle["review_events"]), len(edges)), (1, 1))
        self.assertEqual(bundle["audit"]["deferred_rows"], 1)
        self.assertTrue(edges[0]["assertion_id"].startswith("concept-candidate-v3:"))
        sol[queue[0]["proposal_id"]]["source_snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "pinned evidence"):
            compiler.compile_consensus(queue, astra, sol,
                                       "2026-09-24T09:00:00Z", "v3", True)

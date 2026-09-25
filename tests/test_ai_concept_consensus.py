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

    def test_v5_retains_only_agreed_reviews_and_proposed_edges(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v5-queue.jsonl")
        astra = compiler._csv_by_id(ROOT / "catalog/concept-review-v5-astra.csv")
        sol = compiler._csv_by_id(ROOT / "catalog/concept-review-v5-sol.csv")
        bundle, edges = compiler.compile_consensus(
            queue, astra, sol, "2026-09-25T00:00:00Z", "v5", True)
        self.assertEqual(bundle["audit"]["decisions"], {"approve": 24, "reject": 100})
        self.assertEqual(bundle["audit"]["deferred_rows"], 1)
        self.assertEqual(len(bundle["review_events"]), 124)
        self.assertEqual(len(bundle["concept_revisions"]), 24)
        self.assertEqual(len(edges), 24)
        self.assertTrue(all(edge["review_status"] == "proposed" for edge in edges))

    def test_v6_stage_can_compile_a_bounded_review(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v6-stage1-queue.jsonl")[:1]
        row = {"proposal_id": queue[0]["proposal_id"],
               "source_snapshot_sha256": queue[0]["source_snapshot_sha256"],
               "suggested_decision": "reject", "rationale": "synthetic independent review"}
        bundle, edges = compiler.compile_consensus(
            queue, {row["proposal_id"]: row}, {row["proposal_id"]: row},
            "2026-09-25T00:00:00Z", "v6", True)
        self.assertEqual((len(bundle["review_events"]), len(edges)), (1, 0))

    def test_v6_triple_review_requires_source_bound_multimodal_agreement(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v6-stage1-queue.jsonl")[:1]
        row = {"proposal_id": queue[0]["proposal_id"],
               "source_snapshot_sha256": queue[0]["source_snapshot_sha256"],
               "suggested_decision": "approve", "rationale": "independent source comparison",
               "image_evidence": "both source-matched card scans checked"}
        reviews = {row["proposal_id"]: row}
        image = {"status": "included", "image_sha256": "a" * 64}
        audit = {"model": "gemini-3.8-flash",
                 "pinned_revision": "a211f11f3ba57d56c65c5ac33be35b77d3280757",
                 "rows": [{"proposal_id": row["proposal_id"],
                           "model_version": "gemini-3.8-flash",
                           "ja_image": image, "en_image": image,
                           "request_sha256": "b" * 64, "response_sha256": "c" * 64}]}
        bundle, edges = compiler.compile_consensus(
            queue, reviews, reviews, "2026-09-25T00:00:00Z", "v6", True,
            reviews, audit)
        self.assertEqual((len(bundle["review_events"]), len(edges)), (1, 1))
        self.assertEqual(len(bundle["review_events"][0]["review"]["ai_reviews"]), 3)
        audit["rows"][0]["ja_image"] = {"status": "image_missing"}
        partial, partial_edges = compiler.compile_consensus(
            queue, reviews, reviews, "2026-09-25T00:00:00Z", "v6", True,
            reviews, audit)
        self.assertEqual((len(partial["review_events"]), len(partial_edges)), (1, 1))
        self.assertFalse(partial["review_events"][0]["review"]["ai_reviews"][2]
                         ["image_pair_checked"])

import csv
import tempfile
import unittest
from pathlib import Path

from scripts import concept_review_staged
from scripts.relationship_pilot import read_jsonl


ROOT = Path(__file__).resolve().parents[1]


class StagedConceptReviewTests(unittest.TestCase):
    def test_v5_first_stage_and_historical_replay(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v5-queue.jsonl")
        first, audit = concept_review_staged.select_next(queue, {})
        self.assertEqual((len(first), audit["ranked_names"]), (25, 25))
        self.assertTrue(all(row["source_snapshot"]["rank"]["position"] == 1
                            for row in first))
        reviews = concept_review_staged.read_dual_reviews(
            queue, ROOT / "catalog/concept-review-v5-astra.csv",
            ROOT / "catalog/concept-review-v5-sol.csv")
        remaining, replay = concept_review_staged.select_next(
            queue, reviews, replay_full=True)
        self.assertEqual(remaining, [])
        self.assertEqual(replay["sequential_review_slots"], 42)
        self.assertEqual(replay["avoided_review_rows"], 83)
        self.assertEqual(replay["outcomes"], {"approved_by_ai": 24, "deferred": 1})

    def test_v4_replay_keeps_all_agreed_approvals(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v4-queue.jsonl")
        reviews = concept_review_staged.read_dual_reviews(
            queue, ROOT / "catalog/concept-review-v4-astra.csv",
            ROOT / "catalog/concept-review-v4-sol.csv")
        _, replay = concept_review_staged.select_next(queue, reviews, replay_full=True)
        self.assertEqual(replay["sequential_review_slots"], 56)
        self.assertEqual(replay["outcomes"], {"approved_by_ai": 19,
                                               "deferred": 2, "exhausted": 4})

    def test_advance_only_after_agreed_reject_and_bind_both_sources(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v5-queue.jsonl")
        first, _ = concept_review_staged.select_next(queue, {})
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / name for name in ("astra.csv", "sol.csv")]
            for path in paths:
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=(
                        "proposal_id", "source_snapshot_sha256", "suggested_decision", "rationale"))
                    writer.writeheader()
                    for row in first:
                        writer.writerow({"proposal_id": row["proposal_id"],
                                         "source_snapshot_sha256": row["source_snapshot_sha256"],
                                         "suggested_decision": "reject",
                                         "rationale": "synthetic review for scheduling test"})
            reviews = concept_review_staged.read_dual_reviews(queue, *paths)
            second, audit = concept_review_staged.select_next(queue, reviews)
            self.assertEqual(len(second), 25)
            self.assertEqual(audit["reviewed_proposals"], 25)
            self.assertTrue(all(row["source_snapshot"]["rank"]["position"] == 2
                                for row in second))
            content = paths[1].read_text().replace(first[0]["source_snapshot_sha256"], "0" * 64)
            paths[1].write_text(content)
            with self.assertRaisesRegex(ValueError, "snapshot mismatch"):
                concept_review_staged.read_dual_reviews(queue, *paths)

    def test_agreement_or_uncertainty_stops_name_and_skips_are_rejected(self):
        queue = read_jsonl(ROOT / "catalog/concept-review-v5-queue.jsonl")
        first, _ = concept_review_staged.select_next(queue, {})
        decisions = {first[0]["proposal_id"]: ("approve", "approve"),
                     first[1]["proposal_id"]: ("approve", "reject")}
        selected, audit = concept_review_staged.select_next(queue, decisions)
        self.assertEqual(len(selected), 23)
        self.assertEqual(audit["outcomes"]["approved_by_ai"], 1)
        self.assertEqual(audit["outcomes"]["deferred"], 1)
        second_for_first = next(row for row in queue
                                if row["name_ja"] == first[0]["name_ja"]
                                and row["source_snapshot"]["rank"]["position"] == 2)
        with self.assertRaisesRegex(ValueError, "after name was stopped"):
            concept_review_staged.select_next(queue, {
                **decisions, second_for_first["proposal_id"]: ("reject", "reject")})
        with self.assertRaisesRegex(ValueError, "skipped a prior rank"):
            concept_review_staged.select_next(queue, {
                second_for_first["proposal_id"]: ("reject", "reject")})

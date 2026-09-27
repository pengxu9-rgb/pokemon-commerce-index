import csv
import json
import unittest
from collections import Counter
from pathlib import Path

from scripts.relationship_pilot import read_jsonl


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class RelationshipScaleResultsTests(unittest.TestCase):
    def test_legacy_asset_review_adds_only_source_bound_proposals(self):
        previous = read_jsonl(CATALOG / "relationship-scale-v1-proposed-edges-v3.jsonl")
        current = read_jsonl(CATALOG / "relationship-scale-v1-proposed-edges-v4.jsonl")
        delta = read_jsonl(CATALOG / "relationship-scale-v1-legacy-en-proposed-edges.jsonl")
        assets = read_jsonl(CATALOG / "relationship-scale-v1-legacy-en-assets.jsonl")
        current_ids = {row["assertion_id"] for row in current}
        old_ids = {row["assertion_id"] for row in previous}
        self.assertEqual((len(previous), len(current), len(delta), len(assets)),
                         (649, 657, 8, 8))
        self.assertEqual({row["assertion_id"] for row in delta}, current_ids - old_ids)
        self.assertTrue(all(row["review_status"] == "proposed" for row in delta))
        self.assertTrue(all(not json.loads(row["evidence_ref"])["price_comparable"]
                            for row in delta))

    def test_recovered_visual_pairs_only_add_proposed_graph_edges(self):
        first = read_jsonl(CATALOG / "relationship-scale-v1-proposed-edges.jsonl")
        expanded = read_jsonl(CATALOG / "relationship-scale-v1-proposed-edges-v3.jsonl")
        delta = read_jsonl(CATALOG / "relationship-scale-v1-recovery-proposed-edges.jsonl")
        scopes = read_jsonl(CATALOG / "relationship-scale-v1-comparability-v3.jsonl")
        ids_first = {row["assertion_id"] for row in first}
        ids_new = {row["assertion_id"] for row in expanded}
        self.assertEqual(len(first), 587)
        self.assertEqual(len(expanded), 649)
        self.assertEqual({row["assertion_id"] for row in delta}, ids_new - ids_first)
        self.assertEqual(len(delta), 62)
        self.assertEqual(len(scopes), 1000)
        for row in expanded:
            self.assertEqual(row["review_status"], "proposed")
            self.assertFalse(json.loads(row["evidence_ref"])["price_comparable"])
        for row in scopes:
            self.assertFalse(row["price_series_merge_allowed"])
            self.assertFalse(row["numeric_cross_region_spread_allowed"])

    def test_japanese_visual_retry_preserves_all_pending_printings(self):
        queue = read_jsonl(CATALOG / "ja-variant-review-all-queue.jsonl")
        visual = read_jsonl(CATALOG / "ja-variant-artwork-ai-v2.jsonl")
        audit = json.loads((CATALOG / "ja-variant-artwork-ai-v2-audit.json").read_text())
        followup = read_jsonl(CATALOG / "ja-variant-artwork-followup-v2.jsonl")
        self.assertEqual(len(queue), len(visual), audit["groups"])
        self.assertEqual(audit["statuses"], {"ai_visual_candidate": 456,
                                             "image_unavailable": 6})
        self.assertEqual(audit["labels"], {"exact_artwork": 499})
        self.assertEqual(len(followup), 279)
        for source, row in zip(queue, visual):
            self.assertEqual(source["card_id"], row["card_id"])
            self.assertFalse(row["printing_verified"])
            self.assertFalse(row["match_eligible_changed"])

    def test_visual_batch_covers_every_pair_without_price_promotion(self):
        queue = read_jsonl(CATALOG / "relationship-scale-v1-queue.jsonl")
        with (CATALOG / "relationship-scale-v1-gemini.csv").open(newline="") as handle:
            visual = list(csv.DictReader(handle))
        audit = json.loads((CATALOG / "relationship-scale-v1-gemini-audit.json").read_text())
        analysis = json.loads((CATALOG / "relationship-scale-v1-visual-analysis.json").read_text())
        numbering = json.loads((CATALOG / "relationship-scale-v1-numbering-audit.json").read_text())
        proposals = read_jsonl(CATALOG / "relationship-scale-v1-proposed-edges.jsonl")
        self.assertEqual(len(queue), len(visual), audit["candidate_rows"])
        self.assertEqual(len(queue), 1000)
        self.assertEqual({row["candidate_id"] for row in queue},
                         {row["candidate_id"] for row in visual})
        counts = dict(Counter(row["artwork_decision"] for row in visual))
        self.assertEqual(counts, audit["decisions"])
        self.assertEqual(counts, analysis["visual_decisions"])
        self.assertEqual(counts["same"], len(proposals))
        self.assertEqual(numbering["by_visual_decision"]["same"]["pairs"],
                         len(proposals))
        self.assertEqual(sum(numbering["by_visual_decision"]["same"][key]
                             for key in (
                                 "same_numerator__same_denominator",
                                 "same_numerator__different_denominator",
                                 "different_numerator__same_denominator",
                                 "different_numerator__different_denominator")),
                         len(proposals))
        for row in proposals:
            self.assertEqual(row["review_status"], "proposed")
            self.assertEqual(row["relation_type"], "same_artwork")
            self.assertFalse(json.loads(row["evidence_ref"])["price_comparable"])

    def test_variant_hash_batch_covers_all_groups_without_printing_claims(self):
        queue = read_jsonl(CATALOG / "ja-variant-review-all-queue.jsonl")
        images = read_jsonl(CATALOG / "ja-variant-image-hash-evidence.jsonl")
        audit = json.loads((CATALOG / "ja-variant-image-hash-audit.json").read_text())
        self.assertEqual(len(queue), len(images), audit["groups"])
        self.assertEqual(audit["groups_complete"], len(images))
        self.assertEqual(audit["groups_distinct_image_bytes"], len(images))
        self.assertEqual(audit["groups_identical_image_bytes"], 0)
        for source, result in zip(queue, images):
            self.assertEqual(source["card_id"], result["card_id"])
            self.assertEqual(source["source_record_sha256"],
                             result["source_record_sha256"])
            self.assertFalse(result["printing_verified"])
            self.assertFalse(result["match_eligible_changed"])
            self.assertEqual(len(result["records"]),
                             result["distinct_image_byte_hashes"])
            self.assertNotIn("image_url", result)


if __name__ == "__main__":
    unittest.main()

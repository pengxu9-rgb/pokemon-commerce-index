import csv
import json
import unittest
from collections import Counter
from pathlib import Path

from scripts.calibrate_relationship_artwork import analyze, prepare, prepare_taxonomy
from scripts.relationship_pilot import read_jsonl


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class RelationshipCalibrationTests(unittest.TestCase):
    def test_frozen_stratified_sample_covers_all_negatives_and_unresolved(self):
        queue = read_jsonl(CATALOG / "relationship-scale-v1-queue.jsonl")
        with (CATALOG / "relationship-scale-v1-gemini.csv").open(newline="") as handle:
            first = list(csv.DictReader(handle))
        audit = json.loads((CATALOG / "relationship-scale-v1-gemini-audit.json").read_text())
        sample, report = prepare(queue, first, audit)
        self.assertEqual(sample, read_jsonl(CATALOG / "relationship-scale-v1-calibration-sample.jsonl"))
        self.assertEqual(len(sample), 212)
        self.assertEqual(Counter(row["first_decision"] for row in sample),
                         {"same": 150, "different": 50, "uncertain": 3, "model_error": 9})
        self.assertEqual(len(report["positive_quota_by_retrieval_stratum"]), 7)
        self.assertTrue(all(row["ja_image"]["sha256"] and row["en_image"]["sha256"]
                            for row in sample))
        changed = [dict(row) for row in first]
        changed[0]["source_snapshot_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source snapshot mismatch"):
            prepare(queue, changed, audit)

    def test_second_pass_is_agreement_only_with_no_graph_promotion(self):
        path = CATALOG / "relationship-scale-v1-calibration-second.jsonl"
        sample = read_jsonl(CATALOG / "relationship-scale-v1-calibration-sample.jsonl")
        second = read_jsonl(path)
        report, followup = analyze(sample, second)
        self.assertEqual(report["sample_rows"], 212)
        self.assertEqual(report["same_agreement"]["n"], 149)
        self.assertEqual(report["same_agreement"]["model_answered_denominator"], 149)
        self.assertEqual(report["different_agreement"]["n"], 47)
        self.assertEqual(report["different_agreement"]["model_answered_denominator"], 50)
        self.assertEqual(report["source_image_changed"], 10)
        self.assertEqual(report["verified_graph_edges_created"], 0)
        self.assertFalse(report["price_comparability_inferred"])
        self.assertEqual(len(followup), report["disagreements_or_abstentions"])

    def test_recolor_challenge_keeps_derived_artwork_out_of_price_merges(self):
        queue = read_jsonl(CATALOG / "relationship-scale-v1-queue.jsonl")
        with (CATALOG / "relationship-scale-v1-gemini.csv").open(newline="") as handle:
            first = list(csv.DictReader(handle))
        audit = json.loads((CATALOG / "relationship-scale-v1-gemini-audit.json").read_text())
        sample, report = prepare_taxonomy(queue, first, audit)
        self.assertEqual(sample, read_jsonl(CATALOG / "relationship-scale-v1-recolor-sample.jsonl"))
        self.assertEqual(report["first_decisions"], {"same": 10, "different": 8})
        taxonomy = read_jsonl(CATALOG / "relationship-scale-v1-recolor-results.jsonl")
        self.assertEqual(Counter(row["category"] for row in taxonomy),
                         {"exact": 10, "derived_recolor": 5, "different": 3})
        proposals = read_jsonl(CATALOG / "relationship-scale-v1-derived-recolor-candidates.jsonl")
        self.assertEqual(len(proposals), 5)
        self.assertTrue(all(not row["graph_import_allowed"] and
                            not row["price_series_merge_allowed"] for row in proposals))
        comparison = json.loads((CATALOG / "relationship-scale-v1-comparability-v2-audit.json").read_text())
        self.assertEqual(comparison["comparison_scope"]["derived_artwork_candidate"], 5)
        self.assertEqual(comparison["price_series_merge_allowed"], 0)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_question_v3_catalog import evaluate
from scripts.public_question_sandbox import sha_file


ROOT = Path(__file__).resolve().parents[1]
COHORT = ROOT / "sandbox/public_questions/v7"


@unittest.skipUnless((ROOT / "catalog-index.sqlite3").exists(),
                     "private catalog snapshot is not present")
class QuestionV3CatalogReplayTests(unittest.TestCase):
    def test_fresh_cohort_is_bound_to_inputs_and_never_unlocks_market_claims(self):
        saved = json.loads((COHORT / "catalog_route_report.json").read_text())
        self.assertEqual(saved["manifest_sha256"], sha_file(COHORT / "manifest.json"))
        self.assertEqual(saved["facts_sha256"], sha_file(COHORT / "gemini_facts.jsonl"))
        with tempfile.TemporaryDirectory() as directory:
            report = evaluate(COHORT, COHORT / "gemini_facts.jsonl",
                              ROOT / "catalog-index.sqlite3", Path(directory) / "report.json")
        self.assertEqual(report, saved)
        self.assertEqual((report["questions"], report["valid_facts"]), (8, 8))
        self.assertEqual(report["catalog_statuses"], {
            "multiple_candidates": 2, "no_match": 2, "not_attempted": 4})
        self.assertFalse(any(row["catalog_status"] == "unique" for row in report["rows"]))
        self.assertFalse(any(step["status"] == "ready" and step["action"] in {
            "retrieve_live_offers", "retrieve_verified_sales"}
            for row in report["rows"] for step in row["actions"]))

    def test_changed_question_binding_rejects_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            facts = [json.loads(line) for line in
                     (COHORT / "gemini_facts.jsonl").read_text().splitlines()]
            facts[0]["question_sha256"] = "0" * 64
            path = Path(directory) / "changed.jsonl"
            path.write_text("".join(json.dumps(row) + "\n" for row in facts))
            with self.assertRaisesRegex(ValueError, "different question"):
                evaluate(COHORT, path, ROOT / "catalog-index.sqlite3",
                         Path(directory) / "report.json")


if __name__ == "__main__":
    unittest.main()

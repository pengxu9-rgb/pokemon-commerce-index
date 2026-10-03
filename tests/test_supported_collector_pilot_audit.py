"""Focused offline tests for the read-only pilot measurement boundary."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pokemon_index import collector_journey, core
from scripts.audit_supported_collector_pilot import audit, inspect_record, run, unexpected_approvals


class SupportedPilotAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "catalog.sqlite3"
        with closing(core.connect(self.path)) as db:
            core.init_db(db)
            for number, eligible in [("001/100", True), ("002/100", False)]:
                core.import_cards(db, [{"language": "ja", "set_code": "SV4A",
                    "collector_number": number, "variant": "normal", "name": "Pikachu",
                    "match_eligible": eligible, "provenance": "synthetic:pilot-audit",
                    "rights_reference": "synthetic:no-public-display"}])
                db.execute("INSERT INTO card_facet VALUES (?,?,?,?,?)",
                           (f"ja:SV4A:{number}:normal", "dex_id", "25",
                            "synthetic:pilot-audit", "synthetic:no-public-display"))
            db.commit()
        self.db = core.connect(self.path, readonly=True)
        self.revision = collector_journey.catalog_revision(self.db)
        self.good = "ja:SV4A:001/100:normal"
        self.held = "ja:SV4A:002/100:normal"

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def suite(self):
        return {"schema": "pokemon.supported-collector-pilot-questions.v1", "questions": [{
            "id": "synthetic-exact", "family": "synthetic", "turns": [{
                "type": "ask", "question": self.good}],
            "expect": {"required_anchor_ids": [self.good], "selection_allowed": True}}]}

    def test_structural_record_can_select_without_gaining_support_or_commerce(self):
        result = inspect_record(self.db, self.good, self.revision)
        self.assertTrue(result["discoverable_by_exact_id"])
        self.assertTrue(result["catalog_selection_eligible"])
        self.assertTrue(result["catalog_intent_roundtrip"])
        self.assertEqual(result["support_status"], "research_candidate")
        self.assertFalse(result["current_supported_and_selection_eligible"])
        self.assertFalse(result["physical_printing_approval_exposed"])
        self.assertFalse(result["automatic_offer_join_approval_exposed"])
        self.assertEqual(result["unexpected_approval_paths"], [])

    def test_disabled_record_remains_discoverable_but_cannot_select(self):
        result = inspect_record(self.db, self.held, self.revision)
        self.assertTrue(result["discoverable_by_exact_id"])
        self.assertFalse(result["catalog_selection_eligible"])
        self.assertFalse(result["catalog_intent_roundtrip"])
        self.assertIn("match_disabled_identity", result["blockers"])

    def test_empty_supported_cohort_does_not_promote_broad_research(self):
        report = audit(self.db, self.suite())
        self.assertEqual(report["catalog_counts"]["source_records"], 2)
        self.assertEqual(report["stage_counts"]["currently_supported_records"], 0)
        self.assertEqual(report["question_summary"]["passed"], 1)
        question = report["questions"][0]
        self.assertEqual(question["returned_supported_ids"], [])
        self.assertEqual(question["returned_research_ids"], [self.good])
        self.assertFalse(question["full_result_precision_or_recall_established"])

    def test_relevance_and_selectability_have_separate_denominators(self):
        suite = self.suite()
        suite["questions"][0].update(turns=[{"type": "ask", "question": "Recommend Japanese Pikachu cards"}],
                                      expect={"returned_facet": {"field": "dex_id", "value": 25}})
        question = audit(self.db, suite)["questions"][0]
        self.assertTrue(question["passed"])
        self.assertEqual(question["requested_facet_matching_records"], 2)
        self.assertEqual(question["selection_eligible_records"], 1)
        self.assertEqual(question["reason_checks"], 2)
        self.assertEqual(question["reason_checks_passed"], 2)

    def test_stale_support_is_counted_separately_from_selection(self):
        self.db.close()
        with closing(core.connect(self.path)) as db:
            db.execute("INSERT INTO supported_card VALUES (?,?,?,?)",
                       (self.good, "{}", "0" * 64, "catalog_discovery_and_listing_review"))
            db.commit()
        self.db = core.connect(self.path, readonly=True)
        report = audit(self.db, self.suite())
        self.assertEqual(report["stage_counts"]["declared_support_records"], 1)
        self.assertEqual(report["stage_counts"]["catalog_selection_eligible"], 1)
        self.assertEqual(report["stage_counts"]["currently_supported_records"], 0)
        self.assertEqual(report["stage_counts"]["current_supported_and_selection_eligible"], 0)
        self.assertEqual(report["support_status_counts"], {"stale_support_evidence": 1})

    def test_missing_anchor_and_runtime_error_remain_in_denominator(self):
        suite = self.suite()
        suite["questions"][0]["expect"]["required_anchor_ids"].append(self.held)
        suite["questions"].append({"id": "bad-turn", "family": "synthetic",
                                   "turns": [{"type": "invented"}]})
        report = audit(self.db, suite)
        self.assertEqual(report["question_summary"], {"total": 2, "passed": 0, "failed": 2})
        self.assertIn("missing_supported_anchors", report["questions"][0]["errors"])
        self.assertEqual(report["questions"][1]["errors"], ["runtime_error"])

    def test_nested_approvals_and_nonempty_market_data_are_rejected(self):
        value = {"comparison": {"cards": [{"automatic_offer_join_allowed": True}]},
                 "prices": [{"price_minor": 100}]}
        self.assertEqual(len(unexpected_approvals(value)), 2)
        self.assertEqual(unexpected_approvals({"physical_printing_verified": False, "prices": []}), [])

    def test_run_is_readonly_and_refuses_to_overwrite_evidence(self):
        suite_path = Path(self.temp.name) / "suite.json"
        output = Path(self.temp.name) / "report.json"
        suite_path.write_text(json.dumps(self.suite()))
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = run(self.path, suite_path, output)
        self.assertTrue(report["catalog_bytes_unchanged"])
        self.assertEqual(report["catalog_sha256"], before)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        with self.assertRaises(FileExistsError):
            run(self.path, suite_path, output)


if __name__ == "__main__":
    unittest.main()

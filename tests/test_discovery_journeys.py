import unittest

from pokemon_index import core
from scripts.evaluate_discovery_journeys import SCHEMA, evaluate


class DiscoveryJourneyEvalTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(":memory:")
        core.init_db(self.db)
        core.import_cards(self.db, [{"match_eligible": True, "language": "ja", "set_code": "SV2a",
                                     "collector_number": "025/165", "variant": "normal",
                                     "name": "ピカチュウ", "provenance": "fixture",
                                     "rights_reference": "fixture"}])

    def tearDown(self):
        self.db.close()

    def test_replays_target_selection_and_detects_wrong_expectation(self):
        suite = {"schema": SCHEMA, "journeys": [{"id": "single-card", "steps": [
            {"utterance": "The Japanese SV2a 025/165 card",
             "constraints": {"language": "ja", "set_code": "SV2a",
                             "collector_number": "025/165"},
             "expect": {"code": "confirm_target", "next_field": "target_card_id",
                        "required_card_id": "ja:SV2A:025/165:normal"}},
            {"utterance": "Yes", "target_card_id": "ja:SV2A:025/165:normal",
             "expect": {"code": "target_selected", "next_field": None,
                        "ready_for_offer_tracking": True}},
        ]}]}
        report = evaluate(self.db, suite)
        self.assertEqual((report["passed"], report["failed"]), (2, 0))
        suite["journeys"][0]["id"] = "wrong-expectation"
        suite["journeys"][0]["steps"][0]["expect"]["code"] = "no_matches"
        failed = evaluate(self.db, suite)
        self.assertEqual((failed["passed"], failed["failed"]), (1, 1))

    def test_cannot_select_card_that_was_not_returned(self):
        suite = {"schema": SCHEMA, "journeys": [{"id": "unseen", "steps": [
            {"constraints": {"query": "unknown"},
             "expect": {"code": "no_matches"}},
            {"target_card_id": "ja:SV2A:025/165:normal",
             "expect": {"code": "target_selected"}},
        ]}]}
        with self.assertRaisesRegex(ValueError, "not shown"):
            evaluate(self.db, suite)


if __name__ == "__main__":
    unittest.main()

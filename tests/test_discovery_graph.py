import sqlite3
import unittest

from pokemon_index import core, discovery_graph


class DiscoveryGraphTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.import_cards(self.db, [
            dict(language="ja", set_code="SV2a", collector_number="025/165",
                 variant="normal", name="ピカチュウ", provenance="fixture",
                 rights_reference="fixture", display_allowed=False),
            dict(language="ja", set_code="SV2a", collector_number="025/165",
                 variant="reverse_masterball", name="ピカチュウ", provenance="fixture",
                 rights_reference="fixture", display_allowed=False),
            dict(language="en", set_code="ME1", collector_number="025/165",
                 variant="normal", name="Pikachu", provenance="fixture",
                 rights_reference="fixture", display_allowed=False, match_eligible=False),
        ])
        self.ja = "ja:SV2A:025/165:normal"
        self.reverse = "ja:SV2A:025/165:reverse_masterball"
        self.en = "en:ME1:025/165:normal"

    def tearDown(self):
        self.db.close()

    def assertion(self, status, reviewer=None):
        row = dict(left_card_id=self.en, right_card_id=self.ja,
                   relation_type="localization_counterpart", review_status=status,
                   evidence_ref="fixture:card-pair-1", rights_reference="fixture",
                   asserted_by="curation-tool")
        if reviewer:
            row["reviewer"] = reviewer
        return row

    def test_relationship_is_reviewed_and_reversible_without_losing_history(self):
        self.assertEqual(discovery_graph.assert_relationships(self.db, [self.assertion("proposed")]), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, [self.assertion("proposed")]), 0)
        initial = discovery_graph.card_neighborhood(self.db, self.ja)
        self.assertEqual(initial["relationships"], [])
        self.assertEqual(initial["variants_at_number"][0]["card_id"], self.reverse)
        self.assertEqual(len(discovery_graph.card_neighborhood(self.db, self.ja, True)["relationships"]), 1)
        with self.assertRaisesRegex(ValueError, "require a reviewer"):
            discovery_graph.assert_relationships(self.db, [self.assertion("verified")])
        discovery_graph.assert_relationships(self.db, [self.assertion("verified", "reviewer-a")])
        edge = discovery_graph.card_neighborhood(self.db, self.ja)["relationships"][0]
        self.assertEqual(edge["other_card_id"], self.en)
        self.assertEqual(edge["review_status"], "verified")
        discovery_graph.assert_relationships(self.db, [self.assertion("rejected", "reviewer-b")])
        self.assertEqual(discovery_graph.card_neighborhood(self.db, self.ja, True)["relationships"], [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 3)

    def test_relationship_does_not_infer_localization_from_matching_numbers(self):
        with self.assertRaisesRegex(ValueError, "different languages"):
            discovery_graph.assert_relationships(self.db, [dict(
                self.assertion("proposed"), left_card_id=self.ja, right_card_id=self.reverse)])
        self.assertEqual(discovery_graph.card_neighborhood(self.db, self.en)["relationships"], [])

    def test_verified_counterpart_enables_cross_language_discovery(self):
        discovery_graph.save_exploration(self.db, dict(
            session_id="cross", owner_key="anonymous-1", expected_version=0,
            constraints={"query": "Pikachu", "language": "ja"}))
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "cross", "anonymous-1")["total"], 0)
        discovery_graph.assert_relationships(self.db, [self.assertion("proposed")])
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "cross", "anonymous-1")["total"], 0)
        discovery_graph.assert_relationships(self.db, [self.assertion("verified", "reviewer-a")])
        found = discovery_graph.exploration_candidates(self.db, "cross", "anonymous-1")
        self.assertEqual(found["cards"][0]["card_id"], self.ja)
        self.assertEqual(found["cards"][0]["matched_via"], "verified_localization_counterpart")
        discovery_graph.assert_relationships(self.db, [self.assertion("rejected", "reviewer-b")])
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "cross", "anonymous-1")["total"], 0)

    def test_structured_exploration_requires_exact_target_and_checks_revision(self):
        session = discovery_graph.save_exploration(self.db, dict(
            session_id="s1", owner_key="opaque-user-1", expected_version=0,
            constraints={"query": "Pikachu", "language": "ja", "budget_minor": 20000},
            shortlist_card_ids=[self.ja, self.reverse]))
        self.assertEqual(session["status"], "exploring")
        self.assertFalse(session["ready_for_offer_tracking"])
        self.assertIn("variant", session["next_clarifications"])
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "s1", "opaque-user-1")["total"], 0)
        selected = discovery_graph.save_exploration(self.db, dict(
            session_id="s1", owner_key="opaque-user-1", expected_version=1,
            constraints={"query": "ピカチュウ", "set_code": "sv2a",
                         "collector_number": "25/165", "variant": "normal"},
            target_card_id=self.ja))
        self.assertEqual(selected["status"], "targeted")
        self.assertEqual(selected["constraints"]["collector_number"], "025/165")
        self.assertTrue(selected["ready_for_offer_tracking"])
        candidates = discovery_graph.exploration_candidates(self.db, "s1", "opaque-user-1")
        self.assertEqual([card["card_id"] for card in candidates["cards"]], [self.ja])
        self.assertEqual(candidates["cards"][0]["display_allowed"], 0)
        with self.assertRaisesRegex(ValueError, "version conflict"):
            discovery_graph.save_exploration(self.db, dict(
                session_id="s1", owner_key="opaque-user-1", expected_version=1,
                target_card_id=self.en))
        with self.assertRaisesRegex(ValueError, "owner"):
            discovery_graph.get_exploration(self.db, "s1", "someone-else")
        discovery_graph.save_exploration(self.db, dict(
            session_id="s1", owner_key="opaque-user-1", expected_version=2,
            target_card_id=self.en))
        self.assertFalse(discovery_graph.get_exploration(
            self.db, "s1", "opaque-user-1")["ready_for_offer_tracking"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM exploration_revision").fetchone()[0], 3)


if __name__ == "__main__":
    unittest.main()

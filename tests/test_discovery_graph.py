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
        self.assertEqual((edge["asserted_by"], edge["reviewer"]),
                         ("curation-tool", "reviewer-a"))
        discovery_graph.assert_relationships(self.db, [self.assertion("rejected", "reviewer-b")])
        self.assertEqual(discovery_graph.card_neighborhood(self.db, self.ja, True)["relationships"], [])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 3)
        self.assertEqual(discovery_graph.assert_relationships(
            self.db, [self.assertion("verified", "reviewer-a")]), 1)
        self.assertEqual(discovery_graph.card_neighborhood(
            self.db, self.ja)["relationships"][0]["review_status"], "verified")
        self.assertEqual(discovery_graph.assert_relationships(
            self.db, [self.assertion("verified", "reviewer-a")]), 0)

    def test_explicit_assertion_id_is_retry_safe(self):
        row = dict(self.assertion("verified", "reviewer-a"), assertion_id="review-event-1")
        self.assertEqual(discovery_graph.assert_relationships(self.db, [row]), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, [row]), 0)
        with self.assertRaisesRegex(ValueError, "different event"):
            discovery_graph.assert_relationships(self.db, [dict(row, review_status="rejected")])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 1)

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
            constraints={"language": "en", "set_code": "ME1"},
            target_card_id=self.en))
        self.assertFalse(discovery_graph.get_exploration(
            self.db, "s1", "opaque-user-1")["ready_for_offer_tracking"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM exploration_revision").fetchone()[0], 3)

    def test_paused_target_stays_paused_and_conflicting_edit_is_rejected(self):
        discovery_graph.save_exploration(self.db, dict(
            session_id="paused", owner_key="user", expected_version=0,
            target_card_id=self.ja, constraints={"language": "ja"}))
        paused = discovery_graph.save_exploration(self.db, dict(
            session_id="paused", owner_key="user", expected_version=1,
            status="paused"))
        self.assertEqual(paused["status"], "paused")
        self.assertFalse(paused["ready_for_offer_tracking"])
        changed = discovery_graph.save_exploration(self.db, dict(
            session_id="paused", owner_key="user", expected_version=2,
            constraints={"budget_minor": 30000}))
        self.assertEqual(changed["status"], "paused")
        self.assertEqual(discovery_graph.exploration_decision(
            self.db, "paused", "user")["code"], "paused")
        with self.assertRaisesRegex(ValueError, "conflicts with language"):
            discovery_graph.save_exploration(self.db, dict(
                session_id="paused", owner_key="user", expected_version=3,
                constraints={"language": "en"}))
        self.assertEqual(discovery_graph.get_exploration(
            self.db, "paused", "user")["version"], 3)
        resumed = discovery_graph.save_exploration(self.db, dict(
            session_id="paused", owner_key="user", expected_version=3,
            status="targeted"))
        self.assertTrue(resumed["ready_for_offer_tracking"])
        with self.assertRaisesRegex(ValueError, "conflicts with variant"):
            discovery_graph.save_exploration(self.db, dict(
                session_id="paused", owner_key="user", expected_version=4,
                constraints={"variant": "reverse_masterball"}))

    def test_decision_uses_actual_candidate_ambiguity(self):
        discovery_graph.save_exploration(self.db, dict(
            session_id="ambiguous", owner_key="user", expected_version=0,
            constraints={"query": "ピカチュウ", "language": "ja", "set_code": "SV2A",
                         "collector_number": "025/165", "budget_minor": 20000}))
        decision = discovery_graph.exploration_decision(self.db, "ambiguous", "user")
        self.assertEqual((decision["code"], decision["candidate_count"]),
                         ("multiple_printings", 2))
        self.assertEqual(decision["next_question"]["field"], "variant")
        self.assertIn("budget_minor", decision["pending_market_filters"])
        discovery_graph.save_exploration(self.db, dict(
            session_id="ambiguous", owner_key="user", expected_version=1,
            constraints={"variant": "normal"}))
        self.assertEqual(discovery_graph.exploration_decision(
            self.db, "ambiguous", "user")["code"], "confirm_target")
        discovery_graph.save_exploration(self.db, dict(
            session_id="ambiguous", owner_key="user", expected_version=2,
            target_card_id=self.ja))
        self.assertEqual(discovery_graph.exploration_decision(
            self.db, "ambiguous", "user")["code"], "target_selected")
        discovery_graph.save_exploration(self.db, dict(
            session_id="missing", owner_key="user", expected_version=0,
            constraints={"query": "not-a-card"}))
        self.assertEqual(discovery_graph.exploration_decision(
            self.db, "missing", "user")["code"], "no_matches")
        discovery_graph.save_exploration(self.db, dict(
            session_id="unverified", owner_key="user", expected_version=0,
            constraints={"query": "Pikachu", "language": "en", "set_code": "ME1"}))
        self.assertEqual(discovery_graph.exploration_decision(
            self.db, "unverified", "user")["code"], "unverified_printing")


if __name__ == "__main__":
    unittest.main()

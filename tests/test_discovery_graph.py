import json
import sqlite3
import unittest
import uuid

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

    def assertion(self, status, reviewer=None, event_id=None):
        row = dict(left_card_id=self.en, right_card_id=self.ja,
                   relation_type="localization_counterpart", review_status=status,
                   evidence_ref="fixture:card-pair-1", rights_reference="fixture",
                   asserted_by="curation-tool")
        if reviewer:
            row["reviewer"] = reviewer
        if status == "verified":
            row["assertion_id"] = event_id or str(uuid.uuid4())
            row["evidence_ref"] = json.dumps({
                "schema": "pokemon.relationship_review.v1",
                "review_event_id": row["assertion_id"],
                "source_snapshot_sha256": "0" * 64,
                "cards": [
                    {"card_id": card_id, "source_ref": f"fixture:{card_id}",
                     "source_kind": "fixture", "identity_checked": True}
                    for card_id in (self.en, self.ja)
                ],
                "first_review": {"reviewer": "first-reviewer", "decision": "localization_counterpart",
                                 "reviewed_at": "2026-09-24T01:00:00Z"},
                "second_review": {"reviewer": reviewer or "second-reviewer",
                                  "decision": "localization_counterpart",
                                  "reviewed_at": "2026-09-24T02:00:00Z"},
                "artwork": {"outcome": "same", "note": "fixture comparison"},
                "finish": {"outcome": "same", "note": "fixture finish"},
                "rationale": "synthetic test relationship",
            }, sort_keys=True)
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
        restored = self.assertion("verified", "reviewer-a")
        self.assertEqual(discovery_graph.assert_relationships(
            self.db, [restored]), 1)
        self.assertEqual(discovery_graph.card_neighborhood(
            self.db, self.ja)["relationships"][0]["review_status"], "verified")
        self.assertEqual(discovery_graph.assert_relationships(
            self.db, [restored]), 0)

    def test_explicit_assertion_id_is_retry_safe(self):
        row = self.assertion("verified", "reviewer-a", event_id="review-event-1")
        self.assertEqual(discovery_graph.assert_relationships(self.db, [row]), 1)
        self.assertEqual(discovery_graph.assert_relationships(self.db, [row]), 0)
        with self.assertRaisesRegex(ValueError, "different event"):
            discovery_graph.assert_relationships(self.db, [dict(row, review_status="rejected")])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 1)

    def test_ai_artwork_proposal_is_discoverable_without_price_equivalence(self):
        row = dict(left_card_id=self.en, right_card_id=self.ja,
                   relation_type="same_artwork", review_status="proposed",
                   assertion_id="ai-artwork-fixture", evidence_ref="fixture:hashed-images",
                   rights_reference="internal-test", asserted_by="ai-artwork-review-v1",
                   reviewer="gemini-3.8-flash")
        discovery_graph.assert_relationships(self.db, [row])
        neighborhood = discovery_graph.card_neighborhood(self.db, self.ja)
        self.assertEqual(neighborhood["relationships"], [])
        self.assertEqual(len(neighborhood["ai_artwork_candidates"]), 1)
        self.assertFalse(neighborhood["ai_artwork_candidates"][0]["price_comparable"])

    def test_relationship_import_handles_legacy_column_order(self):
        self.db.execute("DROP TABLE card_relationship_assertion")
        self.db.execute("""CREATE TABLE card_relationship_assertion (
            assertion_id TEXT PRIMARY KEY, left_card_id TEXT NOT NULL,
            right_card_id TEXT NOT NULL, relation_type TEXT NOT NULL,
            review_status TEXT NOT NULL, evidence_ref TEXT NOT NULL,
            rights_reference TEXT NOT NULL, asserted_by TEXT NOT NULL,
            asserted_at TEXT NOT NULL, reviewer TEXT)""")
        row = self.assertion("proposed")
        row["assertion_id"] = "legacy-column-order-test"
        self.assertEqual(discovery_graph.assert_relationships(self.db, [row]), 1)
        saved = self.db.execute(
            "SELECT asserted_at, reviewer FROM card_relationship_assertion"
        ).fetchone()
        self.assertTrue(saved["asserted_at"])
        self.assertIsNone(saved["reviewer"])

    def test_direct_verified_import_requires_two_card_two_reviewer_evidence(self):
        row = self.assertion("verified", "reviewer-a")
        with self.assertRaisesRegex(ValueError, "structured evidence"):
            discovery_graph.assert_relationships(self.db, [dict(row, evidence_ref="checked")])
        evidence = json.loads(row["evidence_ref"])
        evidence["cards"][1]["card_id"] = "en:OTHER:001/001:normal"
        with self.assertRaisesRegex(ValueError, "endpoint cards"):
            discovery_graph.assert_relationships(
                self.db, [dict(row, evidence_ref=json.dumps(evidence))])
        evidence = json.loads(row["evidence_ref"])
        evidence["second_review"]["reviewer"] = "first-reviewer"
        with self.assertRaisesRegex(ValueError, "distinct reviewers"):
            discovery_graph.assert_relationships(
                self.db, [dict(row, evidence_ref=json.dumps(evidence))])
        evidence["second_review"]["reviewer"] = "first-reviewer "
        with self.assertRaisesRegex(ValueError, "distinct reviewers"):
            discovery_graph.assert_relationships(
                self.db, [dict(row, evidence_ref=json.dumps(evidence), reviewer="first-reviewer ")])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_relationship_assertion").fetchone()[0], 0)

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

    def test_verified_counterpart_respects_explicit_character_and_artist(self):
        core.import_card_facets(self.db, [
            dict(card_id=self.ja, facet_type="dex_id", value="25",
                 provenance="fixture", rights_reference="fixture"),
            dict(card_id=self.ja, facet_type="illustrator", value="Naoyo Kimura",
                 provenance="fixture", rights_reference="fixture"),
        ])
        discovery_graph.assert_relationships(self.db, [self.assertion("verified", "reviewer-a")])
        discovery_graph.save_exploration(self.db, dict(
            session_id="facet-filter", owner_key="owner", expected_version=0,
            constraints={"query": "Pikachu", "language": "ja", "dex_id": 999}))
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "facet-filter", "owner")["total"], 0)
        discovery_graph.save_exploration(self.db, dict(
            session_id="facet-filter", owner_key="owner", expected_version=1,
            constraints={"dex_id": None, "illustrator": "Wrong Artist"}))
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "facet-filter", "owner")["total"], 0)
        discovery_graph.save_exploration(self.db, dict(
            session_id="facet-filter", owner_key="owner", expected_version=2,
            constraints={"illustrator": "naoyo kimura"}))
        self.assertEqual(discovery_graph.exploration_candidates(
            self.db, "facet-filter", "owner")["cards"][0]["matched_via"],
                         "verified_localization_counterpart")

    def test_character_alias_is_discovery_only_and_artist_can_filter(self):
        core.import_cards(self.db, [
            dict(language="en", set_code="ME1", collector_number="026/165",
                 variant="normal", name="Pikachu & Zekrom", provenance="fixture",
                 rights_reference="fixture", display_allowed=False),
            dict(language="ja", set_code="SV2a", collector_number="026/165",
                 variant="normal", name="ゼクロム", provenance="fixture",
                 rights_reference="fixture", display_allowed=False),
        ])
        group = "en:ME1:026/165:normal"
        zekrom = "ja:SV2A:026/165:normal"
        core.import_card_facets(self.db, [
            dict(card_id=card_id, facet_type=kind, value=value,
                 provenance=f"fixture:{card_id}", rights_reference="fixture")
            for card_id in (self.ja, self.reverse, self.en)
            for kind, value in (("dex_id", "25"), ("illustrator", "Naoyo Kimura"))
        ])
        core.import_card_facets(self.db, [
            dict(card_id=card_id, facet_type="dex_id", value=value,
                 provenance="fixture:team", rights_reference="fixture")
            for card_id, value in ((group, "25"), (group, "644"), (zekrom, "644"))
        ])
        self.assertEqual(core.catalog_search_internal(self.db, "", dex_id=25)["total"], 4)
        self.assertEqual(core.catalog_status(self.db)["facet_coverage"],
                         {"dex_id": 5, "illustrator": 3})
        self.assertEqual(core.catalog_search_internal(
            self.db, "", illustrator="naoyo kimura", set_code="SV2a")["total"], 2)
        self.assertEqual(len(core.catalog_card_internal(
            self.db, self.ja)["discovery_facets"]), 2)
        discovery_graph.save_exploration(self.db, dict(
            session_id="alias", owner_key="user", expected_version=0,
            constraints={"query": "Pikachu", "language": "ja", "dex_id": 25}))
        # An English name finds Japanese character relatives, with or without
        # an explicit dex filter, without creating a counterpart edge.
        direct = discovery_graph.exploration_candidates(self.db, "alias", "user")
        self.assertEqual(direct["total"], 2)
        discovery_graph.save_exploration(self.db, dict(
            session_id="alias", owner_key="user", expected_version=1,
            constraints={"dex_id": None}))
        found = discovery_graph.exploration_candidates(self.db, "alias", "user")
        self.assertEqual(found["total"], 2)
        self.assertEqual({card["matched_via"] for card in found["cards"]}, {"same_character"})
        self.assertTrue(all(card["character_dex_id"] == 25 for card in found["cards"]))
        self.assertNotIn(zekrom, [card["card_id"] for card in found["cards"]])
        neighborhood = discovery_graph.card_neighborhood(self.db, self.ja)
        self.assertEqual(neighborhood["relationships"], [])
        self.assertGreaterEqual(neighborhood["metadata_neighbors"]["same_character"]["total"], 2)
        self.assertFalse(neighborhood["metadata_neighbors"]["same_illustrator"]["price_comparable"])
        self.assertEqual(neighborhood["metadata_neighbors"]["same_character"]["claim_status"],
                         "retrieval_only")

    def test_metadata_neighbor_counts_distinct_cards_across_case_variants(self):
        core.import_card_facets(self.db, [
            dict(card_id=card_id, facet_type="illustrator", value=value,
                 provenance="fixture", rights_reference="fixture")
            for card_id, value in ((self.ja, "Naoyo Kimura"), (self.ja, "naoyo kimura"),
                                   (self.en, "Naoyo Kimura"), (self.en, "naoyo kimura"))
        ])
        result = discovery_graph.card_neighborhood(self.db, self.ja)["metadata_neighbors"]["same_illustrator"]
        self.assertEqual(result["total"], 1)
        self.assertEqual([row["card_id"] for row in result["cards"]], [self.en])

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

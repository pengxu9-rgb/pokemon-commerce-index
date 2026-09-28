import json
import unittest

from pokemon_index import buyer_questions, core, discovery_graph


class BuyerQuestionPlanTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(":memory:")
        core.init_db(self.db)
        core.import_cards(self.db, [
            dict(language="ja", set_code="SV2a", collector_number="025/165",
                 variant="normal", name="ピカチュウ", provenance="fixture",
                 rights_reference="fixture"),
            dict(language="ja", set_code="SV2a", collector_number="025/165",
                 variant="reverse_masterball", name="ピカチュウ", provenance="fixture",
                 rights_reference="fixture"),
            dict(language="en", set_code="ME1", collector_number="025/165",
                 variant="normal", name="Pikachu", provenance="fixture",
                 rights_reference="fixture"),
        ])
        self.ja = "ja:SV2A:025/165:normal"
        self.en = "en:ME1:025/165:normal"

    def tearDown(self):
        self.db.close()

    def proposal(self):
        discovery_graph.assert_relationships(self.db, [dict(
            left_card_id=self.ja, right_card_id=self.en,
            relation_type="same_artwork", review_status="proposed",
            assertion_id="ai-fixture", evidence_ref="fixture:hashed-images",
            rights_reference="internal-only", asserted_by="ai-artwork-review-v1")])

    def verified_counterpart(self):
        event_id = "review-fixture"
        evidence = {
            "schema": "pokemon.relationship_review.v1", "review_event_id": event_id,
            "source_snapshot_sha256": "0" * 64,
            "cards": [{"card_id": card_id, "source_ref": f"fixture:{card_id}",
                       "source_kind": "fixture", "identity_checked": True}
                      for card_id in (self.ja, self.en)],
            "first_review": {"reviewer": "one", "decision": "localization_counterpart",
                             "reviewed_at": "2026-09-24T01:00:00Z"},
            "second_review": {"reviewer": "two", "decision": "localization_counterpart",
                              "reviewed_at": "2026-09-24T02:00:00Z"},
            "artwork": {"outcome": "same", "note": "fixture"},
            "finish": {"outcome": "different", "note": "fixture"},
            "rationale": "synthetic test relationship",
        }
        discovery_graph.assert_relationships(self.db, [dict(
            left_card_id=self.ja, right_card_id=self.en,
            relation_type="localization_counterpart", review_status="verified",
            assertion_id=event_id, evidence_ref=json.dumps(evidence),
            rights_reference="internal-only", asserted_by="test", reviewer="two")])

    def test_ai_artwork_is_only_a_lead_even_for_counterpart_question(self):
        self.proposal()
        for question in ("same_artwork", "english_or_japanese_counterpart"):
            result = buyer_questions.plan_card_question(self.db, question, self.ja, "en")
            self.assertEqual(result["status"], "relationship_review_needed")
            self.assertEqual(result["verified_links"], [])
            self.assertEqual(result["candidate_leads"][0]["review_status"], "proposed")
            self.assertFalse(result["price_comparable"])

    def test_verified_counterpart_is_evidence_bound_but_not_price_equivalence(self):
        self.proposal()
        self.verified_counterpart()
        result = buyer_questions.plan_card_question(
            self.db, "english_or_japanese_counterpart", self.ja, "en")
        self.assertEqual(result["status"], "verified_links_available")
        self.assertEqual(result["verified_links"][0]["assertion_id"], "review-fixture")
        self.assertEqual(result["candidate_leads"], [])
        self.assertFalse(result["price_comparable"])
        self.assertEqual(result["required_inputs"], [])
        unrelated_language = buyer_questions.plan_card_question(
            self.db, "same_artwork", self.ja, "ja")
        self.assertEqual(unrelated_language["verified_links"], [])

    def test_same_number_variants_are_structural_only(self):
        result = buyer_questions.plan_card_question(self.db, "printing_variants", self.ja)
        self.assertEqual(result["status"], "structural_variants_available")
        self.assertEqual(result["candidate_leads"][0]["relation_type"], "same_set_number")
        self.assertFalse(result["price_comparable"])

    def test_market_questions_require_market_evidence(self):
        for question in ("cross_region_price", "condition", "merchant_choice"):
            result = buyer_questions.plan_card_question(self.db, question, self.ja)
            self.assertEqual(result["status"], "market_evidence_needed")
            self.assertEqual(result["verified_links"], [])
            self.assertTrue(result["required_inputs"])
            self.assertFalse(result["price_comparable"])

    def test_missing_target_and_invalid_inputs(self):
        missing = buyer_questions.plan_card_question(self.db, "same_artwork")
        self.assertEqual(missing["status"], "need_exact_card")
        with self.assertRaisesRegex(ValueError, "unsupported buyer question"):
            buyer_questions.plan_card_question(self.db, "sell_through", self.ja)
        with self.assertRaisesRegex(ValueError, "unsupported target language"):
            buyer_questions.plan_card_question(self.db, "same_artwork", self.ja, "fr")
        with self.assertRaisesRegex(ValueError, "unknown card"):
            buyer_questions.plan_card_question(self.db, "same_artwork", "ja:UNKNOWN:1:normal")


if __name__ == "__main__":
    unittest.main()

import unittest

from pokemon_index.question_routing_v2 import (FOCUSES, OBJECT_TYPES,
                                                plan_question, validate_facts)


def facts(*, object_type="single_card", goal="price_comparison",
          context="prospective_buy", names=None, media="none", languages=None,
          merchant=None, destination=None):
    return {"object_type": object_type, "primary_goal": goal,
            "transaction_context": context,
            "identity_tokens": {"card_names": [] if names is None else names,
                                "set_name": None, "collector_number": None,
                                "language": None, "finish": None, "grade": None},
            "media_state": media, "language_mentions": [] if languages is None else languages,
            "merchant_ref": merchant, "destination": destination}


def unique():
    return {"status": "unique", "candidate_ids": ["card-1"],
            "evidence_ref": "catalog-snapshot-1"}


class QuestionRoutingV2Tests(unittest.TestCase):
    def actions(self, result):
        return [step["action"] for step in result["steps"]]

    def test_platform_rule_keeps_card_object_and_retrieves_policy(self):
        result = plan_question(facts(goal="marketplace_policy", context="completed_purchase"))
        self.assertEqual(result["scope_status"], "supported_card_object")
        self.assertEqual(self.actions(result), ["explain_general", "retrieve_current_policy"])
        self.assertEqual(result["steps"][1]["status"], "blocked")

    def test_generic_seller_signal_requests_merchant_identity(self):
        result = plan_question(facts(goal="merchant_reliability", context="none"))
        self.assertEqual(self.actions(result), ["explain_general", "ask_merchant_details"])
        self.assertNotIn("retrieve_seller_outcomes", self.actions(result))

    def test_model_tokens_cannot_assert_unique_printing(self):
        row = facts(names=["Munch Pikachu"])
        row["identity_tokens"]["collector_number"] = "288/SM-P"
        result = plan_question(row, capabilities={"internal_catalog"})
        self.assertEqual(self.actions(result), ["explain_general", "retrieve_catalog"])
        self.assertNotIn("retrieve_live_offers", self.actions(result))
        resolved = plan_question(row, resolution=unique())
        self.assertEqual(self.actions(resolved), ["explain_general", "retrieve_live_offers",
                                                 "retrieve_verified_sales"])

    def test_seller_payout_uses_copy_and_buyback_evidence(self):
        row = facts(goal="seller_pricing", context="seller_buyback", names=["Pikachu"])
        result = plan_question(row, resolution=unique())
        self.assertEqual(self.actions(result), ["explain_general", "ask_front_back_photos",
                                                "retrieve_buyback_quotes", "retrieve_verified_sales"])
        self.assertNotIn("retrieve_live_offers", self.actions(result))

    def test_unseen_photo_never_supports_grade_claim(self):
        result = plan_question(facts(goal="grading_decision", context="owned",
                                     media="referenced_not_collected"))
        self.assertEqual(self.actions(result), ["explain_general", "ask_front_back_photos"])
        self.assertIn("no_condition_or_grade_guarantee_from_text_or_photos",
                      result["claim_guards"])

    def test_overseas_unspecified_requires_release_evidence(self):
        result = plan_question(facts(goal="cross_language_relation", names=["Pikachu"],
                                     languages=["ja", "unspecified_foreign"]))
        self.assertEqual(self.actions(result), ["explain_catalog_coverage",
                                                "retrieve_official_release"])
        self.assertEqual(result["steps"][1]["status"], "blocked")

    def test_reviewed_relation_is_separate_from_unique_identity(self):
        result = plan_question(facts(goal="cross_language_relation", names=["Mew"],
                                     languages=["ja", "en"]), resolution=unique())
        self.assertEqual(self.actions(result), ["show_catalog_relation"])
        self.assertEqual(result["steps"][0]["status"], "blocked")

    def test_landed_quote_needs_destination_and_unique_identity(self):
        row = facts(goal="landed_cost", names=["Mew"], destination="HK")
        unresolved = plan_question(row)
        self.assertNotIn("retrieve_landed_quotes", self.actions(unresolved))
        resolved = plan_question(row, resolution=unique())
        self.assertIn("retrieve_landed_quotes", self.actions(resolved))

    def test_unsupported_object_precedes_market_evidence(self):
        result = plan_question(facts(object_type="sealed_tcg"), resolution=unique())
        self.assertEqual(self.actions(result), ["explain_scope"])

    def test_bad_resolution_and_unhashable_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "one catalog ID and evidence"):
            plan_question(facts(names=["Mew"]), resolution={
                "status": "unique", "candidate_ids": ["x"], "evidence_ref": None})
        bad = facts(languages=[{"not": "a language"}])
        with self.assertRaisesRegex(ValueError, "language mentions"):
            validate_facts(bad)

    def test_all_object_goal_pairs_return_an_action(self):
        for obj in OBJECT_TYPES:
            for goal in FOCUSES:
                with self.subTest(object_type=obj, primary_goal=goal):
                    self.assertTrue(plan_question(facts(object_type=obj, goal=goal))["steps"])


if __name__ == "__main__":
    unittest.main()

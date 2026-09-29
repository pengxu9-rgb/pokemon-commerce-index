import unittest

from pokemon_index.question_routing import FOCUSES, PRODUCT_SCOPES, plan_question


def facts(scope="tcg_single", focus="grading_decision", *, named=False,
          exact=False, copy=False, photos=False, language="unspecified"):
    return {"product_scope": scope, "focus": focus, "named_card": named,
            "exact_printing": exact, "specific_copy": copy,
            "photos_available": photos, "language_scope": language}


class QuestionRoutingTests(unittest.TestCase):
    def test_explain_then_ask_for_copy_photos(self):
        result = plan_question(facts(copy=True))
        self.assertEqual(result["answer_mode"], "explain_then_evidence")
        self.assertEqual([step["action"] for step in result["steps"]],
                         ["explain_general", "ask_front_back_photos"])
        self.assertEqual(result["steps"][1]["status"], "ready")

    def test_market_retrieval_requires_exact_printing_and_authorized_feed(self):
        ambiguous = plan_question(facts(focus="price_comparison", named=True))
        self.assertEqual([s["action"] for s in ambiguous["steps"]],
                         ["explain_general", "ask_printing_details"])
        self.assertNotIn("retrieve_live_offers", [s["action"] for s in ambiguous["steps"]])
        exact = plan_question(facts(focus="price_comparison", named=True, exact=True),
                              capabilities={"authorized_live_offers"})
        self.assertEqual([s["status"] for s in exact["steps"]],
                         ["ready", "ready", "blocked"])
        self.assertEqual(exact["steps"][2]["requires_capability"], "verified_sales")

    def test_non_tcg_is_gated_before_photo_review(self):
        result = plan_question(facts("non_tcg_card", "authenticity", copy=True))
        self.assertEqual(result["scope_status"], "unsupported_product")
        self.assertEqual([s["action"] for s in result["steps"]], ["explain_scope"])

    def test_other_language_relation_requires_external_release_source(self):
        result = plan_question(facts(focus="cross_language_relation", language="other"),
                               capabilities={"internal_catalog"})
        self.assertEqual(result["scope_status"], "limited_catalog_scope")
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["explain_catalog_coverage", "retrieve_official_release"])
        self.assertEqual(result["steps"][1]["status"], "blocked")

    def test_marketplace_policy_is_separate_from_card_identity(self):
        result = plan_question(facts("marketplace_process", "marketplace_policy"))
        self.assertEqual(result["answer_mode"], "explain_then_evidence")
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["explain_general", "retrieve_current_policy"])
        self.assertEqual(result["steps"][1]["status"], "blocked")

    def test_store_acceptance_needs_current_buyback_terms(self):
        result = plan_question(facts("marketplace_process", "channel_choice"))
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["explain_general", "retrieve_buyback_terms"])
        self.assertEqual(result["steps"][1]["status"], "blocked")

    def test_seller_value_uses_buyback_quotes_not_buyer_asks(self):
        result = plan_question(facts(focus="seller_pricing", named=True, exact=True,
                                     copy=True, language="ja_en"))
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["ask_front_back_photos", "retrieve_buyback_quotes",
                          "retrieve_verified_sales"])
        self.assertNotIn("retrieve_live_offers", [s["action"] for s in result["steps"]])
        self.assertEqual(result["steps"][1]["status"], "waiting_for_user")
        self.assertFalse(result["steps"][1]["capability_ready"])

    def test_catalog_waits_for_card_details(self):
        result = plan_question(facts(focus="identify_variant"),
                               capabilities={"internal_catalog"})
        self.assertEqual([s["status"] for s in result["steps"]],
                         ["ready", "waiting_for_user"])

    def test_general_raw_vs_graded_question_explains_then_clarifies(self):
        result = plan_question(facts(focus="price_comparison"))
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["explain_general", "ask_card_details"])
        self.assertEqual(result["answer_mode"], "explain_then_evidence")

    def test_invalid_identity_cannot_route(self):
        with self.assertRaisesRegex(ValueError, "exact printing"):
            plan_question(facts(exact=True))

    def test_every_supported_fact_pair_has_an_action(self):
        for scope in PRODUCT_SCOPES:
            for focus in FOCUSES:
                with self.subTest(scope=scope, focus=focus):
                    self.assertTrue(plan_question(facts(scope, focus))["steps"])

    def test_card_specific_policy_requires_current_policy(self):
        result = plan_question(facts(focus="marketplace_policy", named=True))
        self.assertEqual([step["action"] for step in result["steps"]],
                         ["explain_general", "retrieve_current_policy"])
        self.assertEqual(result["steps"][1]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

import unittest

from pokemon_index import question_routing_v4 as routing


def facts(*, goal="price_trend", object_type="single_card", window=None,
          constraints=None, names=None, set_name="Base Set", number="058/102"):
    return {"object_type": object_type, "primary_goal": goal,
            "transaction_context": "prospective_buy", "seller_channel": "none",
            "identity_tokens": {"card_names": ["Pikachu"] if names is None else names,
                                "set_name": set_name, "collector_number": number,
                                "language": "en", "rarity": None, "finish": None,
                                "grade": None},
            "media_state": "none", "language_mentions": ["en"],
            "platform_refs": [], "merchant_ref": None, "destination": None,
            "time_window": window, "purchase_constraints": constraints}


UNIQUE = {"status": "unique", "candidate_ids": ["en:BASE1:058/102:normal"],
          "evidence_ref": "catalog-proof"}


class QuestionRoutingV4Tests(unittest.TestCase):
    def actions(self, plan):
        return [step["action"] for step in plan["steps"]]

    def test_trend_asks_for_catalog_and_time_window_without_market_data(self):
        plan = routing.plan_question(facts())
        self.assertEqual(self.actions(plan), ["explain_market_context", "retrieve_catalog",
                                              "ask_time_window"])
        self.assertEqual(plan["steps"][1]["status"], "blocked")
        self.assertEqual(plan["claim_status"], "general_explanation_only")
        self.assertNotIn("retrieve_live_offers", self.actions(plan))

    def test_resolved_trend_keeps_asks_sales_and_coverage_separate(self):
        plan = routing.plan_question(facts(window="since January"), resolution=UNIQUE)
        self.assertEqual(self.actions(plan), ["explain_market_context",
            "retrieve_historical_asks", "retrieve_verified_sale_series",
            "validate_series_coverage"])
        self.assertEqual([step["status"] for step in plan["steps"]],
                         ["ready", "blocked", "blocked", "blocked"])
        self.assertEqual(plan["claim_status"], "retrieval_and_quality_review_required")
        self.assertIn("no_guaranteed_future_price_prediction", plan["claim_guards"])
        ready = routing.plan_question(facts(window="since January"), resolution=UNIQUE,
            capabilities={"authorized_ask_history", "verified_sale_series",
                          "validated_series_coverage"})
        self.assertTrue(all(step["status"] == "ready" for step in ready["steps"]))
        self.assertEqual(ready["claim_status"], "retrieval_and_quality_review_required")

    def test_buy_or_wait_needs_fresh_offer_and_buyer_preferences(self):
        plan = routing.plan_question(facts(goal="purchase_timing"), resolution=UNIQUE)
        self.assertIn("retrieve_live_offers", self.actions(plan))
        self.assertIn("ask_decision_horizon", self.actions(plan))
        self.assertIn("ask_purchase_constraints", self.actions(plan))
        self.assertFalse(any(action.startswith("recommend_") for action in self.actions(plan)))
        complete = routing.plan_question(facts(goal="purchase_timing", window="six months",
                                              constraints="under $500, PSA 9"), resolution=UNIQUE)
        self.assertNotIn("ask_decision_horizon", self.actions(complete))
        self.assertNotIn("ask_purchase_constraints", self.actions(complete))

    def test_ambiguous_printing_cannot_trigger_price_series(self):
        multiple = {"status": "multiple_candidates", "candidate_ids": ["card:1", "card:2"],
                    "evidence_ref": "catalog-proof"}
        plan = routing.plan_question(facts(goal="purchase_timing"), resolution=multiple)
        self.assertIn("ask_printing_details", self.actions(plan))
        self.assertNotIn("retrieve_historical_asks", self.actions(plan))
        self.assertNotIn("retrieve_live_offers", self.actions(plan))

    def test_market_segment_and_sealed_scope_are_not_exact_card_trends(self):
        broad = routing.plan_question(facts(object_type="card_market_segment", names=[]))
        self.assertIn("ask_market_scope", self.actions(broad))
        self.assertNotIn("retrieve_historical_asks", self.actions(broad))
        sealed = routing.plan_question(facts(object_type="sealed_tcg", names=[]))
        self.assertEqual(sealed["scope_status"], "unsupported_product")
        self.assertNotIn("retrieve_historical_asks", self.actions(sealed))

    def test_v3_goals_stay_available_without_changing_frozen_code(self):
        previous = routing.plan_question(facts(goal="price_comparison"), resolution=UNIQUE)
        self.assertIn("retrieve_live_offers", self.actions(previous))
        self.assertIn("retrieve_verified_sales", self.actions(previous))
        self.assertEqual(previous["schema"], "pokemon.question-route-plan.v4")

    def test_v4_fields_must_be_explicit_and_short(self):
        invalid = facts()
        del invalid["time_window"]
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            routing.validate_facts(invalid)
        with self.assertRaisesRegex(ValueError, "invalid time_window"):
            routing.validate_facts(facts(window=" "))


if __name__ == "__main__":
    unittest.main()

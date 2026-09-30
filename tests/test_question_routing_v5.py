import unittest

from pokemon_index import question_routing_v5 as routing


def facts(goal="seller_timing", *, names=None, object_type="single_card",
          transaction="owned", channel="marketplace_listing", window=None,
          purchase=None, sale=None, media="none"):
    return {"object_type": object_type, "primary_goal": goal,
            "transaction_context": transaction, "seller_channel": channel,
            "identity_tokens": {"card_names": ["Pikachu"] if names is None else names,
                                "set_name": "Base Set", "collector_number": "058/102",
                                "language": "en", "rarity": None, "finish": None,
                                "grade": None},
            "media_state": media, "language_mentions": ["en"],
            "platform_refs": [], "merchant_ref": None, "destination": None,
            "time_window": window, "purchase_constraints": purchase,
            "sale_constraints": sale}


UNIQUE = {"status": "unique", "candidate_ids": ["en:BASE1:058/102:normal"],
          "evidence_ref": "catalog-proof"}


class QuestionRoutingV5Tests(unittest.TestCase):
    def actions(self, plan):
        return [step["action"] for step in plan["steps"]]

    def test_seller_timing_uses_seller_evidence_and_constraints(self):
        plan = routing.plan_question(facts(), resolution=UNIQUE)
        actions = self.actions(plan)
        for action in ("retrieve_verified_sale_series", "retrieve_live_offers",
                       "retrieve_selling_fees", "ask_sale_horizon",
                       "ask_sale_constraints", "ask_front_back_photos"):
            self.assertIn(action, actions)
        self.assertNotIn("ask_purchase_constraints", actions)
        self.assertNotIn("retrieve_buyback_quotes", actions)
        self.assertEqual(plan["claim_status"], "retrieval_and_quality_review_required")
        self.assertTrue(all(step["status"] == "blocked" for step in plan["steps"]
                            if step["requires_capability"] in {"verified_sale_series",
                                                              "authorized_live_offers",
                                                              "current_selling_fees"}))

    def test_seller_buyback_is_separate(self):
        plan = routing.plan_question(facts(channel="comparing_channels", window="by October",
                                          sale="need cash soon"), resolution=UNIQUE)
        self.assertIn("retrieve_buyback_quotes", self.actions(plan))
        self.assertNotIn("ask_sale_horizon", self.actions(plan))
        self.assertNotIn("ask_sale_constraints", self.actions(plan))

    def test_seller_timing_with_no_owner_evidence_does_not_retrieve_market_series(self):
        plan = routing.plan_question(facts(transaction="none", channel="none"),
                                     resolution=UNIQUE)
        self.assertIn("ask_sale_state", self.actions(plan))
        self.assertNotIn("retrieve_verified_sale_series", self.actions(plan))
        self.assertNotIn("retrieve_live_offers", self.actions(plan))

    def test_relative_value_segment_does_not_invent_exact_printing(self):
        plan = routing.plan_question(facts("relative_value_explanation", names=[],
                                          object_type="card_market_segment",
                                          transaction="none", channel="none"))
        self.assertIn("ask_comparable_cohort", self.actions(plan))
        self.assertIn("ask_comparison_period", self.actions(plan))
        self.assertNotIn("retrieve_verified_sale_series", self.actions(plan))
        self.assertEqual(plan["claim_status"], "general_explanation_only")

    def test_relative_value_single_card_needs_reviewed_counterpart(self):
        plan = routing.plan_question(facts("relative_value_explanation",
                                          transaction="none", channel="none"),
                                     resolution=UNIQUE)
        self.assertIn("retrieve_reviewed_counterpart", self.actions(plan))
        self.assertIn("validate_series_coverage", self.actions(plan))
        self.assertEqual(next(s for s in plan["steps"] if
                              s["action"] == "retrieve_reviewed_counterpart")["status"],
                         "blocked")

    def test_card_selection_with_unavailable_photos_asks_for_choices(self):
        plan = routing.plan_question(facts("collecting_preference", names=[],
                                          transaction="prospective_buy", channel="none",
                                          purchase="about $1,300", window="five years",
                                          media="referenced_not_collected"))
        self.assertIn("ask_candidate_cards_or_preferences", self.actions(plan))
        self.assertIn("ask_listed_choices", self.actions(plan))
        self.assertNotIn("retrieve_live_offers", self.actions(plan))
        self.assertEqual(plan["claim_status"], "general_explanation_only")

    def test_named_card_options_retrieve_catalog_candidates(self):
        plan = routing.plan_question(facts("collecting_preference",
                                          names=["Pikachu", "Charizard"],
                                          transaction="prospective_buy", channel="none"))
        self.assertIn("retrieve_catalog_candidates", self.actions(plan))
        self.assertIn("retrieve_reviewed_relations", self.actions(plan))
        self.assertIn("ask_budget_and_condition", self.actions(plan))

    def test_vague_future_reference_requires_concrete_horizon(self):
        plan = routing.plan_question(facts("price_trend", window="今後",
                                          transaction="prospective_buy", channel="none"),
                                     resolution=UNIQUE)
        self.assertIn("ask_time_window", self.actions(plan))

    def test_old_goal_and_facts_remain_available(self):
        plan = routing.plan_question(facts("price_comparison",
                                          transaction="prospective_buy", channel="none"),
                                     resolution=UNIQUE)
        self.assertIn("retrieve_live_offers", self.actions(plan))
        self.assertEqual(plan["schema"], "pokemon.question-route-plan.v5")
        invalid = facts()
        del invalid["sale_constraints"]
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            routing.validate_facts(invalid)


if __name__ == "__main__":
    unittest.main()

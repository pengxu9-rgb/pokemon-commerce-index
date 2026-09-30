import unittest
import sqlite3

from pokemon_index import question_routing_v6 as routing, core
from tests.test_question_routing_v5 import facts as old_facts, UNIQUE


def facts(goal="seller_saleability", *, scope="recent normal Pokémon cards", formats=None,
          channel="none", **kwargs):
    result = old_facts(goal, object_type="card_market_segment", names=[],
                       transaction="none", channel=channel, **kwargs)
    return {**result, "sale_scope": scope,
            "sale_formats": ["single", "evolution_line"] if formats is None else formats}


COHORT = {"unit_ids": ["ja:SV4A:347/190:holo|RAW|raw|a"],
          "evidence_ref": "catalog-unit-cohort-sha256:" + "a" * 64}


class QuestionRoutingV6Tests(unittest.TestCase):
    def test_broad_saleability_retrieves_candidates_before_market_evidence(self):
        plan = routing.plan_question(facts(), capabilities={"internal_catalog", "authorized_live_offers"})
        actions = {s["action"]: s for s in plan["steps"]}
        self.assertIn("retrieve_sale_candidates", actions)
        self.assertIn("review_sale_cohort", actions)
        self.assertNotIn("retrieve_live_offers", actions)
        self.assertNotIn("retrieve_verified_sale_series", actions)
        self.assertNotIn("ask_sale_scope", actions)
        self.assertNotIn("ask_sale_format", actions)
        self.assertEqual(plan["claim_status"], "general_explanation_only")

    def test_reviewed_cohort_still_needs_sales_costs_and_relations(self):
        plan = routing.plan_question(facts(channel="comparing_channels", window="last 30 days"),
                                     sale_cohort=COHORT)
        actions = {s["action"]: s for s in plan["steps"]}
        for action in ("retrieve_live_offers", "retrieve_verified_sale_series", "validate_series_coverage",
                       "retrieve_selling_fees", "retrieve_shipping_costs", "retrieve_buyback_quotes",
                       "retrieve_reviewed_relations"):
            self.assertEqual(actions[action]["status"], "blocked")
        self.assertNotIn("ask_analysis_period", actions)
        self.assertIn("no_bulk_or_bundle_price_from_summing_single_card_asks", plan["claim_guards"])

    def test_missing_scope_and_format_are_clarified(self):
        plan = routing.plan_question(facts(scope=None, formats=[]))
        actions = {s["action"] for s in plan["steps"]}
        self.assertIn("ask_sale_scope", actions)
        self.assertIn("ask_sale_format", actions)
        self.assertNotIn("retrieve_sale_candidates", actions)

    def test_card_ids_and_unknown_copy_conditions_cannot_form_price_cohort(self):
        for units in (["ja:SV4A:347/190:holo"],
                      ["ja:SV4A:347/190:holo|RAW|raw|unknown"],
                      ["ja:SV4A:347/190:holo|PSA|fake|graded"],
                      COHORT["unit_ids"] * 2):
            with self.assertRaises(ValueError):
                routing.plan_question(facts(), sale_cohort={**COHORT, "unit_ids": units})

    def test_unrelated_v5_goals_keep_existing_routes(self):
        previous = old_facts("price_comparison", transaction="prospective_buy", channel="none")
        plan = routing.plan_question({**previous, "sale_scope": None, "sale_formats": []},
                                     resolution=UNIQUE)
        self.assertIn("retrieve_live_offers", [s["action"] for s in plan["steps"]])
        self.assertEqual(plan["schema"], "pokemon.question-route-plan.v6")

    def test_cohort_builder_checks_units_and_changes_evidence_when_source_changes(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        try:
            core.init_db(db)
            seed = {"match_eligible": True, "language": "ja", "set_code": "SV4A", "collector_number": "347/190",
                    "variant": "holo", "name": "ミュウex", "rarity": "SAR",
                    "provenance": "fixture", "rights_reference": "fixture"}
            core.import_cards(db, [seed])
            unit_id = core._unit(db, "ja:SV4A:347/190:holo", "RAW", "raw", "a")
            cohort = routing.build_sale_cohort(db, [unit_id])
            self.assertEqual(cohort["unit_ids"], [unit_id])
            db.execute("UPDATE card SET rarity='SR'")
            self.assertNotEqual(cohort, routing.build_sale_cohort(db, [unit_id]))
            db.execute("UPDATE card SET match_eligible=0")
            with self.assertRaisesRegex(ValueError, "match-ineligible"):
                routing.build_sale_cohort(db, [unit_id])
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

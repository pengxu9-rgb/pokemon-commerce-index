import sqlite3
import unittest

from pokemon_index import catalog_question_resolver, core, question_routing_v3


def facts(**tokens):
    identity = {"card_names": ["Pikachu"], "set_name": "Starter Set",
                "collector_number": "001/100", "language": "en", "rarity": None,
                "finish": None, "grade": None}
    identity.update(tokens)
    return {"object_type": "single_card", "primary_goal": "price_comparison",
            "transaction_context": "prospective_buy", "seller_channel": "none",
            "identity_tokens": identity, "media_state": "none",
            "language_mentions": [], "platform_refs": [],
            "merchant_ref": None, "destination": None}


class CatalogQuestionResolverTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.db.execute("""INSERT INTO catalog_set_localized VALUES
                        ('en','ABC','Starter Set',NULL,100,'fixture','test',0)""")
        self.add_card("en:ABC:001/100:normal")

    def tearDown(self):
        self.db.close()

    def add_card(self, card_id, *, variant="normal", eligible=1, rarity="Common"):
        self.db.execute("""INSERT INTO card
            (card_id,language,set_code,collector_number,variant,name,rarity,
             provenance,rights_reference,display_allowed,match_eligible)
             VALUES (?,'en','ABC','001/100',?,'Pikachu',?,'fixture','test',0,?)""",
                        (card_id, variant, rarity, eligible))

    def test_exact_catalog_coordinates_unlock_only_the_identity_gate(self):
        lookup = catalog_question_resolver.resolve_question(self.db, facts())
        self.assertEqual(lookup["resolution"]["status"], "unique")
        self.assertEqual(lookup["resolution"]["candidate_ids"],
                         ["en:ABC:001/100:normal"])
        self.assertTrue(lookup["resolution"]["evidence_ref"].startswith(
            "catalog-query-sha256:"))
        plan = question_routing_v3.plan_question(facts(), resolution=lookup["resolution"])
        offer_step = next(step for step in plan["steps"] if step["action"] == "retrieve_live_offers")
        self.assertEqual(offer_step["status"], "blocked")

    def test_name_only_single_row_is_not_promoted_to_exact_printing(self):
        incomplete = facts(set_name=None, collector_number=None, language=None)
        lookup = catalog_question_resolver.resolve_question(self.db, incomplete)
        self.assertEqual(lookup["resolution"]["status"], "not_attempted")
        self.assertEqual(lookup["reason"], "insufficient_printing_coordinates")
        plan = catalog_question_resolver.plan_question_with_catalog(self.db, incomplete)
        self.assertIn("ask_printing_details", [step["action"] for step in plan["steps"]])
        self.assertNotIn("retrieve_catalog", [step["action"] for step in plan["steps"]])
        self.assertNotIn("retrieve_live_offers", [step["action"] for step in plan["steps"]])

    def test_second_finish_blocks_unique_even_with_exact_set_and_number(self):
        self.add_card("en:ABC:001/100:holo", variant="holo")
        lookup = catalog_question_resolver.resolve_question(self.db, facts())
        self.assertEqual(lookup["resolution"]["status"], "multiple_candidates")
        self.assertEqual(len(lookup["resolution"]["candidate_ids"]), 2)
        self.assertIn("ask_printing_details", [step["action"] for step in
                      question_routing_v3.plan_question(
                          facts(), resolution=lookup["resolution"])["steps"]])
        holo = catalog_question_resolver.resolve_question(self.db, facts(finish="holo"))
        self.assertEqual(holo["resolution"]["candidate_ids"], ["en:ABC:001/100:holo"])

    def test_broad_finish_keeps_edition_subvariants(self):
        self.add_card("en:ABC:001/100:normal_1st_edition", variant="normal_1st_edition")
        lookup = catalog_question_resolver.resolve_question(self.db, facts(finish="normal"))
        self.assertEqual(lookup["resolution"]["status"], "multiple_candidates")
        self.assertEqual(lookup["matched_total"], 2)

    def test_unverified_or_ineligible_metadata_cannot_unlock_price(self):
        self.db.execute("UPDATE card SET rarity=NULL WHERE card_id='en:ABC:001/100:normal'")
        self.assertEqual(catalog_question_resolver.resolve_question(
            self.db, facts(rarity="Common"))["resolution"]["status"], "not_attempted")
        self.db.execute("UPDATE card SET match_eligible=0 WHERE card_id='en:ABC:001/100:normal'")
        self.assertEqual(catalog_question_resolver.resolve_question(
            self.db, facts())["resolution"]["status"], "not_attempted")

    def test_catalog_miss_is_distinct_from_incomplete_identity(self):
        lookup = catalog_question_resolver.resolve_question(
            self.db, facts(collector_number="999/100"))
        self.assertEqual(lookup["resolution"]["status"], "no_match")
        self.assertEqual(lookup["matched_total"], 0)
        self.assertTrue(lookup["resolution"]["evidence_ref"])


if __name__ == "__main__":
    unittest.main()

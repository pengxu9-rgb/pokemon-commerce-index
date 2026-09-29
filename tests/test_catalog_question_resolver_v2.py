import sqlite3
import unittest

from pokemon_index import catalog_question_resolver_v2, core


def facts(*, name="Lillie", number="397/SM-P", set_name="Promo"):
    return {"object_type": "single_card", "primary_goal": "price_comparison",
            "transaction_context": "prospective_buy", "seller_channel": "none",
            "identity_tokens": {"card_names": [name], "set_name": set_name,
                                "collector_number": number, "language": "ja",
                                "rarity": None, "finish": None, "grade": None},
            "media_state": "none", "language_mentions": ["ja"],
            "platform_refs": [], "merchant_ref": None, "destination": None}


class CatalogQuestionResolverV2Tests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.db.execute("""INSERT INTO catalog_set_localized VALUES
                        ('ja','SMP','Promo',NULL,100,'fixture','test',0)""")
        self.db.execute("""INSERT INTO card
            (card_id,language,set_code,collector_number,variant,name,rarity,
             provenance,rights_reference,display_allowed,match_eligible)
            VALUES ('ja:SMP:397/SM-P:normal','ja','SMP','397/SM-P','normal',
                    'リーリエ','Promo','fixture','test',0,1)""")
        self.db.execute("""INSERT INTO card_classification VALUES
                        ('ja:SMP:397/SM-P:normal','Trainer','Supporter','fixture','test')""")
        self.alias("lillie", "Lillie", "リーリエ")

    def tearDown(self):
        self.db.close()

    def alias(self, concept_id, english, japanese, *, revision=1, status="approved"):
        self.db.execute("""INSERT INTO bilingual_concept_revision
            (concept_id,revision,category,name_ja,name_en,source_ja,source_en,
             rights_reference,reviewer,reviewed_at,status)
            VALUES (?,?, 'Trainer', ?, ?, 'fixture-ja','fixture-en',
                    'test','reviewer','2026-09-29T00:00:00Z',?)""",
            (concept_id, revision, japanese, english, status))

    def test_reviewed_name_alias_can_resolve_only_with_exact_printing_coordinates(self):
        lookup = catalog_question_resolver_v2.resolve_question(self.db, facts())
        self.assertEqual(lookup["resolution"]["status"], "unique")
        self.assertEqual(lookup["resolution"]["candidate_ids"],
                         ["ja:SMP:397/SM-P:normal"])
        self.assertTrue(lookup["resolution"]["evidence_ref"].startswith(
            "reviewed-name-alias-sha256:"))
        plan = catalog_question_resolver_v2.plan_question_with_catalog(self.db, facts())
        offer = next(step for step in plan["steps"] if step["action"] == "retrieve_live_offers")
        self.assertEqual(offer["status"], "blocked")
        incomplete = catalog_question_resolver_v2.resolve_question(
            self.db, facts(number=None))
        self.assertEqual(incomplete["resolution"]["status"], "not_attempted")

    def test_ineligible_translation_target_stays_unresolved(self):
        self.db.execute("UPDATE card SET match_eligible=0")
        lookup = catalog_question_resolver_v2.resolve_question(self.db, facts())
        self.assertEqual(lookup["resolution"]["status"], "not_attempted")
        self.assertEqual(lookup["reason"], "translated_name_catalog_row_ineligible")

    def test_name_concept_cannot_cross_an_unverified_card_category(self):
        self.db.execute("DELETE FROM card_classification")
        lookup = catalog_question_resolver_v2.resolve_question(self.db, facts())
        self.assertEqual(lookup["resolution"]["status"], "not_attempted")
        self.assertEqual(lookup["reason"], "translated_name_category_unverified")

    def test_missing_or_disputed_translation_is_not_a_catalog_miss(self):
        missing = catalog_question_resolver_v2.resolve_question(
            self.db, facts(name="Unknown English Name"))
        self.assertEqual(missing["resolution"]["status"], "not_attempted")
        self.assertEqual(missing["reason"], "unresolved_cross_language_name")
        self.alias("lillie_alt", "Lillie", "別名")
        disputed = catalog_question_resolver_v2.resolve_question(self.db, facts())
        self.assertEqual(disputed["resolution"]["status"], "not_attempted")
        self.assertEqual(disputed["reason"], "ambiguous_reviewed_translation")

    def test_withdrawn_latest_revision_cannot_be_used(self):
        self.alias("lillie", "Lillie", "リーリエ", revision=2, status="withdrawn")
        lookup = catalog_question_resolver_v2.resolve_question(self.db, facts())
        self.assertEqual(lookup["reason"], "unresolved_cross_language_name")


if __name__ == "__main__":
    unittest.main()

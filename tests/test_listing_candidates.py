import sqlite3
import unittest

from pokemon_index import core, listing_candidates


class ListingCandidateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.import_cards(self.db, [
            {"language": "ja", "set_code": "S6a", "collector_number": "095/069",
             "variant": "unverified_hr_sa", "name": "ブラッキーVMAX", "provenance": "fixture",
             "rights_reference": "fixture", "match_eligible": False},
            {"language": "ja", "set_code": "M2a", "collector_number": "223/193",
             "variant": "holo", "name": "メガリザードンXex", "provenance": "fixture",
             "rights_reference": "fixture", "match_eligible": True},
            {"language": "ja", "set_code": "M2", "collector_number": "116/080",
             "variant": "holo", "name": "メガリザードンXex", "provenance": "fixture",
             "rights_reference": "fixture", "match_eligible": True},
        ])

    def tearDown(self):
        self.db.close()

    def test_match_disabled_card_is_retrievable_but_not_resolved(self):
        title = "ブラッキーVMAX HR S6a 095/069"
        result = listing_candidates.retrieve(self.db, title)
        self.assertEqual(result["status"], "candidate_only")
        self.assertEqual(result["candidates"][0]["card_id"],
                         "ja:S6A:095/069:unverified_hr_sa")
        self.assertFalse(result["candidates"][0]["match_eligible"])
        self.assertIsNone(core.resolve(self.db, {"title": title})[0])

    def test_artwork_shorthand_and_name_conflict_stay_candidate_only(self):
        shorthand = listing_candidates.retrieve(
            self.db, "メガリザードン X ex MA 223/193")
        self.assertEqual(shorthand["candidates"][0]["card_id"],
                         "ja:M2A:223/193:holo")
        self.assertEqual(shorthand["candidates"][0]["retrieval_signal"], "number_name")
        conflicting = listing_candidates.retrieve(
            self.db, "メガリザードンex M2 116/080")
        self.assertEqual(conflicting["candidates"][0]["retrieval_signal"],
                         "set_number_name_conflict")
        self.assertIsNone(core.resolve(self.db, {"title": "メガリザードンex M2 116/080"})[0])

    def test_set_name_without_number_and_bundle_abstention(self):
        result = listing_candidates.retrieve(self.db, "ブラッキーVMAX S6a")
        self.assertEqual(result["candidates"][0]["retrieval_signal"], "set_name")
        self.assertEqual(listing_candidates.retrieve(
            self.db, "ブラッキーVMAX S6a 095/069 2枚セット")["status"], "excluded_bundle")


if __name__ == "__main__":
    unittest.main()

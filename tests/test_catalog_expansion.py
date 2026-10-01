import sqlite3
import unittest

from pokemon_index import core, tcgdex_source
from scripts.expand_english_catalog import classify


class CatalogExpansionTests(unittest.TestCase):
    def test_card_name_after_attack_name_and_comment(self):
        source = '''const card: Card = {
          // name: { en: "comment name" }
          attacks: [{name: {en: "Slam"}, damage: "20"}],
          name: {en: "Snivy"}, rarity: "None", variants: [{type: "holo"}]
        };'''
        row = tcgdex_source.parse_card_source(source, set_id="2011bw", official_count=12,
            path="data/McDonald's Collection/2011bw/1.ts", revision="a" * 40, language="en")[0]
        self.assertEqual(row["name"], "Snivy")

    def test_missing_card_name_never_uses_attack_name(self):
        source = '''const card = {attacks: [{name: {en: "Slam"}}], variants: [{type: "holo"}]};'''
        with self.assertRaisesRegex(ValueError, "lacks en name"):
            tcgdex_source.parse_card_source(source, set_id="TEST", official_count=12,
                path="data/Base/TEST/1.ts", revision="a" * 40, language="en")

    def test_expansion_holds_conflicts_preserves_baseline_and_disables_matches(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        core.init_db(db)
        seed = dict(language="en", set_code="TEST", collector_number="001/012", name="Snivy",
            variant="unverified_api_family", provenance="fixture", rights_reference="fixture",
            match_eligible=False, display_allowed=False)
        core.import_cards(db, [seed])
        try:
            baseline = db.execute("SELECT * FROM card").fetchall()
            rows, holds, skipped = classify([seed, {**seed, "name": "Slam", "variant": "holo"},
                {**seed, "variant": "normal", "match_eligible": True, "display_allowed": True}], db)
            self.assertEqual((len(rows), len(holds), len(skipped)), (1, 1, 1))
            self.assertFalse(rows[0]["match_eligible"])
            self.assertFalse(rows[0]["display_allowed"])
            self.assertFalse(rows[0]["attributes"]["physical_printing_verified"])
            self.assertEqual(db.execute("SELECT * FROM card").fetchall(), baseline)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

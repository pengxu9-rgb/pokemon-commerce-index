"""Pinned denominator corrections must survive catalog re-imports."""

import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, number_conflicts, number_graph


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class NumberConflictTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.rules = [json.loads(line) for line in (
            CATALOG / "ja-number-denominator-conflict-rules.jsonl").read_text().splitlines()]

    def tearDown(self):
        self.db.close()

    def card(self, revision: str, number: str = "001/174") -> dict:
        return {"language": "ja", "set_code": "SV11B", "collector_number": number,
                "variant": "normal", "name": "ツタージャ",
                "provenance": f"tcgdex:{revision}:fixture.ts:sha256:" + "a" * 64,
                "rights_reference": "fixture", "display_allowed": False,
                "match_eligible": True}

    def test_rule_disables_existing_card_and_survives_reimport(self):
        current = self.rules[1]["catalog_source_prefix"].split(":")[1]
        card = self.card(current)
        core.import_cards(self.db, [card])
        self.assertEqual(self.db.execute("SELECT match_eligible FROM card").fetchone()[0], 1)
        result = number_conflicts.apply_rules(self.db, [self.rules[1]])
        self.assertEqual(result, {"rules": 1, "cards_disabled": 1})
        core.import_cards(self.db, [card])
        self.assertEqual(self.db.execute("SELECT match_eligible FROM card").fetchone()[0], 0)
        context = number_graph.card_number_context(self.db, "ja:SV11B:001/174:normal")
        self.assertEqual(context["source_number_conflict"]["official_denominator"], "086")
        with self.assertRaisesRegex(ValueError, "number conflict rule"):
            core.import_cards(self.db, [self.card("b" * 40)])
        self.assertEqual(number_conflicts.apply_rules(self.db, [self.rules[1]])[
            "cards_disabled"], 0)

    def test_rule_does_not_block_other_source_revision_or_number(self):
        number_conflicts.apply_rules(self.db, [self.rules[1]])
        core.import_cards(self.db, [self.card("b" * 40), self.card(
            self.rules[1]["catalog_source_prefix"].split(":")[1], "001/086")])
        self.assertEqual(self.db.execute("SELECT SUM(match_eligible) FROM card").fetchone()[0], 2)

    def test_rule_rejects_page_with_wrong_official_denominator(self):
        row = dict(self.rules[1])
        row["official_pages"] = [dict(page) for page in row["official_pages"]]
        row["official_pages"][0]["collector_number"] = "001/174"
        with self.assertRaisesRegex(ValueError, "official page evidence"):
            number_conflicts.apply_rules(self.db, [row])


if __name__ == "__main__":
    unittest.main()

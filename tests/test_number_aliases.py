"""Pinned number leads stay outside the offer-matching and price graph."""

import copy
import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, number_aliases, number_conflicts, number_graph


CATALOG = Path(__file__).resolve().parents[1] / "catalog"


class NumberAliasTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.rules = [json.loads(line) for line in (
            CATALOG / "ja-number-denominator-conflict-rules.jsonl").read_text().splitlines()]
        self.row = json.loads((CATALOG / "ja-number-alias-candidates.jsonl").read_text().splitlines()[0])
        core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
            "collector_number": self.row["catalog_number"], "variant": self.row["card_id"].rsplit(":", 1)[-1],
            "name": self.row["catalog_name"], "provenance": self.row["source_provenance"],
            "rights_reference": "fixture", "display_allowed": False}])
        number_conflicts.apply_rules(self.db, [self.rules[0]])

    def tearDown(self):
        self.db.close()

    def test_source_bound_alias_does_not_enable_matching(self):
        self.assertEqual(number_aliases.apply_candidates(self.db, [self.row]), {"candidates": 1})
        self.assertEqual(number_aliases.apply_candidates(self.db, [self.row]), {"candidates": 1})
        context = number_graph.card_number_context(self.db, self.row["card_id"])
        alias = context["source_number_alias_candidate"]
        self.assertEqual(alias["official_number_candidate"], "001/054")
        self.assertEqual(alias["physical_printing_status"], "unverified")
        self.assertEqual(alias["offer_matching_status"], "blocked")
        self.assertEqual(context["match_eligible"], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_number_alias_candidate").fetchone()[0], 1)
        with self.assertRaisesRegex(ValueError, "number alias evidence"):
            core.import_cards(self.db, [{"language": "ja", "set_code": "SM10b",
                "collector_number": self.row["catalog_number"],
                "variant": self.row["card_id"].rsplit(":", 1)[-1],
                "name": "違うカード", "provenance": self.row["source_provenance"],
                "rights_reference": "fixture", "display_allowed": False}])

    def test_rejects_number_or_source_evidence_changes(self):
        for change in ({"official_number_candidate": "002/054"},
                       {"source_provenance": "other"},
                       {"official_source_revision": "f" * 40}):
            row = copy.deepcopy(self.row) | change
            with self.assertRaises(ValueError):
                number_aliases.apply_candidates(self.db, [row])
        row = copy.deepcopy(self.row)
        row["official_records"][0]["name"] = "違うカード"
        with self.assertRaises(ValueError):
            number_aliases.apply_candidates(self.db, [row])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_number_alias_candidate").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()

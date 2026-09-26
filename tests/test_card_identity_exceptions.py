import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core
from scripts.audit_jp_source_conflicts import compact, official_record


class CardIdentityExceptionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.seed = {"language": "ja", "set_code": "M6", "collector_number": "098/076",
                     "variant": "holo", "name": "とくちゅうチョッキ", "rarity": "Mega Hyper Rare",
                     "provenance": "tcgdex:pinned:card", "rights_reference": "fixture",
                     "display_allowed": False, "match_eligible": True}
        core.import_cards(self.db, [self.seed])
        self.exception = {"card_id": "ja:M6:098/076:holo",
                          "original_name": "とくちゅうチョッキ",
                          "source_provenance": "tcgdex:pinned:card",
                          "corrected_name": "ポケモンキャッチャー",
                          "corrected_rarity": "SR",
                          "official_url": "https://www.pokemon-card.com/card-search/details.php/card/50539",
                          "official_page_sha256": "a" * 64,
                          "reason": "official exact page"}

    def tearDown(self):
        self.db.close()

    def test_correction_survives_pinned_reimport_and_blocks_match(self):
        core.apply_card_identity_exceptions(self.db, [self.exception])
        core.import_cards(self.db, [self.seed])
        card = core.catalog_card_internal(self.db, self.exception["card_id"])
        self.assertEqual(card["card"]["name"], "ポケモンキャッチャー")
        self.assertEqual(card["card"]["rarity"], "SR")
        self.assertEqual(card["card"]["match_eligible"], 0)
        self.assertEqual(card["identity_exception"]["official_url"],
                         self.exception["official_url"])
        self.assertIsNone(core.resolve(self.db, {"title": "ポケモンキャッチャー M6 098/076"})[0])

    def test_stale_or_invalid_exception_rolls_back(self):
        stale = {**self.exception, "original_name": "wrong"}
        with self.assertRaises(ValueError):
            core.apply_card_identity_exceptions(self.db, [self.exception, stale])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_identity_exception").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT match_eligible FROM card").fetchone()[0], 1)

    def test_name_normalization_is_format_only(self):
        self.assertEqual(compact("アローラ ロコン"), compact("アローラロコン"))
        with self.assertRaises(ValueError):
            official_record("https://evil.example/card/50539", "M6", "098/076")

    def test_committed_exceptions_bind_verified_official_pages(self):
        catalog = Path(__file__).resolve().parents[1] / "catalog"
        audit = json.loads((catalog / "jp-source-conflict-official-audit.json").read_text())
        exceptions = [json.loads(line) for line in
                      (catalog / "jp-card-identity-exceptions.jsonl").read_text().splitlines()]
        self.assertEqual(len(exceptions), 19)
        self.assertEqual(audit["counts"]["official_prismstar_groups"], 15)
        by_key = {(row["set_code"], row["collector_number"]): row
                  for row in audit["conflicts"]}
        for exception in exceptions:
            _, set_code, number, _ = exception["card_id"].split(":")
            record = by_key[(set_code, number)]["official_records"][0]
            self.assertEqual(exception["official_url"], record["url"])
            self.assertEqual(exception["official_page_sha256"], record["page_sha256"])
            if exception["corrected_rarity"] == "Prism Star":
                self.assertIn("ic_prismstar.gif", record["rarity_icons"])
            else:
                self.assertEqual(exception["corrected_name"], record["name"])


if __name__ == "__main__":
    unittest.main()

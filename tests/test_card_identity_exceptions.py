import json
import sqlite3
import unittest
from pathlib import Path

from pokemon_index import core, discovery_graph, listing_candidates
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

    def test_shifted_legacy_exception_is_repaired(self):
        card_id = self.exception["card_id"]
        self.db.execute("""INSERT INTO card_identity_exception
            (card_id,original_name,corrected_name,corrected_rarity,official_url,
             official_page_sha256,reason,applied_at,source_provenance)
             VALUES (?,?,?,?,?,?,?,?,?)""",
            (card_id, "とくちゅうチョッキ", "tcgdex:pinned:card", "ポケモンキャッチャー",
             "Prism Star", self.exception["official_url"], "a" * 64,
             "official exact page", "2026-09-26T00:00:00+00:00"))
        self.db.execute("UPDATE card SET name='tcgdex:pinned:card',rarity='ポケモンキャッチャー' WHERE card_id=?",
                        (card_id,))
        core.init_db(self.db)
        card = core.catalog_card_internal(self.db, card_id)
        self.assertEqual(card["card"]["name"], "ポケモンキャッチャー")
        self.assertEqual(card["card"]["rarity"], "Prism Star")
        self.assertEqual(card["identity_exception"]["source_provenance"], "tcgdex:pinned:card")
        self.assertEqual(card["identity_exception"]["official_printing_type"], "prism_star")

    def test_insert_uses_column_names_after_legacy_table_upgrade(self):
        self.db.execute("DROP TABLE card_identity_exception")
        self.db.execute("""CREATE TABLE card_identity_exception (
            card_id TEXT PRIMARY KEY, original_name TEXT, corrected_name TEXT,
            corrected_rarity TEXT, official_url TEXT, official_page_sha256 TEXT,
            reason TEXT, applied_at TEXT)""")
        core.init_db(self.db)
        core.apply_card_identity_exceptions(self.db, [self.exception])
        card = core.catalog_card_internal(self.db, self.exception["card_id"])
        self.assertEqual(card["card"]["name"], "ポケモンキャッチャー")
        self.assertEqual(card["identity_exception"]["source_provenance"], "tcgdex:pinned:card")
        self.assertEqual(card["identity_exception"]["official_url"], self.exception["official_url"])

    def test_official_printing_type_is_queryable_but_not_price_matchable(self):
        seed = {**self.seed, "set_code": "SM5M", "collector_number": "030/066",
                "name": "ギラティナ", "rarity": "Rare Holo"}
        core.import_cards(self.db, [seed])
        exception = {**self.exception, "card_id": "ja:SM5M:030/066:holo",
                     "original_name": "ギラティナ", "corrected_name": "ギラティナ",
                     "corrected_rarity": "Prism Star",
                     "official_printing_type": "prism_star"}
        core.apply_card_identity_exceptions(self.db, [exception])
        search = core.catalog_search_internal(self.db, "", printing_type="prism_star")
        self.assertEqual(search["total"], 1)
        self.assertEqual(search["cards"][0]["official_printing_type"], "prism_star")
        self.assertEqual(core.catalog_search_internal(self.db, "プリズムスター")["total"], 1)
        candidate = listing_candidates.retrieve(self.db, "ギラティナ プリズムスター SM5M 030/066")
        self.assertEqual(candidate["candidates"][0]["official_printing_type"], "prism_star")
        self.assertFalse(candidate["candidates"][0]["match_eligible"])
        self.assertIsNone(core.resolve(self.db, {"title": "ギラティナ プリズムスター SM5M 030/066"})[0])
        discovery_graph.save_exploration(self.db, {
            "session_id": "prism-search", "owner_key": "test-user", "expected_version": 0,
            "constraints": {"printing_type": "prism_star"}})
        found = discovery_graph.exploration_candidates(self.db, "prism-search", "test-user")
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["cards"][0]["official_printing_type"], "prism_star")
        selected = discovery_graph.save_exploration(self.db, {
            "session_id": "prism-search", "owner_key": "test-user", "expected_version": 1,
            "target_card_id": exception["card_id"]})
        self.assertFalse(selected["ready_for_offer_tracking"])

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
                self.assertEqual(exception["official_printing_type"], "prism_star")
            else:
                self.assertEqual(exception["corrected_name"], record["name"])


if __name__ == "__main__":
    unittest.main()

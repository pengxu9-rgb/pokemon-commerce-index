"""Official rarity corrections must preserve card identity and source binding."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import catalog_question_resolver_v2, core, question_routing_v3
from scripts.build_catalog_snapshot import build
from scripts.audit_jp_source_conflicts import RARITY_ICON

ROOT = Path(__file__).resolve().parents[1]


class CardRarityCorrectionTests(unittest.TestCase):
    def test_official_icon_parser_keeps_uppercase_mur(self):
        html = '<img src="/assets/images/card/rarity/ic_rare_MUR.gif" />'
        self.assertEqual(RARITY_ICON.findall(html), ["ic_rare_MUR.gif"])

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        self.seed = {"language": "ja", "set_code": "M6", "collector_number": "110/076",
                     "variant": "holo", "name": "メガレックウザex", "rarity": "Mega Hyper Rare",
                     "provenance": "tcgdex:pinned:110", "rights_reference": "fixture",
                     "display_allowed": False, "match_eligible": True}
        core.import_cards(self.db, [self.seed])
        self.correction = {"card_id": "ja:M6:110/076:holo",
                           "original_name": self.seed["name"],
                           "original_rarity": self.seed["rarity"],
                           "source_provenance": self.seed["provenance"],
                           "corrected_rarity": "SAR",
                           "reference_provenance": "ptcg-database:pinned:50551",
                           "official_url": "https://www.pokemon-card.com/card-search/details.php/card/50551",
                           "official_page_sha256": "a" * 64,
                           "official_rarity_icon": "ic_rare_sar.gif"}

    def tearDown(self):
        self.db.close()

    def test_overlay_survives_reimport_without_disabling_matching(self):
        core.apply_card_rarity_corrections(self.db, [self.correction])
        core.import_cards(self.db, [self.seed])
        core.apply_card_rarity_corrections(self.db, [self.correction])
        row = self.db.execute("SELECT rarity,match_eligible FROM card WHERE card_id=?",
                              (self.correction["card_id"],)).fetchone()
        self.assertEqual((row["rarity"], row["match_eligible"]), ("SAR", 1))
        detail = core.catalog_card_internal(self.db, self.correction["card_id"])
        self.assertEqual(detail["rarity_correction"]["official_url"],
                         self.correction["official_url"])
        with self.assertRaisesRegex(ValueError, "rarity correction source"):
            core.import_cards(self.db, [{**self.seed, "rarity": "MUR"}])

    def test_bad_or_stale_evidence_rolls_back(self):
        bad = {**self.correction, "official_rarity_icon": "ic_rare_ar.gif"}
        with self.assertRaisesRegex(ValueError, "consistent official evidence"):
            core.apply_card_rarity_corrections(self.db, [self.correction, bad])
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM card_rarity_correction").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT rarity FROM card").fetchone()[0],
                         "Mega Hyper Rare")

    def test_versioned_catalog_fixes_known_no_match_without_inventing_printing(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "catalog.sqlite3"
            result = build(ROOT / "catalog-build-manifest-rarity-v1.json", db_path)
            self.assertEqual(result["rarity_corrections"], 35)
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                facts = {row["id"]: row["facts"] for row in
                         (json.loads(line) for line in (ROOT / "sandbox/public_questions/v8/gemini_facts.jsonl")
                          .read_text().splitlines())}
                ray_facts = {k: facts["pubq8-002"][k] for k in question_routing_v3.FACT_FIELDS}
                mew_facts = {k: facts["pubq8-003"][k] for k in question_routing_v3.FACT_FIELDS}
                ray_facts["primary_goal"] = mew_facts["primary_goal"] = "price_comparison"
                ray = catalog_question_resolver_v2.resolve_question(db, ray_facts)
                mew = catalog_question_resolver_v2.resolve_question(db, mew_facts)
                self.assertEqual(ray["resolution"]["status"], "not_attempted")
                self.assertIn("ja:M6:110/076:holo", [r["card_id"] for r in ray["candidates"]])
                self.assertEqual(mew["resolution"]["status"], "no_match")


if __name__ == "__main__":
    unittest.main()

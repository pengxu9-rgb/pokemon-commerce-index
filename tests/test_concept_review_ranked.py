import hashlib
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import concept_review_ranked


class RankedConceptPacketTests(unittest.TestCase):
    def test_localized_set_date_is_available_to_ranker(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            card = repo / "data-asia" / "SV" / "SV2a" / "001.ts"
            card.parent.mkdir(parents=True)
            card.write_text("effect: {ja: '30ダメージ'}", encoding="utf-8")
            header = repo / "data-asia" / "SV" / "SV2a.ts"
            header.write_text("releaseDate: {ja: '2023-06-16', en: '2023-09-22'}",
                              encoding="utf-8")
            revision = concept_review_ranked.REVISION
            provenance = (f"tcgdex:{revision}:data-asia/SV/SV2a/001.ts:sha256:"
                          f"{hashlib.sha256(card.read_bytes()).hexdigest()}")
            with sqlite3.connect(":memory:") as db:
                db.row_factory = sqlite3.Row
                db.execute("CREATE TABLE catalog_set_localized "
                           "(language TEXT, set_code TEXT, provenance TEXT)")
                db.execute("INSERT INTO catalog_set_localized VALUES (?, ?, ?)",
                           ("ja", "SV2a", f"tcgdex:{revision}:data-asia/SV/SV2a.ts"))
                row = {"card_id": "ja:SV2A:001/165:standard", "provenance": provenance,
                       "language": "ja", "set_code": "SV2a"}
                scalar = concept_review_ranked._features(db, repo, row, {}, "scalar")
                localized = concept_review_ranked._features(db, repo, row, {}, "localized")
            self.assertIsNone(scalar["release_date"])
            self.assertEqual(localized["release_date"], date(2023, 6, 16))

    def test_pinned_source_is_checked_before_ranking(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = Path(folder)
            source = repo / "card.ts"
            source.write_text("effect: { ja: '30' }", encoding="utf-8")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            self.assertEqual(concept_review_ranked._read_verified(repo, "card.ts", digest)[1],
                             digest)
            source.write_text("effect: { ja: '50' }", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                concept_review_ranked._read_verified(repo, "card.ts", digest)
            with self.assertRaisesRegex(ValueError, "source path leaves"):
                concept_review_ranked._read_verified(repo, "../outside.ts", None)

    def test_effect_and_date_agreement_rank_above_unrelated_card(self):
        anchor = {"effect_numbers": ["30", "3"],
                  "release_date": date(2023, 3, 1), "era": "SV"}
        matching = {"effect_numbers": ["30", "3"],
                    "release_date": date(2023, 5, 1), "era": "SV"}
        unrelated = {"effect_numbers": ["50", "7"],
                     "release_date": date(2021, 5, 1), "era": "S"}
        positive, positive_parts = concept_review_ranked._score(anchor, matching)
        negative, _ = concept_review_ranked._score(anchor, unrelated)
        self.assertGreater(positive, negative)
        self.assertEqual(positive_parts["release_gap_days"], 61)

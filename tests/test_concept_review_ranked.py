import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import concept_review_ranked


class RankedConceptPacketTests(unittest.TestCase):
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

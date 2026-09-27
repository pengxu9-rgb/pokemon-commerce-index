"""Legacy image URLs require a pinned matching collector-number filename."""

import unittest

from scripts.probe_legacy_en_card_assets import candidate_url


class LegacyAssetCandidateTests(unittest.TestCase):
    def test_numeric_zero_padding_and_set_scope(self):
        card = {"card_id": "en:SM3.5:062/073:standard",
                "provenance": "tcgdex:rev:data/Sun & Moon/Shining Legends/62.ts:sha256:hash"}
        self.assertEqual(candidate_url(card),
                         "https://images.pokemontcg.io/sm35/62_hires.png")

    def test_other_set_is_not_silently_mapped(self):
        card = {"card_id": "en:MEP:069/MEP:holo",
                "provenance": "tcgdex:rev:data/Mega/069.ts:sha256:hash"}
        with self.assertRaisesRegex(ValueError, "unsupported"):
            candidate_url(card)


if __name__ == "__main__":
    unittest.main()

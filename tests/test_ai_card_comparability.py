import unittest

from scripts.compile_ai_card_comparability import compile_pair


class AIComparabilityTests(unittest.TestCase):
    def setUp(self):
        self.pair = {
            "candidate_id": "pair-1", "source_snapshot_sha256": "a" * 64,
            "anchor": {"card_id": "ja:S1:001/100:holo", "variant": "holo",
                       "rarity": "Ultra Rare"},
            "candidate": {"card_id": "en:E1:001/100:holo", "variant": "holo",
                          "rarity": "Ultra Rare"},
        }
        self.art = {"candidate_id": "pair-1", "source_snapshot_sha256": "a" * 64,
                    "artwork_decision": "same", "ja_image_status": "included",
                    "en_image_status": "included"}
        self.audit = {"candidate_id": "pair-1", "source_snapshot_sha256": "a" * 64,
                      "model_version": "gemini-3.8-flash",
                      "ja_image": {"image_sha256": "b" * 64},
                      "en_image": {"image_sha256": "c" * 64}}

    def test_same_art_and_nominal_finish_are_context_only(self):
        result = compile_pair(self.pair, self.art, self.audit)
        self.assertEqual(result["comparison_scope"], "nominal_variant_peer")
        self.assertFalse(result["price_series_merge_allowed"])
        self.assertFalse(result["numeric_cross_region_spread_allowed"])

    def test_no_same_art_claim_without_two_hashed_images(self):
        self.art["en_image_status"] = "fetch_failed"
        with self.assertRaisesRegex(ValueError, "two hashed images"):
            compile_pair(self.pair, self.art, self.audit)

    def test_artwork_mismatch_overrides_nominal_variant(self):
        self.art["artwork_decision"] = "different"
        self.assertEqual(compile_pair(self.pair, self.art, self.audit)[
            "comparison_scope"], "separate_artwork")

    def test_snapshot_mismatch_is_rejected(self):
        self.audit["source_snapshot_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "does not bind"):
            compile_pair(self.pair, self.art, self.audit)


if __name__ == "__main__":
    unittest.main()

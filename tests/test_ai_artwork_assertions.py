import unittest

from scripts.build_ai_artwork_assertions import build


class AIArtworkAssertionTests(unittest.TestCase):
    def test_identity_uncertainty_blocks_same_artwork_proposal(self):
        row = {"candidate_id": "candidate", "source_snapshot_sha256": "a" * 64,
               "ja_card_id": "ja:X:001/010:normal",
               "en_card_id": "en:Y:001/010:normal",
               "artwork_decision": "same", "artwork_model": "gemini-3.8-flash",
               "artwork_rationale": "matching details", "model_response_sha256": "b" * 64,
               "en_image_identity": "uncertain", "ja_image_sha256": "c" * 64,
               "en_image_sha256": "d" * 64, "ja_image_ref": "source-ja",
               "en_image_ref": "source-en", "comparison_scope": "artwork_peer_only"}
        with self.assertRaisesRegex(ValueError, "confirmed English image identity"):
            build([row])
        row["en_image_identity"] = "match"
        proposals = build([row])
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["review_status"], "proposed")
        self.assertEqual(proposals[0]["relation_type"], "same_artwork")


if __name__ == "__main__":
    unittest.main()

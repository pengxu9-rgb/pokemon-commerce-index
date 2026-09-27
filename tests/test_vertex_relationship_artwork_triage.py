import unittest
from unittest.mock import patch

from scripts.vertex_relationship_artwork_triage import STANDARD_LIMIT, _curated_image, _mime, _parse


class ArtworkTriageTests(unittest.TestCase):
    def test_model_none_limit_cannot_erase_printing_boundary(self):
        response = {"modelVersion": "gemini-3.8-flash", "candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": (
                '{"artwork_decision":"same","rationale":"Matching illustration details",'
                '"evidence_limits":"None","en_image_identity":"match"}')}]} }]}
        result = _parse(response)
        self.assertEqual(result["artwork_decision"], "same")
        self.assertIn(STANDARD_LIMIT, result["evidence_limits"])

    def test_unexpected_model_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "model version"):
            _parse({"modelVersion": "other", "candidates": []})

    def test_official_jpeg_is_sent_with_correct_mime(self):
        self.assertEqual(_mime(b"\xff\xd8\xffsomething"), "image/jpeg")

    def test_legacy_english_png_is_sent_with_correct_mime(self):
        self.assertEqual(_mime(b"\x89PNG\r\n\x1a\ncontent"), "image/png")

    def test_legacy_asset_rejects_unbound_host(self):
        row = {"candidate_id": "id", "source_snapshot_sha256": "a" * 64,
               "candidate": {"card_id": "en:SM3.5:062/073:standard", "name": "Lillie"}}
        record = {"candidate_id": "id", "source_snapshot_sha256": "a" * 64,
                  "en_card_id": row["candidate"]["card_id"], "en_name": "Lillie",
                  "asset_source": "pokemon_tcg_api_image_candidate",
                  "image_url": "https://other.example/sm35/62_hires.png",
                  "image_sha256": "b" * 64}
        with patch("urllib.request.urlopen") as fetch:
            image, evidence = _curated_image(record, row)
        self.assertIsNone(image)
        self.assertEqual(evidence["status"], "curated_asset_unavailable")
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()

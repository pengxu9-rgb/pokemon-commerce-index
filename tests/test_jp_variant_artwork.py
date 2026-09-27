"""Source and model result guards for Japanese same-number visual review."""

import io
import http.client
import unittest
from unittest.mock import patch

from PIL import Image

from scripts.review_jp_variant_artwork import model_image, model_request, parse_response, review_one
from scripts.vertex_concept_review import MODEL


class VariantArtworkTest(unittest.TestCase):
    def test_gif_is_converted_in_memory_and_remains_visually_available(self):
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), (120, 40, 20)).save(buffer, format="GIF")
        converted, mime, method = model_image(buffer.getvalue())
        self.assertTrue(converted.startswith(b"\x89PNG"))
        self.assertEqual((mime, method), ("image/png", "gif_first_frame_to_png"))

    def test_request_includes_every_record_once(self):
        group = {"source_jp_ids": [11, 12, 13]}
        request = model_request(group, [b"\xff\xd8\xffx", b"\x89PNGx", b"\xff\xd8\xffy"])
        parts = request["contents"][0]["parts"]
        self.assertEqual([part["inlineData"]["mimeType"] for part in parts
                          if "inlineData" in part], ["image/jpeg", "image/png", "image/jpeg"])

    def test_parse_rejects_wrong_source_ids(self):
        response = {"modelVersion": MODEL, "candidates": [{"finishReason": "STOP",
                    "content": {"parts": [{"text": '{"comparisons":[{"source_jp_id":99,'
                                           '"label":"exact_artwork","visible_reason":"same trees",'
                                           '"possible_surface_or_stamp_difference":false}]}'}]}}]}
        with self.assertRaisesRegex(ValueError, "comparison IDs"):
            parse_response(response, [11, 12])

    def test_incomplete_model_response_abstains_without_crashing_batch(self):
        group = {"card_id": "ja:S1:001/100:unverified_multi_record",
                 "source_jp_ids": [11, 12], "source_record_sha256": ["a", "b"]}
        prior = {"records": [{"sha256": "1"}, {"sha256": "2"}]}
        with patch("scripts.review_jp_variant_artwork.source_images", return_value=(
                [b"\xff\xd8\xffa", b"\xff\xd8\xffb"], [{"status": "included"}, {"status": "included"}])), \
             patch("scripts.review_jp_variant_artwork._call_model",
                   side_effect=http.client.IncompleteRead(b"partial")) as model, \
             patch("scripts.review_jp_variant_artwork.time.sleep"):
            result = review_one(group, prior, None, "project", "global", "token")
        self.assertEqual(result["review_status"], "model_error")
        self.assertEqual(result["model_error_type"], "IncompleteRead")
        self.assertEqual(model.call_count, 3)


if __name__ == "__main__":
    unittest.main()

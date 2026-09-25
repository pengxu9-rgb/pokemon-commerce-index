import unittest

from scripts.vertex_relationship_artwork_triage import STANDARD_LIMIT, _parse


class ArtworkTriageTests(unittest.TestCase):
    def test_model_none_limit_cannot_erase_printing_boundary(self):
        response = {"modelVersion": "gemini-3.8-flash", "candidates": [{
            "finishReason": "STOP", "content": {"parts": [{"text": (
                '{"artwork_decision":"same","rationale":"Matching illustration details",'
                '"evidence_limits":"None"}')}]} }]}
        result = _parse(response)
        self.assertEqual(result["artwork_decision"], "same")
        self.assertIn(STANDARD_LIMIT, result["evidence_limits"])

    def test_unexpected_model_version_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "model version"):
            _parse({"modelVersion": "other", "candidates": []})


if __name__ == "__main__":
    unittest.main()

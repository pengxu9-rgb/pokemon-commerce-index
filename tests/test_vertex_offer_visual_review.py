import unittest

from scripts.vertex_offer_visual_review import _parse


def response(condition_decision="assessed", condition_bucket="near_mint"):
    import json
    return {"modelVersion": "gemini-3.8-flash", "candidates": [{
        "finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
            "identity_decision": "match", "finish_decision": "match",
            "observed_finish": "normal", "condition_decision": condition_decision,
            "condition_bucket": condition_bucket, "rationale": "visible card number and corners",
        })}]}}]}


class VertexOfferVisualReviewTests(unittest.TestCase):
    def test_condition_requires_back_photo(self):
        with self.assertRaisesRegex(ValueError, "front/back"):
            _parse(response(), has_back=False)
        self.assertEqual(_parse(response(), has_back=True)["condition_bucket"], "near_mint")

    def test_uncertain_condition_cannot_keep_a_bucket(self):
        finding = _parse(response("uncertain", "near_mint"), has_back=False)
        self.assertIsNone(finding["condition_bucket"])


if __name__ == "__main__":
    unittest.main()

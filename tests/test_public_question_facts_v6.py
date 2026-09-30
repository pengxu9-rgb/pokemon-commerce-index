import unittest
import json
from unittest.mock import patch

from scripts.vertex_public_question_facts_v6 import _extract_one, _request, validate_answer
from tests.test_question_routing_v6 import facts


class PublicQuestionFactsV6Tests(unittest.TestCase):
    def answer(self):
        question = {"id": "scope", "language": "en", "media_state": "text_only",
                    "question": "Which recent normal Pokémon cards can sell individually or as evolution lines?"}
        answer = {"facts": facts(), "rationale": "The poster asks which card class can sell in these formats.",
                  "evidence_spans": {"goal": "can sell individually or as evolution lines",
                                     "platform_refs": [], "merchant_ref": None, "rarity": None,
                                     "finish": None, "time_window": None, "purchase_constraints": None,
                                     "sale_constraints": None, "sale_scope": "recent normal Pokémon cards",
                                     "sale_formats": ["individually", "evolution lines"]}}
        # These fields are absent in the actual text; the helper's old identity
        # defaults must not appear in this extractor fixture.
        answer["facts"]["identity_tokens"].update(set_name=None, collector_number=None, language=None)
        answer["facts"]["language_mentions"] = []
        return question, answer

    def test_sale_scope_and_formats_require_direct_evidence(self):
        question, answer = self.answer()
        self.assertEqual(validate_answer(answer, question)[0]["primary_goal"], "seller_saleability")
        answer["facts"]["sale_formats"] = ["bulk", "evolution_line"]
        with self.assertRaisesRegex(ValueError, "sale_formats evidence"):
            validate_answer(answer, question)

    def test_invented_scope_and_price_cohort_are_rejected(self):
        question, answer = self.answer()
        answer["facts"]["sale_scope"] = "Japanese vintage PSA 10 cards"
        with self.assertRaisesRegex(ValueError, "sale_scope evidence"):
            validate_answer(answer, question)
        question, answer = self.answer()
        answer["facts"]["sale_cohort"] = {"unit_ids": ["invented"]}
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            validate_answer(answer, question)

    def test_prompt_names_new_intent_and_preserves_selling_format_boundaries(self):
        question, _ = self.answer()
        prompt = _request(question)[0]["contents"][0]["parts"][0]["text"]
        self.assertIn("seller_saleability asks WHICH CLASSES", prompt)
        self.assertIn("Many cards or a collection alone does not imply", prompt)

    def test_output_exhaustion_retries_with_a_recorded_larger_limit(self):
        question, answer = self.answer()
        question["question_sha256"] = "a" * 64
        responses = [{"modelVersion": "fixture", "candidates": [{"finishReason": "MAX_TOKENS"}],
                      "usageMetadata": {"thoughtsTokenCount": 8100}},
                     {"modelVersion": "fixture", "candidates": [{"finishReason": "STOP",
                       "content": {"parts": [{"text": json.dumps(answer)}]}}]}]
        with patch("scripts.vertex_public_question_facts_v6._call_model", side_effect=responses):
            row = _extract_one(question, "test-project", "global", "test-token")
        self.assertEqual((row["status"], row["attempts"]), ("ok", 2))
        self.assertEqual(row["attempt_errors"][0]["requested_output_tokens"], 8192)
        self.assertEqual(row["generation_config"]["maxOutputTokens"], 16384)
        self.assertEqual(row["attempt_errors"][0]["usage_metadata"]["thoughtsTokenCount"], 8100)


if __name__ == "__main__":
    unittest.main()

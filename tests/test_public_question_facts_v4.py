import unittest

from scripts.vertex_public_question_facts_v4 import _request, validate_answer


class PublicQuestionFactsV4Tests(unittest.TestCase):
    def test_purchase_timing_fields_require_direct_question_spans(self):
        question = {"id": "example", "language": "en", "media_state": "text_only",
                    "question": "Should I buy Battle Day Lillie now or wait six months if I can spend $500?"}
        facts = {"object_type": "single_card", "primary_goal": "purchase_timing",
                 "transaction_context": "prospective_buy", "seller_channel": "none",
                 "identity_tokens": {"card_names": ["Lillie"], "set_name": "Battle Day",
                                     "collector_number": None, "language": None,
                                     "rarity": None, "finish": None, "grade": None},
                 "media_state": "none", "language_mentions": [],
                 "platform_refs": [], "merchant_ref": None, "destination": None,
                 "time_window": "six months", "purchase_constraints": "$500"}
        answer = {"facts": facts, "rationale": "The user asks whether to wait to buy.",
                  "evidence_spans": {"goal": "buy Battle Day Lillie now or wait",
                                     "platform_refs": [], "merchant_ref": None,
                                     "rarity": None, "finish": None,
                                     "time_window": "six months",
                                     "purchase_constraints": "$500"}}
        self.assertEqual(validate_answer(answer, question)[0]["primary_goal"],
                         "purchase_timing")
        answer["evidence_spans"]["time_window"] = "next year"
        with self.assertRaisesRegex(ValueError, "time_window evidence"):
            validate_answer(answer, question)
        answer["evidence_spans"]["time_window"] = "six months"
        answer["evidence_spans"]["goal"] = "market value"
        with self.assertRaisesRegex(ValueError, "goal evidence"):
            validate_answer(answer, question)

    def test_prompt_separates_trend_from_current_comparison(self):
        question = {"id": "example", "language": "en", "media_state": "text_only",
                    "question": "Why did this card's price rise?"}
        request, prompt_sha = _request(question)
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertIn("price_trend asks whether or why a price moved over time", prompt)
        self.assertIn("purchase_timing asks whether to buy", prompt)
        self.assertIn("An old forum price is question context", prompt)
        self.assertEqual(len(prompt_sha), 64)


if __name__ == "__main__":
    unittest.main()

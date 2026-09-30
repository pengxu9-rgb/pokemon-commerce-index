import unittest

from scripts.vertex_public_question_facts_v5 import _request, validate_answer


class PublicQuestionFactsV5Tests(unittest.TestCase):
    def test_seller_constraint_requires_direct_span(self):
        question = {"id": "example", "language": "en", "media_state": "text_only",
                    "question": "I own Pikachu and need cash this month. Sell now or hold?"}
        facts = {"object_type": "single_card", "primary_goal": "seller_timing",
                 "transaction_context": "owned", "seller_channel": "none",
                 "identity_tokens": {"card_names": ["Pikachu"], "set_name": None,
                                     "collector_number": None, "language": None,
                                     "rarity": None, "finish": None, "grade": None},
                 "media_state": "none", "language_mentions": [],
                 "platform_refs": [], "merchant_ref": None, "destination": None,
                 "time_window": "this month", "purchase_constraints": None,
                 "sale_constraints": "need cash"}
        answer = {"facts": facts, "rationale": "The owner asks when to sell.",
                  "evidence_spans": {"goal": "Sell now or hold",
                                     "platform_refs": [], "merchant_ref": None,
                                     "rarity": None, "finish": None,
                                     "time_window": "this month",
                                     "purchase_constraints": None,
                                     "sale_constraints": "need cash"}}
        self.assertEqual(validate_answer(answer, question)[0]["primary_goal"],
                         "seller_timing")
        answer["evidence_spans"]["sale_constraints"] = "target $500"
        with self.assertRaisesRegex(ValueError, "sale_constraints evidence"):
            validate_answer(answer, question)

    def test_prompt_separates_new_goal_boundaries(self):
        question = {"id": "example", "language": "en", "media_state": "text_only",
                    "question": "Why are English cards worth more than Japanese ones?"}
        request, prompt_sha = _request(question)
        prompt = request["contents"][0]["parts"][0]["text"]
        for marker in ("seller_timing asks whether the OWNER should sell",
                       "relative_value_explanation", "price_comparison",
                       "collecting_preference", "sale_constraints"):
            self.assertIn(marker, prompt)
        self.assertEqual(len(prompt_sha), 64)


if __name__ == "__main__":
    unittest.main()

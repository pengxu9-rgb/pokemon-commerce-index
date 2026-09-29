import json
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import question_routing_v3 as routing
from pokemon_index.question_routing_v3 import plan_question, validate_facts
from scripts.public_question_sandbox import read_jsonl, sha_file
from scripts import vertex_public_question_facts_v3 as extractor
from scripts.vertex_public_question_facts_v3 import _extract_one, validate_answer


def facts(*, goal="marketplace_policy", context="sold_pending_fulfillment",
          channel="marketplace_listing", merchant=None, platforms=None, rarity=None,
          finish=None):
    return {"object_type": "single_card", "primary_goal": goal,
            "transaction_context": context, "seller_channel": channel,
            "identity_tokens": {"card_names": ["Pikachu"], "set_name": None,
                                "collector_number": None, "language": None,
                                "rarity": rarity, "finish": finish, "grade": "PSA10"},
            "media_state": "none", "language_mentions": [],
            "platform_refs": ["メルカリ"] if platforms is None else platforms,
            "merchant_ref": merchant, "destination": None}


class QuestionRoutingV3Tests(unittest.TestCase):
    def test_v6_development_replay_is_pinned_and_not_a_fresh_score(self):
        root = Path(__file__).resolve().parents[1] / "sandbox/public_questions/v6/v3_regression"
        manifest = json.loads((root / "manifest.json").read_text())
        report = json.loads((root / "report.json").read_text())
        self.assertEqual(manifest["evaluation_role"], "development_regression_only")
        self.assertEqual(manifest["blind_sha256"], sha_file(root / "blind_questions.jsonl"))
        self.assertEqual(manifest["v3_planner_sha256"], sha_file(Path(routing.__file__)))
        self.assertEqual(manifest["v3_fact_extractor_sha256"], sha_file(Path(extractor.__file__)))
        self.assertEqual(report["manifest_sha256"], sha_file(root / "manifest.json"))
        self.assertEqual(report["checkpoint_sha256"], sha_file(root / "gemini_facts.jsonl"))
        self.assertEqual((report["questions"], report["valid"], report["errors"]), (11, 11, 0))
        self.assertEqual({row["id"] for row in report["rows"]},
                         {row["id"] for row in read_jsonl(root / "blind_questions.jsonl")})
        previous = root.parent / "v3_regression_attempt3"
        old_manifest = json.loads((previous / "manifest.json").read_text())
        self.assertEqual(old_manifest["v3_planner_sha256"],
                         sha_file(previous / "question_routing_v3_snapshot.py"))
        self.assertEqual(old_manifest["v3_fact_extractor_sha256"],
                         sha_file(previous / "vertex_public_question_facts_v3_snapshot.py"))

    def test_seller_sold_pending_authentication_remains_seller_state(self):
        plan = plan_question(facts())
        self.assertEqual(plan["transaction_context"], "sold_pending_fulfillment")
        self.assertEqual([step["action"] for step in plan["steps"]],
                         ["explain_general", "retrieve_current_policy"])
        self.assertEqual(plan["steps"][1]["status"], "blocked")

    def test_observed_third_party_listing_needs_copy_evidence_without_buy_intent(self):
        plan = plan_question(facts(goal="authenticity", context="observed_listing",
                                   channel="none"))
        self.assertEqual(plan["transaction_context"], "observed_listing")
        self.assertIn("ask_front_back_photos",
                      [step["action"] for step in plan["steps"]])

    def test_platform_cannot_be_promoted_to_merchant(self):
        for name in ("Mercari", "メルカリ", "Yahoo!フリマ", "メルカリ / Yahooフリマ"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "not a merchant"):
                validate_facts(facts(merchant=name))
        validate_facts(facts(merchant="Card Rush"))

    def test_rarity_is_separate_from_finish_and_kept_for_catalog(self):
        with self.assertRaisesRegex(ValueError, "rarity code cannot be a finish"):
            validate_facts(facts(finish="MUR"))
        plan = plan_question(facts(goal="price_comparison", context="prospective_buy",
                                   channel="none", rarity="MUR"))
        self.assertEqual(plan["catalog_query"]["rarity"], "MUR")
        self.assertIn("retrieve_catalog", [step["action"] for step in plan["steps"]])
        self.assertNotIn("retrieve_live_offers", [step["action"] for step in plan["steps"]])

    def test_seller_channel_comparison_requires_terms_fees_and_policy(self):
        plan = plan_question(facts(goal="channel_choice", context="owned",
                                   channel="comparing_channels",
                                   platforms=["メルカリ", "Yahooフリマ"]))
        actions = [step["action"] for step in plan["steps"]]
        self.assertEqual(actions, ["explain_general", "retrieve_buyback_terms",
                                   "retrieve_selling_fees", "retrieve_current_policy"])
        self.assertEqual(plan["steps"][2]["status"], "blocked")
        ready = plan_question(facts(goal="channel_choice", context="owned",
                                    channel="comparing_channels"),
                              capabilities={"current_selling_fees"})
        self.assertEqual(next(step for step in ready["steps"] if step["action"] ==
                              "retrieve_selling_fees")["status"], "ready")

    def test_marketplace_seller_price_does_not_use_store_buyback_quote(self):
        resolution = {"status": "unique", "candidate_ids": ["card:1"],
                      "evidence_ref": "catalog-check-1"}
        marketplace = plan_question(facts(goal="seller_pricing", context="listed_for_sale",
                                          channel="marketplace_listing"),
                                    resolution=resolution)
        actions = [step["action"] for step in marketplace["steps"]]
        self.assertNotIn("retrieve_buyback_quotes", actions)
        self.assertIn("retrieve_live_offers", actions)
        self.assertIn("retrieve_verified_sales", actions)
        self.assertIn("retrieve_selling_fees", actions)
        buyback = plan_question(facts(goal="seller_pricing", context="owned",
                                      channel="store_buyback"), resolution=resolution)
        buyback_actions = [step["action"] for step in buyback["steps"]]
        self.assertIn("retrieve_buyback_quotes", buyback_actions)
        self.assertNotIn("retrieve_selling_fees", buyback_actions)

    def test_buyer_transaction_cannot_carry_seller_channel(self):
        with self.assertRaisesRegex(ValueError, "seller channel conflicts"):
            validate_facts(facts(context="completed_purchase"))

    def test_evidence_spans_bind_market_fields_to_question_text(self):
        question = {"question": "メルカリでMURのカードを売りました。", "media_state": "text_only",
                    "language": "ja", "id": "example", "question_sha256": "a" * 64}
        row = facts(rarity="MUR", merchant=None)
        answer = {"facts": row, "rationale": "The card was sold on Mercari.",
                  "evidence_spans": {"platform_refs": ["メルカリ"],
                                     "merchant_ref": None, "rarity": "MUR", "finish": None}}
        self.assertEqual(validate_answer(answer, question)[0]["identity_tokens"]["rarity"],
                         "MUR")
        answer["evidence_spans"]["rarity"] = "SAR"
        with self.assertRaisesRegex(ValueError, "rarity evidence"):
            validate_answer(answer, question)
        answer["facts"]["identity_tokens"]["rarity"] = "UR"
        answer["evidence_spans"]["rarity"] = "MUR"
        with self.assertRaisesRegex(ValueError, "rarity evidence"):
            validate_answer(answer, question)

    def test_failed_model_response_records_stage_without_raw_text(self):
        question = {"id": "example", "question": "Is this Pikachu real?",
                    "question_sha256": "a" * 64, "language": "en",
                    "media_state": "text_only"}
        incomplete = {"candidates": [{"finishReason": "MAX_TOKENS"}]}
        invalid = {"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": json.dumps({"facts": {}})}]}}], "modelVersion": "test-model"}
        with patch("scripts.vertex_public_question_facts_v3._call_model",
                   side_effect=[incomplete, invalid]):
            result = _extract_one(question, "project", "global", "token")
        self.assertEqual(result["status"], "error")
        self.assertEqual([error["stage"] for error in result["attempt_errors"]],
                         ["candidate", "facts_and_evidence"])
        self.assertEqual(result["attempt_errors"][1]["validation_code"],
                         "unexpected answer fields")
        self.assertNotIn("raw_response", result)
        self.assertNotIn("question", result)


if __name__ == "__main__":
    unittest.main()

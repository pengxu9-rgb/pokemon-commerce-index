import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from pokemon_index import question_routing_v2 as routing
from scripts.public_question_facts_v2 import merge
from scripts.public_question_sandbox import read_jsonl, sha_file, write_jsonl
from scripts.public_question_sandbox_v2 import freeze_new
from scripts.vertex_public_question_facts_v2 import _request
from scripts import vertex_public_question_facts_v2 as extractor
from scripts.vertex_concept_review import _call_model


def facts(*, goal="price_comparison", names=None, media="none", merchant=None):
    return {"object_type": "single_card", "primary_goal": goal,
            "transaction_context": "prospective_buy",
            "identity_tokens": {"card_names": [] if names is None else names,
                                "set_name": None, "collector_number": None,
                                "language": None, "finish": None, "grade": None},
            "media_state": media, "language_mentions": [],
            "merchant_ref": merchant, "destination": None}


class PublicQuestionFactsV2Tests(unittest.TestCase):
    def test_vertex_retries_transient_connection_failure(self):
        with patch("scripts.vertex_concept_review._get_json",
                   side_effect=[URLError("temporary EOF"), {"candidates": []}]) as request:
            with patch("scripts.vertex_concept_review.time.sleep"):
                self.assertEqual(_call_model("project", "global", "token", {}),
                                 {"candidates": []})
        self.assertEqual(request.call_count, 2)

    def test_v6_archive_preserves_source_gate_and_failed_reviews(self):
        root = Path(__file__).resolve().parents[1] / "sandbox/public_questions/v6"
        manifest = json.loads((root / "manifest.json").read_text())
        preflight = json.loads((root / "preflight_report.json").read_text())
        report = json.loads((root / "facts_report.json").read_text())
        self.assertEqual((preflight["candidates"], preflight["accepted"],
                          preflight["rejected"]), (12, 11, 1))
        self.assertEqual(manifest["preflight_report_sha256"],
                         sha_file(root / "preflight_report.json"))
        self.assertEqual(manifest["planner_sha256"], sha_file(Path(routing.__file__)))
        self.assertEqual(manifest["v2_fact_extractor_sha256"],
                         sha_file(Path(extractor.__file__)))
        self.assertEqual(report["manifest_sha256"], sha_file(root / "manifest.json"))
        self.assertEqual((report["questions"], report["jointly_reviewed"],
                          report["deterministic_plan_agreement"]), (11, 8, 7))
        self.assertEqual(report["status_counts"],
                         {"disputed": 6, "review_failed": 3, "silver_agreed": 2})
        self.assertEqual({row["id"] for row in read_jsonl(root / "plan_trace.jsonl")},
                         {row["id"] for row in read_jsonl(root / "blind_questions.jsonl")})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = self.root / "source.jsonl"
        prior = self.root / "prior.jsonl"
        row = {"id": "new", "question": "Is this Pikachu listing worth buying?",
               "source_url": "https://www.elitefourum.com/t/new/34567",
               "source_platform": "elitefourum", "language": "en",
               "selection_bucket": "buyer_price", "media_state": "referenced_not_collected",
               "observed_date": "2026-09-29", "text_form": "source_condensed"}
        write_jsonl(source, [row])
        write_jsonl(prior, [dict(row, id="old",
                                 source_url="https://www.elitefourum.com/t/old/34566")])
        self.frozen = self.root / "frozen"
        freeze_new(source, prior, self.frozen)
        manifest_path = self.frozen / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["planner_sha256"] = sha_file(Path(routing.__file__))
        manifest["v2_fact_extractor_sha256"] = sha_file(Path(extractor.__file__))
        manifest_path.write_text(json.dumps(manifest))
        self.q = read_jsonl(self.frozen / "blind_questions.jsonl")[0]

    def tearDown(self):
        self.temp.cleanup()

    def review(self, family, item_facts):
        return {"id": self.q["id"], "question_sha256": self.q["question_sha256"],
                "model_family": family, "status": "ok", "facts": item_facts}

    def test_prompt_carries_absent_image_and_no_unique_printing(self):
        request, prompt_hash = _request(self.q)
        prompt = request["contents"][0]["parts"][0]["text"]
        self.assertIn("media_state: use referenced_not_collected", prompt)
        self.assertIn("do not", prompt.lower())
        self.assertEqual(len(prompt_hash), 64)

    def test_merge_separates_fact_dispute_from_plan_agreement(self):
        left = facts(names=["Pikachu"], media="referenced_not_collected")
        right = facts(names=["Pikachu"], media="referenced_not_collected",
                      merchant="seller123")
        a, g = self.root / "a.jsonl", self.root / "g.jsonl"
        write_jsonl(a, [self.review("astra", left)])
        write_jsonl(g, [self.review("google", right)])
        report = merge(self.frozen, a, g, self.root / "report.json")
        self.assertEqual(report["status_counts"], {"disputed": 1})
        self.assertEqual(report["field_agreement"]["merchant_ref"], 0)
        self.assertEqual(report["deterministic_plan_agreement"], 1)
        self.assertEqual(report["by_language"]["en"]["questions"], 1)

    def test_merge_rejects_unavailable_image_and_changed_code_lock(self):
        a, g = self.root / "a.jsonl", self.root / "g.jsonl"
        write_jsonl(a, [self.review("astra", facts(names=["Pikachu"], media="available"))])
        write_jsonl(g, [self.review("google", facts(names=["Pikachu"],
                                                   media="referenced_not_collected"))])
        with self.assertRaisesRegex(ValueError, "unavailable media"):
            merge(self.frozen, a, g, self.root / "bad.json")
        manifest_path = self.frozen / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["v2_fact_extractor_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "differs from manifest"):
            merge(self.frozen, a, g, self.root / "changed.json")


if __name__ == "__main__":
    unittest.main()

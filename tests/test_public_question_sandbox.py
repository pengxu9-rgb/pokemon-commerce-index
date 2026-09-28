import json
import tempfile
import unittest
from pathlib import Path

from scripts.public_question_sandbox import (freeze, merge, question_sha,
                                             read_jsonl, write_jsonl)
from scripts.vertex_public_question_review import _request


def source_row(item_id, bucket, language="en"):
    host = "www.reddit.com" if language == "en" else "detail.chiebukuro.yahoo.co.jp"
    return {"id": item_id, "question": f"How should I identify this Pokémon card {item_id}?",
            "source_url": f"https://{host}/questions/{item_id}",
            "source_platform": "reddit" if language == "en" else "yahoo_chiebukuro",
            "language": language, "selection_bucket": bucket,
            "media_state": "referenced_not_collected", "observed_date": "2026-09-29",
            "text_form": "source_condensed"}


LABEL = {"actor": "buyer", "primary_intent": "identify_card",
         "identity_state": "needs_photo", "next_action": "ask_photos",
         "required_evidence": ["card_photos", "card_metadata"],
         "forbidden_claims": ["exact_card", "price"]}


class PublicQuestionSandboxTests(unittest.TestCase):
    def test_freeze_and_merge_keep_disputes_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            rows = [source_row("a", "buyer_identity"),
                    source_row("b", "buyer_identity"),
                    source_row("c", "seller_price", "ja"),
                    source_row("d", "seller_price", "ja")]
            write_jsonl(source, rows)
            frozen = root / "frozen"
            manifest = freeze(source, frozen, seed=5)
            self.assertEqual((manifest["questions"], manifest["holdout"]), (4, 2))
            blind = read_jsonl(frozen / "blind_questions.jsonl")
            self.assertEqual(set(blind[0]), {"id", "question", "language", "media_state",
                                             "question_sha256"})
            self.assertEqual(blind[0]["question_sha256"], question_sha(rows[0]))
            request, _ = _request(blind[0])
            self.assertNotIn("source_url", json.dumps(request))
            astra, gemini = [], []
            for row in blind:
                base = {"id": row["id"], "question_sha256": row["question_sha256"],
                        "status": "ok", "label": dict(LABEL)}
                astra.append(dict(base, model_family="astra"))
                gemini.append(dict(base, model_family="google"))
            gemini[0]["label"] = dict(LABEL,
                                      required_evidence=list(reversed(LABEL["required_evidence"])),
                                      forbidden_claims=list(reversed(LABEL["forbidden_claims"])))
            gemini[1]["label"] = dict(LABEL, primary_intent="identify_variant")
            gemini[2]["status"], gemini[2]["label"] = "error", None
            a_path, g_path = root / "a.jsonl", root / "g.jsonl"
            write_jsonl(a_path, astra)
            write_jsonl(g_path, gemini)
            report = merge(frozen, a_path, g_path, root / "report.json")
            self.assertEqual(report["status_counts"], {
                "disputed": 1, "review_failed": 1, "silver_agreed": 2})
            self.assertEqual(report["jointly_reviewed"], 3)
            self.assertEqual(report["field_agreement"]["required_evidence"], 3)
            self.assertEqual(report["field_agreement"]["forbidden_claims"], 3)
            self.assertEqual(report["field_agreement"]["primary_intent"], 2)
            self.assertEqual(len(report["results"]), 4)

    def test_freeze_rejects_duplicate_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            row = source_row("a", "buyer_identity")
            write_jsonl(source, [row, dict(row, id="b")])
            with self.assertRaisesRegex(ValueError, "source URLs must be unique"):
                freeze(source, root / "frozen")


if __name__ == "__main__":
    unittest.main()

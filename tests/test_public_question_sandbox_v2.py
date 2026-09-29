import tempfile
import unittest
import json
from pathlib import Path

from scripts.public_question_sandbox import read_jsonl, write_jsonl
from scripts.public_question_sandbox_v2 import freeze_new, merge, validate_label
from scripts.evaluate_public_question_replay import evaluate
from scripts.public_question_fidelity import summarize
from scripts.public_question_sandbox import sha_file
from scripts.vertex_public_question_review_v2 import _request


def row(item_id):
    return {"id": item_id,
            "question": f"How should I value this Japanese Pokémon card {item_id}?",
            "source_url": f"https://www.reddit.com/r/PokemonTCG/comments/{item_id}",
            "source_platform": "reddit", "language": "en",
            "selection_bucket": "seller_price", "media_state": "text_only",
            "observed_date": "2026-09-29", "text_form": "source_condensed"}


LABEL = {"actor": "seller", "object_type": "card_single",
         "primary_intent": "seller_pricing", "identity_state": "ambiguous",
         "next_action": "ask_context", "missing_context": ["card_identity"],
         "blocking_evidence": ["verified_sales", "card_metadata"],
         "optional_evidence": ["authorized_live_offers"],
         "forbidden_claims": ["price", "paid_sale"]}


class PublicQuestionSandboxV2Tests(unittest.TestCase):
    def test_freeze_new_and_merge_set_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior, source = root / "prior.jsonl", root / "source.jsonl"
            write_jsonl(prior, [row("old")])
            write_jsonl(source, [row("new1"), row("new2")])
            frozen = root / "frozen"
            manifest = freeze_new(source, prior, frozen)
            self.assertEqual(manifest["questions"], 2)
            self.assertEqual(manifest["new_source_posts_vs_prior"], 2)
            blind = read_jsonl(frozen / "blind_questions.jsonl")
            prompt, _ = _request(blind[0])
            self.assertNotIn("source_url", str(prompt))
            astra, google = [], []
            for question in blind:
                base = {"id": question["id"],
                        "question_sha256": question["question_sha256"],
                        "status": "ok", "label": dict(LABEL)}
                astra.append(dict(base, model_family="astra"))
                google.append(dict(base, model_family="google"))
            google[0]["label"] = dict(LABEL,
                                       blocking_evidence=list(reversed(LABEL["blocking_evidence"])),
                                       forbidden_claims=list(reversed(LABEL["forbidden_claims"])))
            google[1]["label"] = dict(LABEL, next_action="retrieve_evidence",
                                       missing_context=[])
            a_path, g_path = root / "astra.jsonl", root / "google.jsonl"
            write_jsonl(a_path, astra)
            write_jsonl(g_path, google)
            report = merge(frozen, a_path, g_path, root / "report.json")
            self.assertEqual(report["status_counts"], {"disputed": 1,
                                                       "silver_agreed": 1})
            self.assertEqual(report["field_agreement"]["forbidden_claims"], 2)
            self.assertEqual(report["core_routing_agreement"], 1)
            predictions = [{"id": question["id"],
                            "question_sha256": question["question_sha256"],
                            "status": "routed",
                            "route": {key: LABEL[key] for key in (
                                "actor", "object_type", "primary_intent",
                                "identity_state", "next_action")},
                            "selected_card_id": "invented-id"}
                           for question in blind]
            p_path = root / "predictions.jsonl"
            write_jsonl(p_path, predictions)
            replay = evaluate(frozen, a_path, g_path, p_path)
            self.assertEqual(replay["question_count"], 2)
            self.assertEqual(sum(part["possible_premature_card_selections"]
                                 for part in replay["by_split"].values()), 2)
            self.assertEqual(sum(part["fields"]["primary_intent"]["matched"]
                                 for part in replay["by_split"].values()), 2)
            audit_path = root / "audit.json"
            audit_path.write_text(json.dumps({
                "schema": "pokemon.public-question-source-fidelity.v1",
                "source_sha256": sha_file(source),
                "items": [{"id": "new1", "status": "faithful", "reason": "direct question"},
                          {"id": "new2", "status": "mismatch", "reason": "wrong object"}]}))
            fidelity = summarize(source, audit_path, root / "report.json")
            self.assertEqual(fidelity["fidelity_counts"], {
                "faithful": 1, "mismatch": 1})
            self.assertEqual(fidelity["flagged_ids"], ["new2"])

    def test_prior_source_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior, source = root / "prior.jsonl", root / "source.jsonl"
            write_jsonl(prior, [row("same")])
            write_jsonl(source, [row("same")])
            with self.assertRaisesRegex(ValueError, "reuses"):
                freeze_new(source, prior, root / "frozen")

    def test_action_coherence(self):
        with self.assertRaisesRegex(ValueError, "requires"):
            validate_label(dict(LABEL, next_action="ask_photos", missing_context=[]))
        with self.assertRaisesRegex(ValueError, "only reported"):
            validate_label(dict(LABEL, next_action="general_explanation"))


if __name__ == "__main__":
    unittest.main()

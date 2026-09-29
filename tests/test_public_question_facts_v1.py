import json
import tempfile
import unittest
from pathlib import Path

from scripts.public_question_facts_v1 import merge
from scripts.public_question_sandbox import read_jsonl, sha_file, write_jsonl
from scripts.public_question_sandbox_v2 import freeze_new


FACTS = {"product_scope": "tcg_single", "focus": "grading_decision",
         "named_card": False, "exact_printing": False,
         "specific_copy": True, "photos_available": False,
         "language_scope": "unspecified"}


class QuestionFactsTests(unittest.TestCase):
    def test_v4_archive_is_bound_to_preflight(self):
        root = Path(__file__).resolve().parents[1] / "sandbox/public_questions/v4"
        report = json.loads((root / "preflight_report.json").read_text())
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual((report["candidates"], report["accepted"]), (8, 8))
        self.assertEqual(sha_file(root / "candidates.jsonl"), report["candidate_sha256"])
        self.assertEqual(sha_file(root / "source_evidence.jsonl"), report["evidence_sha256"])
        self.assertEqual(sha_file(root / "preflight_report.json"),
                         manifest["preflight_report_sha256"])
        self.assertEqual({row["id"] for row in read_jsonl(root / "blind_questions.jsonl")},
                         {row["id"] for row in read_jsonl(root / "eligible_source_questions.jsonl")})

    def test_fact_merge_reports_plan_agreement_even_with_noncritical_dispute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = {"id": "sample", "question": "Should I grade this card?",
                   "source_url": "https://www.elitefourum.com/t/sample/12345",
                   "source_platform": "elitefourum", "language": "en",
                   "selection_bucket": "seller_grading", "media_state": "text_only",
                   "observed_date": "2026-09-29", "text_form": "source_condensed"}
            prior = dict(row, id="prior", source_url="https://www.elitefourum.com/t/prior/12346")
            source, old = root / "source.jsonl", root / "prior.jsonl"
            write_jsonl(source, [row]); write_jsonl(old, [prior])
            frozen = root / "frozen"
            freeze_new(source, old, frozen)
            q = read_jsonl(frozen / "blind_questions.jsonl")[0]
            a = {"id": q["id"], "question_sha256": q["question_sha256"],
                 "model_family": "astra", "status": "ok", "facts": FACTS}
            g = dict(a, model_family="google",
                     facts=dict(FACTS, named_card=True))
            a_path, g_path = root / "astra.jsonl", root / "google.jsonl"
            write_jsonl(a_path, [a]); write_jsonl(g_path, [g])
            report = merge(frozen, a_path, g_path, root / "report.json")
            self.assertEqual(report["status_counts"], {"disputed": 1})
            self.assertEqual(report["field_agreement"]["named_card"], 0)
            self.assertEqual(report["deterministic_plan_agreement"], 1)
            manifest_path = frozen / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["planner_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "frozen cohort"):
                merge(frozen, a_path, g_path, root / "locked-report.json")

    def test_v5_archive_keeps_rejected_source_and_locked_report(self):
        root = Path(__file__).resolve().parents[1] / "sandbox/public_questions/v5"
        preflight = json.loads((root / "preflight_report.json").read_text())
        manifest = json.loads((root / "manifest.json").read_text())
        report = json.loads((root / "facts_report.json").read_text())
        self.assertEqual((preflight["candidates"], preflight["accepted"],
                          preflight["rejected"]), (12, 11, 1))
        self.assertEqual(manifest["preflight_report_sha256"],
                         sha_file(root / "preflight_report.json"))
        self.assertEqual(manifest["source_sha256"],
                         sha_file(root / "eligible_source_questions.jsonl"))
        self.assertEqual(report["manifest_sha256"], sha_file(root / "manifest.json"))
        self.assertEqual(report["planner_sha256"], manifest["planner_sha256"])
        self.assertEqual((report["questions"], report["jointly_reviewed"],
                          report["deterministic_plan_agreement"]), (11, 11, 5))
        self.assertEqual(report["status_counts"], {"disputed": 9, "silver_agreed": 2})
        self.assertEqual({row["id"] for row in read_jsonl(root / "plan_trace.jsonl")},
                         {row["id"] for row in read_jsonl(root / "blind_questions.jsonl")})


if __name__ == "__main__":
    unittest.main()

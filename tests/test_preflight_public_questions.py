import json
import tempfile
import unittest
from pathlib import Path

from scripts.preflight_public_questions import preflight
from scripts.public_question_sandbox import read_jsonl, sha_file, write_jsonl


def source(item_id):
    return {"id": item_id, "question": f"How should I identify card {item_id}?",
            "source_url": f"https://www.elitefourum.com/t/example/{item_id}",
            "source_platform": "elitefourum", "language": "en",
            "selection_bucket": "buyer_identity", "media_state": "text_only",
            "observed_date": "2026-09-29", "text_form": "source_condensed"}


class PreflightTests(unittest.TestCase):
    def test_archived_v3_denominator_and_hashes(self):
        root = Path(__file__).resolve().parents[1] / "sandbox/public_questions/v3"
        report = json.loads((root / "preflight_report.json").read_text())
        manifest = json.loads((root / "manifest.json").read_text())
        self.assertEqual((report["candidates"], report["accepted"], report["rejected"]),
                         (10, 9, 1))
        self.assertEqual(sha_file(root / "candidates.jsonl"), report["candidate_sha256"])
        self.assertEqual(sha_file(root / "source_evidence.jsonl"), report["evidence_sha256"])
        self.assertEqual(sha_file(root / "eligible_source_questions.jsonl"),
                         report["eligible_sha256"])
        self.assertEqual(sha_file(root / "preflight_report.json"),
                         manifest["preflight_report_sha256"])
        self.assertEqual({row["id"] for row in read_jsonl(root / "blind_questions.jsonl")},
                         {row["id"] for row in read_jsonl(root / "eligible_source_questions.jsonl")})

    def test_gate_keeps_rejected_candidate_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidates = [source("good"), source("title")]
            source_path, evidence_path = root / "source.jsonl", root / "evidence.jsonl"
            write_jsonl(source_path, candidates)
            write_jsonl(evidence_path, [{"id": row["id"],
                "source_url": row["source_url"], "post_locator": "post #1",
                "anchor": "How should I identify this card?",
                "source_context": "The original poster asks how to identify the card and provides no photos.",
                "verification_method": "title_only" if row["id"] == "title" else "opened_post",
                "observed_date": "2026-09-29"} for row in candidates])
            paths = []
            for family in ("astra", "google"):
                path = root / f"{family}.jsonl"
                write_jsonl(path, [{"id": row["id"], "model_family": family,
                    "source_sha256": sha_file(source_path),
                    "evidence_sha256": sha_file(evidence_path),
                    "status": "faithful", "reason": "Preserves the source question."}
                    for row in candidates])
                paths.append(path)
            report = preflight(source_path, evidence_path, *paths, [], root / "out")
            self.assertEqual((report["candidates"], report["accepted"], report["rejected"]),
                             (2, 1, 1))
            eligible = (root / "out" / "eligible_source_questions.jsonl").read_text()
            self.assertIn('"good"', eligible)
            self.assertNotIn('"title"', eligible)
            # Audits are invalidated if source wording changes after review.
            candidates[0]["question"] = "Which seller should I trust?"
            write_jsonl(source_path, candidates)
            with self.assertRaisesRegex(ValueError, "invalid astra audit"):
                preflight(source_path, evidence_path, *paths, [], root / "changed")


if __name__ == "__main__":
    unittest.main()

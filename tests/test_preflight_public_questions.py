import json
import tempfile
import unittest
from pathlib import Path

from scripts.preflight_public_questions import preflight, source_post_key
from scripts.public_question_sandbox import read_jsonl, sha_file, write_jsonl


def source(item_id):
    return {"id": item_id, "question": f"How should I identify card {item_id}?",
            "source_url": f"https://www.elitefourum.com/t/example/{item_id}",
            "source_platform": "elitefourum", "language": "en",
            "selection_bucket": "buyer_identity", "media_state": "text_only",
            "observed_date": "2026-09-29", "text_form": "source_condensed"}


class PreflightTests(unittest.TestCase):
    def test_post_ids_ignore_slugs_and_host_aliases(self):
        urls=['https://www.reddit.com/r/PokemonTCG/comments/abc123/old_title/',
              'https://old.reddit.com/r/Other/comments/abc123/new_title/?x=1',
              'https://redd.it/abc123']
        self.assertEqual(len({source_post_key(u) for u in urls}),1)
        self.assertEqual(source_post_key('https://www.elitefourum.com/t/old/123/2'),
                         source_post_key('https://elitefourum.com/t/new/123'))

    def test_prior_post_overlap_cannot_hide_behind_a_changed_slug(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);a=source('one');b=source('two')
            a['source_url']='https://www.reddit.com/r/PokemonTCG/comments/abc123/a/'
            b['source_url']='https://www.reddit.com/r/Other/comments/abc123/b/'
            write_jsonl(root/'prior.jsonl',[a]);write_jsonl(root/'new.jsonl',[b])
            with self.assertRaisesRegex(ValueError,'reuses a prior source'):
                preflight(root/'new.jsonl',root/'absent',root/'absent',root/'absent',
                          [root/'prior.jsonl'],root/'out')

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

    def test_first_review_is_attributed_to_actual_reviewer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = source("codex")
            source_path, evidence_path = root / "source.jsonl", root / "evidence.jsonl"
            write_jsonl(source_path, [candidate])
            write_jsonl(evidence_path, [{"id": "codex", "source_url": candidate["source_url"],
                "post_locator": "opening post", "anchor": "identify card",
                "source_context": "The opening post asks how to identify a card and supplies no photo.",
                "verification_method": "opened_post", "observed_date": "2026-09-29"}])
            paths = []
            for family in ("codex", "google"):
                path = root / f"{family}.jsonl"
                write_jsonl(path, [{"id": "codex", "model_family": family,
                    "source_sha256": sha_file(source_path),
                    "evidence_sha256": sha_file(evidence_path),
                    "status": "faithful", "reason": "Same source question."}])
                paths.append(path)
            report = preflight(source_path, evidence_path, *paths, [], root / "out",
                               first_review_family="codex")
            self.assertEqual(report["codex_sha256"], sha_file(paths[0]))
            self.assertNotIn("astra_sha256", report)
            self.assertEqual(report["decisions"][0]["codex_status"], "faithful")


if __name__ == "__main__":
    unittest.main()

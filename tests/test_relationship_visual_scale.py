import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_relationship_visual_scale import _batch, _merge
from scripts.vertex_relationship_artwork_triage import FIELDS


class RelationshipVisualScaleTests(unittest.TestCase):
    def test_merge_blocks_unconfirmed_english_image_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            queue = [{"candidate_id": "a", "source_snapshot_sha256": "1" * 64}]
            chunks = _batch(queue, work, 1)
            row = {"candidate_id": "a", "source_snapshot_sha256": "1" * 64,
                   "artwork_decision": "same", "rationale": "same composition",
                   "evidence_limits": "finish unverified",
                   "ja_image_status": "included", "en_image_status": "included",
                   "en_image_identity": "uncertain"}
            with (work / "chunk-000-results.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow(row)
            detail = {"candidate_id": "a", "source_snapshot_sha256": "1" * 64,
                      "model_version": "gemini-3.8-flash", "response_sha256": "2" * 64}
            (work / "chunk-000-audit.json").write_text(json.dumps({
                "rows": [detail], "candidate_rows": 1, "model": "gemini-3.8-flash",
                "project": "test", "location": "global",
                "prompt_version": "vertex-card-artwork-triage-v1",
                "pinned_revision": "revision"}))
            report = _merge(queue, chunks, work, work / "merged.csv",
                            work / "merged-audit.json")
            self.assertEqual(report["decisions"], {"uncertain": 1})
            self.assertEqual(report["rows"][0]["identity_gate_original_decision"], "same")
            with (work / "merged.csv").open(newline="") as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["artwork_decision"],
                                 "uncertain")

    def test_frozen_chunk_cannot_be_reused_for_different_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            _batch([{"candidate_id": "a"}], work, 1)
            with self.assertRaisesRegex(ValueError, "frozen chunk changed"):
                _batch([{"candidate_id": "b"}], work, 1)


if __name__ == "__main__":
    unittest.main()

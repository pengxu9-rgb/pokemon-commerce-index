"""The deployed catalog must match its pinned source manifest."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_catalog_snapshot import build

ROOT = Path(__file__).resolve().parents[1]


class CatalogBuildManifestTests(unittest.TestCase):
    def test_rebuilds_documented_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.sqlite3"
            result = build(ROOT / "catalog-build-manifest.json", output)
            self.assertEqual((result["printings"], result["match_eligible"]),
                             (55167, 33543))
            db = sqlite3.connect(f"file:{output}?mode=ro", uri=True)
            try:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM card_number_conflict_rule").fetchone()[0], 2)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM card_identity_exception").fetchone()[0], 19)
                self.assertEqual(db.execute(
                    "SELECT match_eligible FROM card WHERE card_id='ja:SV11B:001/174:normal'"
                ).fetchone()[0], 0)
            finally:
                db.close()

    def test_manifest_hash_mismatch_fails_before_writing(self):
        manifest = ROOT / "catalog-build-manifest.json"
        with tempfile.TemporaryDirectory() as directory:
            data = json.loads(manifest.read_text())
            data["steps"][0]["sha256"] = "0" * 64
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", dir=ROOT,
                                             delete=False) as temporary:
                copied = Path(temporary.name)
                temporary.write(json.dumps(data))
            output = Path(directory) / "catalog.sqlite3"
            try:
                with self.assertRaisesRegex(ValueError, "hash changed"):
                    build(copied, output)
                self.assertFalse(output.exists())
            finally:
                copied.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

"""The deployed catalog must match its pinned source manifest."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from pokemon_index import discovery_graph
from scripts.build_catalog_snapshot import build, import_ai_artwork_proposals

ROOT = Path(__file__).resolve().parents[1]


class CatalogBuildManifestTests(unittest.TestCase):
    def test_rebuilds_documented_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.sqlite3"
            result = build(ROOT / "catalog-build-manifest.json", output)
            self.assertEqual((result["printings"], result["match_eligible"]),
                             (55167, 33543))
            self.assertEqual((result["ai_artwork_proposals"], result["verified_relationships"]),
                             (657, 0))
            db = sqlite3.connect(f"file:{output}?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            try:
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM card_number_conflict_rule").fetchone()[0], 2)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM card_identity_exception").fetchone()[0], 19)
                self.assertEqual(db.execute(
                    "SELECT match_eligible FROM card WHERE card_id='ja:SV11B:001/174:normal'"
                ).fetchone()[0], 0)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'"
                ).fetchone()[0], 0)
                neighborhood = discovery_graph.card_neighborhood(db, "ja:M-P:046/M-P:normal")
                self.assertEqual(neighborhood["relationships"], [])
                self.assertTrue(neighborhood["ai_artwork_candidates"])
                self.assertTrue(all(not edge["price_comparable"] for edge in
                                    neighborhood["ai_artwork_candidates"]))
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

    def test_proposal_import_cannot_smuggle_verified_edge(self):
        with self.assertRaisesRegex(ValueError, "must remain AI proposals"):
            import_ai_artwork_proposals(None, [{"relation_type": "same_artwork",
                                                "review_status": "verified",
                                                "asserted_by": "ai-artwork-review-v1"}])


if __name__ == "__main__":
    unittest.main()

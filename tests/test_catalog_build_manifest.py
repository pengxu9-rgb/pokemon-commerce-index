"""The deployed catalog must match its pinned source manifest."""

import json
import sqlite3
import tempfile
import unittest
import hashlib
from unittest.mock import patch
from pathlib import Path

from pokemon_index import discovery_graph
from scripts.build_catalog_snapshot import build, import_ai_artwork_proposals,OPERATIONS

ROOT = Path(__file__).resolve().parents[1]


class CatalogBuildManifestTests(unittest.TestCase):
    def test_input_changed_during_ingestion_does_not_publish_mixed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'seed.jsonl';source.write_text('{}\n')
            manifest=root/'manifest.json';output=root/'catalog.sqlite3'
            expected={key:0 for key in ('printings','sets','match_eligible','display_approved','reference_records',
                'identity_exceptions','number_conflict_rules','relationship_assertions','verified_relationships','ai_artwork_proposals')}
            manifest.write_text(json.dumps(dict(schema='pokemon.catalog-build.v1',steps=[dict(operation='import-sets',
                path='seed.jsonl',sha256=hashlib.sha256(source.read_bytes()).hexdigest())],expected=expected)))
            def change_source(db,rows):
                list(rows);source.write_text('{"changed":true}\n');return 0
            with patch.dict(OPERATIONS,{'import-sets':change_source}):
                with self.assertRaisesRegex(ValueError,'input changed during build'):
                    build(manifest,output)
            self.assertFalse(output.exists())

    def test_second_japanese_cohort_is_disjoint_and_preserves_evidence_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'metadata-v2.sqlite3'
            result=build(ROOT/'catalog-build-manifest-metadata-v2.json',output)
            self.assertEqual((result['current_official_metadata_cards'],result['official_known_rarity_cards']), (2497,1900))
            self.assertEqual((result['match_eligible'],result['current_supported_targets']), (33543,100))
            first=[json.loads(l) for l in (ROOT/'catalog/japanese-evidence-next-v1/metadata-evidence-v1.jsonl').read_text().splitlines()]
            second=[json.loads(l) for l in (ROOT/'catalog/japanese-evidence-expansion-v2/metadata-evidence-v1.jsonl').read_text().splitlines()]
            self.assertFalse({r['card_id'] for r in first}&{r['card_id'] for r in second})
            with sqlite3.connect(output) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM active_card_metadata_evidence e JOIN supported_card s ON e.card_id=s.card_id').fetchone()[0],0)
                self.assertTrue(all(db.execute('SELECT evidence_id FROM card_metadata_evidence WHERE card_id=?',(r['card_id'],)).fetchone()[0]==r['evidence_id'] for r in first))
                for cid in ['ja:SV-P:111/SV-P:normal','ja:SV-P:198/SV-P:normal','ja:SV8:012/106:normal']:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE card_id=? AND facet_type='illustrator'",(cid,)).fetchone()[0],0)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM observation').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT SUM(display_allowed) FROM card').fetchone()[0],0)

    def test_japanese_metadata_batch_preserves_printing_and_offer_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'metadata.sqlite3'
            result=build(ROOT/'catalog-build-manifest-metadata-v1.json',output)
            self.assertEqual((result['current_official_metadata_cards'],result['official_known_rarity_cards']), (1000,749))
            self.assertEqual((result['match_eligible'],result['current_supported_targets']), (33543,100))
            with sqlite3.connect(output) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM active_card_metadata_evidence e JOIN supported_card s ON e.card_id=s.card_id').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE card_id='ja:M-P:046/M-P:normal' AND facet_type='illustrator'").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE card_id='ja:M6A:151/103:holo'").fetchone()[0],0)
                self.assertEqual(db.execute("SELECT match_eligible FROM card WHERE card_id='ja:SV11B:001/174:normal'").fetchone()[0],0)

    def test_coverage_expansion_keeps_source_versions_out_of_commerce(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "expanded.sqlite3"
            result = build(ROOT / "catalog-build-manifest-coverage-v1.json", output)
            self.assertEqual((result["printings"], result["match_eligible"]), (70005, 33543))
            db = sqlite3.connect(f"file:{output}?mode=ro", uri=True)
            try:
                self.assertEqual(db.execute("""SELECT COUNT(*),SUM(match_eligible),SUM(display_allowed)
                    FROM card WHERE json_extract(attributes_json,'$.expansion_batch')='english-history-v1'""").fetchone(), (14838, 0, 0))
                self.assertEqual(db.execute("SELECT name FROM card WHERE card_id='en:2011BW:001/012:holo'").fetchone()[0], "Snivy")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM card_facet WHERE card_id='en:2011BW:001/012:holo'").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0], 0)
                self.assertEqual(result["current_supported_targets"], 100)
            finally:
                db.close()

    def test_rebuilds_documented_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.sqlite3"
            result = build(ROOT / "catalog-build-manifest-discovery-v1.json", output)
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
        manifest = ROOT / "catalog-build-manifest-discovery-v1.json"
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

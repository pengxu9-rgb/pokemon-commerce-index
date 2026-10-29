import hashlib
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import sys
from unittest.mock import patch

from pokemon_index.cohort_coverage import generate, main, sha256


class CohortReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "catalog.sqlite3"
        c = sqlite3.connect(self.db)
        c.execute("CREATE TABLE card(card_id TEXT PRIMARY KEY,language TEXT,set_code TEXT,collector_number TEXT,variant TEXT,name TEXT,provenance TEXT,match_eligible INTEGER,display_allowed INTEGER)")
        c.execute("INSERT INTO card VALUES (?,?,?,?,?,?,?,?,?)", ("ja:S:001/100:holo", "ja", "S", "001/100", "holo", "Example", "pinned-source", 1, 0))
        c.commit(); c.close()
        (self.root / "usage.json").write_text(json.dumps({"card_id": "ja:S:001/100:holo"}))
        self.entry = {"card_id": "ja:S:001/100:holo", "identity": {"language": "ja", "set_code": "S", "collector_number": "001/100", "variant": "holo", "name": "Example"},
                      "catalog_provenance_sha256": hashlib.sha256(b"pinned-source").hexdigest(),
                      "selection_evidence": [{"path": "usage.json", "sha256": sha256(self.root / "usage.json"), "json_pointer": "/card_id", "expected_value": "ja:S:001/100:holo"}]}
        self.cohort = self.root / "cohort.json"
        self.save_cohort([self.entry])

    def tearDown(self):
        self.temp.cleanup()

    def save_cohort(self, entries):
        self.cohort.write_text(json.dumps({"schema": "pot.focused-card-cohort.v1", "id": "test", "basis": "retained_acceptance_test", "entries": entries}))

    def report(self, **overrides):
        kw = dict(database=self.db, expected_database_sha256=sha256(self.db), cohort_path=self.cohort, workspace=self.root,
                  primary_reader=lambda db, cid: {"status": "current", "current_endpoint": True, "basis": "catalog_source_reference", "source_ref": "https://images.invalid/reference.png"},
                  scan_reader=lambda db, cid: {"status": "missing_source_scan_evidence"})
        kw.update(overrides)
        return generate(**kw)

    def test_current_reference_is_not_image_delivery_inventory_or_offer_authorization(self):
        before = sha256(self.db)
        report = self.report()
        self.assertEqual(report["summary"]["primary_images_current"], 1)
        self.assertEqual(report["summary"]["ready_for_live_comparison"], 0)
        self.assertIsNone(report["rows"][0]["offers"]["active_listing_count"])
        self.assertEqual(report["rows"][0]["offers"]["input_status"], "not_supplied")
        self.assertFalse(any(report["rows"][0]["claims"].values()))
        self.assertIn("actual_seller_photos_not_supplied", report["rows"][0]["gaps"])
        self.assertEqual(before, sha256(self.db))
        self.assertEqual(report["safeguards"]["network_calls"], 0)

    def test_missing_stale_and_held_references_never_count_as_current(self):
        for status in ["missing", "stale", "held"]:
            report = self.report(primary_reader=lambda db, cid: {"status": status, "current_endpoint": status == "held"})
            self.assertEqual(report["summary"]["primary_images_current"], 0)
            self.assertIn("primary_image_" + status, report["rows"][0]["gaps"])

    def test_database_or_usage_evidence_changes_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "catalog checksum"):
            self.report(expected_database_sha256="0" * 64)
        (self.root / "usage.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "evidence checksum"):
            self.report()

    def test_exact_identity_and_provenance_changes_are_rejected(self):
        self.entry["identity"]["variant"] = "reverse_holo"
        self.save_cohort([self.entry])
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.report()
        self.entry["identity"]["variant"] = "holo"
        self.entry["catalog_provenance_sha256"] = "0" * 64
        self.save_cohort([self.entry])
        with self.assertRaisesRegex(ValueError, "provenance changed"):
            self.report()

    def test_duplicate_card_ids_and_escaped_evidence_paths_rejected(self):
        self.save_cohort([self.entry, self.entry])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.report()
        self.entry["selection_evidence"][0]["path"] = "../usage.json"
        self.save_cohort([self.entry])
        with self.assertRaisesRegex(ValueError, "within workspace"):
            self.report()

    def test_next_wave_remains_provisional_and_cannot_promote_alias_or_photo_status(self):
        wave = self.root / "wave.jsonl"
        row = {**self.entry["identity"], "card_id": self.entry["card_id"], "catalog_provenance_sha256": self.entry["catalog_provenance_sha256"],
               "selection_status": "provisional_coverage_sample", "search_query_status": "not_ready_marketplace_alias_required", "offer_matching_status": "photo_review_required"}
        wave.write_text(json.dumps(row) + "\n")
        report = self.report(next_wave_path=wave)
        self.assertFalse(report["next_wave"]["entries"][0]["ready_for_live_comparison"])
        self.assertEqual(report["next_wave"]["entries"][0]["search_query_status"], "not_ready_marketplace_alias_required")
        row["search_query_status"] = "approved"
        wave.write_text(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "status transition"):
            self.report(next_wave_path=wave)

    def test_cli_uses_pinned_snapshot_without_external_runtime_import_or_network(self):
        snapshot = self.root / 'decisions.json'
        snapshot.write_text(json.dumps({'schema': 'pokemon.catalog-primary-decisions.v1', 'database_sha256': sha256(self.db),
            'catalog_records': 1, 'producer': {'name': 'synthetic-reader', 'reader_code_sha256': 'c' * 64},
            'rows': [{'card_id': self.entry['card_id'], 'identity': self.entry['identity'],
                      'catalog_provenance_sha256': self.entry['catalog_provenance_sha256'],
                      'primary_image': {'status': 'current', 'basis': 'catalog_source_reference', 'current_endpoint': True,
                                        'event_id': 'catalog-source-image:' + 'a' * 64, 'image_sha256': 'b' * 64},
                      'source_scan': {'status': 'missing_source_scan_evidence', 'current_endpoint': False}}]}))
        output = self.root / 'report.json'
        argv = ['cohort_coverage', '--database', str(self.db), '--cohort', str(self.cohort), '--workspace', str(self.root),
                '--snapshot', str(snapshot), '--expected-database-sha256', sha256(self.db),
                '--expected-snapshot-sha256', sha256(snapshot), '--output', str(output)]
        with patch.object(sys, 'argv', argv), patch('socket.socket', side_effect=AssertionError('network forbidden')), \
                patch('importlib.import_module', side_effect=AssertionError('external runtime import forbidden')), redirect_stdout(io.StringIO()):
            main()
        result = json.loads(output.read_text())
        self.assertEqual(result['summary']['primary_images_current'], 1)
        self.assertFalse(result['reader_snapshot']['native_reader_decisions_revalidated'])
        self.assertEqual(result['reader_snapshot']['sha256'], sha256(snapshot))
        self.assertIsNone(result['rows'][0]['offers']['active_listing_count'])


if __name__ == "__main__":
    unittest.main()

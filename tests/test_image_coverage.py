import csv
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index.coverage_snapshot import load_snapshot, sha256, strict_json, validate_catalog
from pokemon_index.image_coverage import copy_inventory, copy_scope, main, validate_copy_summary

SCOPE = copy_scope('source-fixture-bucket', 'destination-fixture-bucket', 'fixture-v1')


class CopyEvidenceTest(unittest.TestCase):
    def files(self, root, rows, generations):
        csv_path = root / 'copy.csv'
        with csv_path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Source', 'Destination', 'Result', 'Source Size', 'Bytes Transferred'])
            writer.writeheader()
            writer.writerows(rows)
        gen_path = root / 'generations.jsonl'
        gen_path.write_text(''.join(json.dumps(x) + '\n' for x in generations))
        return csv_path, gen_path

    def row(self, key='a' * 64):
        name = SCOPE['prefix'] + key + '.raw'
        return {'Source': SCOPE['source'] + name + '#1', 'Destination': SCOPE['destination'] + name,
                'Result': 'OK', 'Source Size': '24', 'Bytes Transferred': '24'}

    def generation(self, key='b' * 64):
        return {'name': SCOPE['prefix'] + key + '.raw', 'size': '25', 'source_generation': '1', 'destination_generation': '2'}

    def summary(self, count=1, size=24):
        return {'schema': 'pot.beta-media-copy.v1', 'source_bucket': 'source-fixture-bucket', 'destination_bucket': 'destination-fixture-bucket',
                'source_generation_bound': True, 'destination_create_only': True, 'unexpected_destination_objects': 0,
                'errors': [], 'passed': True, 'objects': count, 'matched': count, 'bytes': size}

    def test_independent_receipt_formats_reconcile_without_double_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = copy_inventory(*self.files(Path(tmp), [self.row()], [self.generation()]), scope=SCOPE)
            self.assertEqual(len(result), 2)
            self.assertEqual(sum(x['bytes'] for x in result.values()), 49)

    def test_duplicate_wrong_bucket_and_wrong_source_fail(self):
        cases = [([self.row()], [self.generation('a' * 64)]),
                 ([dict(self.row(), Destination='gs://other/' + SCOPE['prefix'] + 'a' * 64 + '.raw')], []),
                 ([dict(self.row(), Source=SCOPE['source'] + SCOPE['prefix'] + 'c' * 64 + '.raw#1')], [])]
        for rows, gens in cases:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                copy_inventory(*self.files(Path(tmp), rows, gens), scope=SCOPE)

    def test_partial_failed_and_unversioned_receipts_fail(self):
        cases = [([dict(self.row(), Result='ERROR')], []), ([dict(self.row(), **{'Bytes Transferred': '23'})], []),
                 ([], [dict(self.generation(), destination_generation='')])]
        for rows, gens in cases:
            with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                copy_inventory(*self.files(Path(tmp), rows, gens), scope=SCOPE)

    def test_summary_scope_counts_and_failures_must_reconcile(self):
        blobs = {'a' * 64: {'bytes': 24}}
        validate_copy_summary(self.summary(), blobs, scope=SCOPE)
        for patch_value in [{'source_bucket': 'other'}, {'schema': 'other'}, {'source_generation_bound': False},
                            {'errors': ['failed']}, {'unexpected_destination_objects': 1}, {'objects': 2}]:
            with self.assertRaises(ValueError):
                validate_copy_summary({**self.summary(), **patch_value}, blobs, scope=SCOPE)


class SnapshotIntegrationTest(unittest.TestCase):
    files = CopyEvidenceTest.files
    row = CopyEvidenceTest.row
    summary = CopyEvidenceTest.summary

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / 'catalog.sqlite3'
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('CREATE TABLE card(card_id TEXT PRIMARY KEY,language TEXT,set_code TEXT,collector_number TEXT,variant TEXT,name TEXT,provenance TEXT)')
            db.execute('INSERT INTO card VALUES (?,?,?,?,?,?,?)', ('ja:S:1:holo', 'ja', 'S', '1', 'holo', 'Fixture', 'fixture-pin'))
            db.commit()
        self.snapshot = self.root / 'snapshot.json'
        self.data = {'schema': 'pokemon.catalog-primary-decisions.v1', 'database_sha256': sha256(self.db), 'catalog_records': 1,
            'producer': {'name': 'synthetic-test-reader', 'reader_code_sha256': 'c' * 64}, 'rows': [
                {'card_id': 'ja:S:1:holo', 'identity': {'language': 'ja', 'set_code': 'S', 'collector_number': '1', 'variant': 'holo', 'name': 'Fixture'},
                 'catalog_provenance_sha256': hashlib.sha256(b'fixture-pin').hexdigest(),
                 'primary_image': {'status': 'current', 'basis': 'catalog_source_reference', 'event_id': 'catalog-source-image:' + 'c' * 64, 'current_endpoint': True, 'image_sha256': 'a' * 64},
                 'source_scan': {'status': 'missing_source_scan_evidence', 'current_endpoint': False}}]}
        self.save_snapshot()

    def tearDown(self):
        self.temp.cleanup()

    def save_snapshot(self):
        self.snapshot.write_text(json.dumps(self.data))

    def load(self):
        return load_snapshot(self.snapshot, sha256(self.snapshot), sha256(self.db))

    def test_snapshot_hash_population_and_identity_are_bound(self):
        with self.assertRaisesRegex(ValueError, 'checksum'):
            load_snapshot(self.snapshot, '0' * 64, sha256(self.db))
        self.data['rows'][0]['identity']['variant'] = 'reverse_holo'
        self.save_snapshot()
        data, rows = self.load()
        with closing(sqlite3.connect(self.db)) as db, self.assertRaisesRegex(ValueError, 'identity'):
            db.row_factory = sqlite3.Row
            validate_catalog(db, data, rows)

    def test_duplicate_or_unsupported_decisions_fail(self):
        self.data['rows'].append(self.data['rows'][0])
        self.data['catalog_records'] = 2
        self.save_snapshot()
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.load()
        self.data['rows'] = self.data['rows'][:1]
        self.data['catalog_records'] = 1
        self.data['rows'][0]['primary_image']['status'] = 'verified_authentic'
        self.save_snapshot()
        with self.assertRaisesRegex(ValueError, 'decision'):
            self.load()

    def test_contradictory_current_primary_or_scan_cannot_inflate_coverage(self):
        for patch_value in [{'current_endpoint': False}, {'event_id': None}, {'basis': None}]:
            original = dict(self.data['rows'][0]['primary_image'])
            self.data['rows'][0]['primary_image'].update(patch_value)
            self.save_snapshot()
            with self.assertRaisesRegex(ValueError, 'decision'):
                self.load()
            self.data['rows'][0]['primary_image'] = original
        self.data['rows'][0]['source_scan']['status'] = 'current_source_scan_evidence'
        self.save_snapshot()
        with self.assertRaisesRegex(ValueError, 'decision'):
            self.load()

    def test_ambiguous_json_decisions_fail_before_use(self):
        for body in ['{"status":"held","status":"current"}', '{"count":NaN}']:
            with self.assertRaises(ValueError):
                strict_json(body)

    def test_actual_cli_is_offline_read_only_and_exposes_evidence_limit(self):
        csv_path, gens = self.files(self.root, [self.row()], [])
        summary = self.root / 'summary.json'
        summary.write_text(json.dumps(self.summary()))
        output = self.root / 'output'
        before = sha256(self.db)
        args = ['image_coverage', '--database', str(self.db), '--snapshot', str(self.snapshot), '--expected-snapshot-sha256', sha256(self.snapshot),
                '--source-bucket', 'source-fixture-bucket', '--destination-bucket', 'destination-fixture-bucket', '--namespace', 'fixture-v1',
                '--copy-csv', str(csv_path), '--copy-generations', str(gens), '--copy-verification', str(summary), '--output', str(output)]
        with patch.object(sys, 'argv', args), patch('socket.socket', side_effect=AssertionError('network forbidden')), redirect_stdout(io.StringIO()):
            main()
        result = json.loads((output / 'image-inventory.json').read_text())
        self.assertEqual(result['record_counts'], {'current_primary_recorded_copy': 1})
        self.assertFalse(result['native_reader_decisions_revalidated'])
        self.assertFalse(result['source_access_authorized'])
        self.assertIsNone(result['browser_image_load_coverage'])
        self.assertEqual(before, sha256(self.db))


if __name__ == '__main__':
    unittest.main()

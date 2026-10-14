"""Guarded parser builds reject transient namespaces before facts can escape."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from pokemon_index import core, collector_discovery as discovery
from pokemon_index import collector_runtime as runtime
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import create_fixture, SUITE


class RequestParserTempGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.path = self.base / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text('{"synthetic_only":true}')
        self.directory = self.base / 'artifact'
        with closing(core.connect(self.path, readonly=True)) as db:
            self.native = runtime.CatalogReadModel(db)
        with closing(core.connect(self.path, readonly=True)) as db:
            seal = artifact.write(db, self.manifest, self.directory)
        with closing(core.connect(self.path, readonly=True)) as db:
            self.loaded, _, _ = artifact.load(
                db, self.directory, self.manifest,
                expected_seal_sha256=seal['seal_sha256'])
        self.original_hash = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._catalog_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),
                         self.original_hash)

    @staticmethod
    def transient_shadow(db):
        # Only bound SQLite APIs and a synthetic TEMP view. BEGIN/rollback
        # restores its schema cookie; no guard attributes are manipulated.
        db.execute('PRAGMA query_only=OFF')
        db.execute('BEGIN')
        record = json.dumps({
            'value': 'Synthetic qualifier',
            'snapshot': {'cards': [{'card_id': 'synthetic:test-only'}]},
        }).replace("'", "''")
        db.execute(
            "CREATE TEMP VIEW source_correction_evidence AS SELECT "
            "'synthetic-e' AS event_id, 'synthetic-k' AS correction_key, "
            "1 AS revision, 'printed_qualifier' AS kind, 'ja' AS language, "
            "'" + record + "' AS record_json")
        db.execute('PRAGMA query_only=ON')

    def rejected_scope(self, model, mode):
        escaped = []

        def body(db):
            if mode == 'cached':
                self.assertEqual(discovery._qualifier_findings(
                    db, 'synthetic qualifier', ['ja']), [])
            self.transient_shadow(db)
            try:
                # Assert the reader itself rejects. Merely detecting TEMP at
                # scope exit would miss the rollback that follows this call.
                value = discovery._qualifier_findings(
                    db, 'synthetic qualifier', ['ja'])
                escaped.append(value)
            finally:
                db.rollback()
                db.execute('PRAGMA query_only=ON')

        probe = body if mode == 'direct' else runtime.catalog_request(body)
        with closing(core.connect(self.path, readonly=True)) as db:
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.request(db):
                    probe(db)
            self.assertEqual(escaped, [])
            self.assertFalse(db.in_transaction)
            self.assertIsNone(db.execute(
                'SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone())
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._catalog_scope.get())
        # A failed reader does not poison the immutable image or a new request.
        with closing(core.connect(self.path, readonly=True)) as fresh:
            with model.request(fresh):
                self.assertEqual(discovery._qualifier_findings(
                    fresh, 'synthetic qualifier', ['ja']), [])

    def test_cached_transaction_rollback_cannot_return_temp_qualifier(self):
        for model in (self.native, self.loaded):
            with self.subTest(model=model is self.loaded):
                self.rejected_scope(model, 'cached')

    def test_uncached_transaction_rollback_cannot_return_temp_qualifier(self):
        for model in (self.native, self.loaded):
            with self.subTest(model=model is self.loaded):
                self.rejected_scope(model, 'miss')

    def test_direct_snapshot_without_catalog_scope_rejects_temp_before_build(self):
        for model in (self.native, self.loaded):
            with self.subTest(model=model is self.loaded):
                self.rejected_scope(model, 'direct')

    def test_native_no_snapshot_still_reads_live_uncached_sql(self):
        @runtime.catalog_request
        def probe(db):
            self.assertIsNone(runtime._snapshot_scope.get())
            self.assertEqual(discovery._qualifier_findings(
                db, 'synthetic qualifier', ['ja']), [])
            self.transient_shadow(db)
            try:
                value = discovery._qualifier_findings(
                    db, 'synthetic qualifier', ['ja'])
                self.assertEqual(value, [{
                    'value': 'Synthetic qualifier', 'active': False,
                    'card_ids': ['synthetic:test-only'],
                    'evidence_id': 'synthetic-e',
                }])
            finally:
                db.rollback()
            self.assertEqual(discovery._qualifier_findings(
                db, 'synthetic qualifier', ['ja']), [])

        with closing(core.connect(self.path, readonly=True)) as db:
            probe(db)


if __name__ == '__main__':
    unittest.main()

"""Real-driver regressions for the packaged model's owned private HTTP handle.

Every database/artifact mutation below targets a disposable synthetic fixture.
Packets and file identities are produced by the real writer/packaged loader;
the tests do not manufacture private proof fields or trust equal-valued objects.
"""
from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_journey, collector_runtime as runtime
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


def typed(value):
    if type(value) is dict:
        return ('dict', tuple((key, typed(item)) for key, item in sorted(value.items())))
    if type(value) is list:
        return ('list', tuple(typed(item) for item in value))
    return (type(value).__name__, value)


class PrivateFacetDriverAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Exercise actual URI encoding, not a pre-escaped caller path.
        self.base = Path(self.tmp.name).resolve() / 'fixed-package?#%日本語'
        self.base.mkdir()
        self.path = self.base / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text('{"synthetic_test_only":true}')
        self.directory = self.base / 'artifact'
        with closing(core.connect(self.path, readonly=True)) as db:
            self.receipt = artifact.write(db, self.manifest, self.directory)
        self.facet = self.directory / 'facet-image.sqlite3'
        self.original_db_sha = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.allow_fixture_db_mutation = False
        with self.packaged_paths(), closing(core.connect(self.path, readonly=True)) as db:
            self.model, self.revision, self.loaded_receipt = artifact.load_packaged(db, required=True)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._work_deadline.get())
        self.assertEqual(runtime._sql_scopes.get(), ())
        if not self.allow_fixture_db_mutation:
            self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.original_db_sha)

    @contextmanager
    def packaged_paths(self):
        # As in existing packaged-path unit fixtures, only the literal package
        # constants are rebound; no private packet or witness is supplied.
        with patch.object(artifact, '_PACKAGED_DIR', self.directory), patch.object(
                artifact, '_PACKAGED_MANIFEST', self.manifest):
            yield

    @contextmanager
    def owned(self, *, expires=None):
        with self.model.owned_http_request(
                expires=time.monotonic() + 8 if expires is None else expires) as db:
            yield db

    def read_facts(self, db):
        return runtime.snapshot_character_names(db, False)

    def assert_closed(self, db):
        with self.assertRaises(sqlite3.ProgrammingError):
            _ = db.in_transaction

    def assert_sticky_denial(self, mutate, restore=None):
        seen = []
        with self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.owned() as db:
                seen.append(db)
                self.assertIsNotNone(self.read_facts(db))
                with self.assertRaises((runtime.CatalogSnapshotChanged, sqlite3.DatabaseError)):
                    mutate(db)
                if restore is not None:
                    with self.assertRaises((runtime.CatalogSnapshotChanged, sqlite3.DatabaseError)):
                        restore(db)
                # Catching the initial violation must not let a later immutable
                # fact lookup or apparently successful context exit publish.
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    self.read_facts(db)
        self.assertEqual(len(seen), 1)
        self.assert_closed(seen[0])

    def assert_external_change_rejected(self, mutate):
        seen = []
        with self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.owned() as db:
                seen.append(db)
                self.assertIsNotNone(self.read_facts(db))
                db.execute('SELECT count(*) FROM collector_snapshot.facets').fetchone()
                mutate()
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    self.read_facts(db)
        self.assertEqual(len(seen), 1)
        self.assert_closed(seen[0])

    def test_owned_handle_is_fresh_file_backed_and_complete_typed_native_equal(self):
        payload = {'turns': [{'type': 'ask', 'question': 'Recommend Japanese Pikachu cards'}], 'limit': 5}
        with closing(core.connect(self.path, readonly=True)) as db:
            expected = collector_journey.replay(db, payload, revision=self.revision)
        handles = []
        for _ in range(2):
            with self.owned() as db:
                handles.append(db)
                databases = {row[1]: row[2] for row in db.execute('PRAGMA database_list')}
                self.assertEqual(Path(databases['main']), self.path)
                self.assertEqual(Path(databases['collector_snapshot']), self.facet)
                self.assertIs(db.row_factory, sqlite3.Row)
                self.assertIs(db.text_factory, str)
                self.assertEqual(typed(collector_journey.replay(db, payload, revision=self.revision)), typed(expected))
            self.assert_closed(db)
        self.assertIsNot(handles[0], handles[1])

    def test_generic_request_on_packaged_custom_loaded_and_native_models_stays_memory(self):
        with closing(core.connect(self.path, readonly=True)) as db:
            custom, _, _ = artifact.load(db, self.directory, self.manifest,
                                        expected_seal_sha256=self.receipt['seal_sha256'])
        with closing(core.connect(self.path, readonly=True)) as db:
            native = runtime.CatalogReadModel(db)
        for model in (self.model, custom, native):
            with self.subTest(model=type(model).__name__), closing(core.connect(self.path, readonly=True)) as db:
                with model.request(db, strict_readonly=True):
                    databases = {row[1]: row[2] for row in db.execute('PRAGMA database_list')}
                    self.assertEqual(databases['collector_snapshot'], '')
                    self.assertIsNotNone(self.read_facts(db))

    def test_connection_row_and_text_factory_flip_and_restore_are_sticky(self):
        calls = []

        def row_factory(cursor, row):
            calls.append('row')
            return row

        def text_factory(value):
            calls.append('text')
            return value.decode()

        for name, value, original in (
                ('row_factory', row_factory, sqlite3.Row), ('text_factory', text_factory, str)):
            with self.subTest(factory=name):
                self.assert_sticky_denial(lambda db: setattr(db, name, value),
                                          lambda db: setattr(db, name, original))
        self.assertEqual(calls, [])

    def test_cursor_row_factory_is_sticky_for_cursor_and_execute_return_paths(self):
        calls = []
        for label, cursor_for in (
                ('cursor', lambda db: db.cursor()),
                ('execute', lambda db: db.execute('SELECT 1'))):
            cursor = []

            def mutate(db):
                cursor.append(cursor_for(db))
                cursor[0].row_factory = lambda cur, row: calls.append(label) or row

            with self.subTest(path=label):
                self.assert_sticky_denial(mutate, lambda db: setattr(cursor[0], 'row_factory', sqlite3.Row))
        self.assertEqual(calls, [])

    def test_custom_cursor_factories_are_rejected_before_construction(self):
        calls = []

        class CustomCursor(sqlite3.Cursor):
            def __init__(self, *args, **kwargs):
                calls.append('constructed')
                super().__init__(*args, **kwargs)

        for make in (lambda db: db.cursor(factory=CustomCursor), lambda db: db.cursor(CustomCursor)):
            self.assert_sticky_denial(make)
        self.assertEqual(calls, [])

    def test_trace_and_progress_registration_and_removal_are_sticky(self):
        calls = []
        operations = (
            lambda db: db.set_trace_callback(lambda text: calls.append('trace')),
            lambda db: db.set_trace_callback(None),
            lambda db: db.set_progress_handler(lambda: calls.append('progress') or 0, 1),
            lambda db: db.set_progress_handler(None, 0),
        )
        for index, mutate in enumerate(operations):
            with self.subTest(operation=index):
                self.assert_sticky_denial(mutate)
        self.assertEqual(calls, [])

    def test_SQL_function_aggregate_window_and_collation_callbacks_cannot_register(self):
        calls = []

        class Aggregate:
            def __init__(self):
                calls.append('aggregate')

            def step(self, value):
                pass

            def finalize(self):
                return 0

        class Window(Aggregate):
            def inverse(self, value):
                pass

            def value(self):
                return 0

        self.assertTrue(hasattr(sqlite3.Connection, 'create_window_function'))
        operations = (
            lambda db: db.create_function('private_probe', 0, lambda: calls.append('function')),
            lambda db: db.create_function('private_probe', 0, None),
            lambda db: db.create_function('private_probe', 0, lambda: 0, deterministic=True),
            lambda db: db.create_aggregate('private_probe', 1, Aggregate),
            lambda db: db.create_aggregate('private_probe', 1, None),
            lambda db: db.create_window_function('private_probe', 1, Window),
            lambda db: db.create_window_function('private_probe', 1, None),
            lambda db: db.create_collation('private_probe', lambda a, b: calls.append('collation') or 0),
            lambda db: db.create_collation('private_probe', None),
        )
        for index, mutate in enumerate(operations):
            with self.subTest(operation=index):
                self.assert_sticky_denial(mutate)
        self.assertEqual(calls, [])

    def test_authorizer_and_extension_API_changes_are_sticky(self):
        calls = []
        operations = (
            lambda db: db.set_authorizer(None),
            lambda db: db.set_authorizer(lambda *args: calls.append('authorizer') or sqlite3.SQLITE_OK),
            lambda db: db.enable_load_extension(True),
            lambda db: db.enable_load_extension(False),
            lambda db: db.load_extension(str(self.base / 'nonexistent-private-extension')),
            lambda db: db.execute("SELECT load_extension('nonexistent-private-extension')"),
        )
        for index, mutate in enumerate(operations):
            with self.subTest(operation=index):
                self.assert_sticky_denial(mutate)
        self.assertEqual(calls, [])

    def test_caught_writes_namespace_transactions_and_TEMP_changes_do_not_recover(self):
        statements = (
            "UPDATE main.card SET name='private mutation'",
            "UPDATE collector_snapshot.facets SET value='private mutation'",
            'CREATE TEMP TABLE private_mutation(value)',
            "ATTACH DATABASE ':memory:' AS private_mutation",
            'DETACH DATABASE collector_snapshot',
            'BEGIN',
            'SAVEPOINT private_mutation',
            'COMMIT',
            'ROLLBACK',
            'PRAGMA query_only=OFF',
            'PRAGMA collector_snapshot.schema_version=17',
        )
        for statement in statements:
            with self.subTest(statement=statement):
                self.assert_sticky_denial(lambda db: db.execute(statement))

    def test_bound_deserialize_main_and_facet_attempts_are_sticky(self):
        for namespace in ('main', 'collector_snapshot'):
            with self.subTest(namespace=namespace):
                self.assert_sticky_denial(lambda db: db.deserialize(self.model._image, name=namespace))

    def test_prior_authorizer_on_real_factory_handle_fails_before_callback_and_closes(self):
        original_connect = core.connect
        handles, calls = [], []

        def contaminated(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            db.set_authorizer(lambda *values: calls.append(values) or sqlite3.SQLITE_OK)
            handles.append(db)
            return db

        with patch.object(core, 'connect', side_effect=contaminated):
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.owned():
                    self.fail('a handle with a prior callback entered private HTTP scope')
        self.assertEqual(calls, [])
        for db in handles:
            self.assert_closed(db)

    def test_primitive_global_adapter_rejects_setup_before_adapter_callback(self):
        original = dict(sqlite3.adapters)
        calls = []

        def adapter(value):
            calls.append(value)
            return value

        try:
            sqlite3.register_adapter(str, adapter)
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.owned():
                    self.fail('global primitive adapter entered private HTTP scope')
            self.assertEqual(calls, [])
        finally:
            sqlite3.adapters.clear()
            sqlite3.adapters.update(original)
        self.assertEqual(sqlite3.adapters, original)
        with self.owned() as db:
            self.assertIsNotNone(self.read_facts(db))

    def test_primitive_adapter_added_then_restored_during_body_stays_denied(self):
        original = dict(sqlite3.adapters)
        calls = []
        handles = []
        try:
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.owned() as db:
                    handles.append(db)
                    self.assertIsNotNone(self.read_facts(db))
                    sqlite3.register_adapter(str, lambda value: calls.append(value) or value)
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        db.execute('SELECT ?', ('synthetic adapter probe',)).fetchone()
                    sqlite3.adapters.clear()
                    sqlite3.adapters.update(original)
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        self.read_facts(db)
        finally:
            sqlite3.adapters.clear()
            sqlite3.adapters.update(original)
        self.assertEqual(calls, [])
        for db in handles:
            self.assert_closed(db)

    def test_nested_owned_failure_restores_outer_scope_deadline_and_handle(self):
        with self.owned() as outer:
            outer_scope = runtime._snapshot_scope.get()
            outer_deadline = runtime._work_deadline.get()
            outer_sql = runtime._sql_scopes.get()
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.owned() as inner:
                    self.assertIsNot(inner, outer)
                    self.assertIs(runtime._snapshot_scope.get()['db'], inner)
                    inner.set_trace_callback(None)
            self.assert_closed(inner)
            self.assertIs(runtime._snapshot_scope.get(), outer_scope)
            self.assertEqual(runtime._work_deadline.get(), outer_deadline)
            self.assertEqual(runtime._sql_scopes.get(), outer_sql)
            self.assertIsNotNone(self.read_facts(outer))
        self.assert_closed(outer)

    def test_failure_after_real_attachment_closes_handle_and_restores_scopes(self):
        original_connect = core.connect
        handles = []

        def capture(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            handles.append(db)
            return db

        def fail_after_attachment(db):
            databases = {row[1]: row[2] for row in db.execute('PRAGMA database_list')}
            self.assertEqual(Path(databases['collector_snapshot']), self.facet)
            raise RuntimeError('synthetic post-attachment failure')

        # Inject an exception after the real driver attached its real file;
        # no replacement identity, guard or successful proof is manufactured.
        with patch.object(core, 'connect', side_effect=capture), patch.object(
                runtime, '_static_snapshot_version', side_effect=fail_after_attachment):
            with self.assertRaisesRegex(RuntimeError, 'synthetic post-attachment failure'):
                with self.owned():
                    self.fail('post-attachment setup failure entered request body')
        self.assertEqual(len(handles), 1)
        self.assert_closed(handles[0])
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._work_deadline.get())
        self.assertEqual(runtime._sql_scopes.get(), ())
        with self.owned() as db:
            self.assertIsNotNone(self.read_facts(db))

    def test_exit_checks_detect_change_without_another_fact_lookup(self):
        with self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.owned() as db:
                self.assertIsNotNone(self.read_facts(db))
                metadata = self.directory / 'metadata.json'
                metadata.write_bytes(metadata.read_bytes())
        self.assert_closed(db)

    def test_original_progress_deadline_survives_private_guard_and_closes(self):
        handles = []
        with self.assertRaises(runtime.CatalogDeadline):
            with self.owned(expires=time.monotonic() + .02) as db:
                handles.append(db)
                db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        for db in handles:
            self.assert_closed(db)
        with self.owned() as db:
            self.assertIsNotNone(self.read_facts(db))

    def test_expired_setup_and_body_exception_restore_scopes_and_close_handles(self):
        original_connect = core.connect
        handles = []

        def capture(*args, **kwargs):
            db = original_connect(*args, **kwargs)
            handles.append(db)
            return db

        with patch.object(core, 'connect', side_effect=capture):
            with self.assertRaises(runtime.CatalogDeadline):
                with self.owned(expires=time.monotonic() - 1):
                    self.fail('expired private setup entered')
        for db in handles:
            self.assert_closed(db)
        with self.assertRaisesRegex(ValueError, 'synthetic body failure'):
            with self.owned() as db:
                body_handle = db
                raise ValueError('synthetic body failure')
        self.assert_closed(body_handle)
        with self.owned() as db:
            self.assertIsNotNone(self.read_facts(db))

    def test_external_facet_commit_is_rejected_at_next_lookup(self):
        def mutate():
            with closing(sqlite3.connect(self.facet, timeout=.1)) as writer:
                writer.execute("UPDATE facets SET value='unqualified external value' WHERE rowid=(SELECT min(rowid) FROM facets)")
                writer.commit()
        self.assert_external_change_rejected(mutate)

    def test_external_main_commit_is_rejected_at_next_lookup(self):
        self.allow_fixture_db_mutation = True

        def mutate():
            with closing(sqlite3.connect(self.path, timeout=.1)) as writer:
                writer.execute("UPDATE card SET name='unqualified external value' WHERE rowid=(SELECT min(rowid) FROM card)")
                writer.commit()
        self.assert_external_change_rejected(mutate)

    def test_external_facet_WAL_commit_and_checkpoint_removal_are_rejected(self):
        def mutate():
            with closing(sqlite3.connect(self.facet, timeout=.1)) as writer:
                self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
                writer.execute("UPDATE facets SET value='unqualified WAL value' WHERE rowid=(SELECT min(rowid) FROM facets)")
                writer.commit()
                writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchall()
            # Checkpoint/last-writer close may remove the sidecar. Neither its
            # removal nor unchanged row counts may bless the changed backing DB.
        self.assert_external_change_rejected(mutate)

    def test_live_facet_WAL_sidecar_is_rejected_before_writer_closes(self):
        writer = sqlite3.connect(self.facet, timeout=.1)
        self.addCleanup(writer.close)

        def mutate():
            self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            writer.execute("UPDATE facets SET value='unqualified live WAL' WHERE rowid=(SELECT min(rowid) FROM facets)")
            writer.commit()
            self.assertTrue(Path(str(self.facet) + '-wal').exists())
        self.assert_external_change_rejected(mutate)

    def test_same_bytes_replacement_of_facet_path_rejects_open_handle_mismatch(self):
        replacement = self.base / 'replacement-facet.sqlite3'
        replacement.write_bytes(self.facet.read_bytes())
        self.assert_external_change_rejected(lambda: os.replace(replacement, self.facet))

    def test_same_bytes_replacement_of_main_path_rejects_open_handle_mismatch(self):
        replacement = self.base / 'replacement-main.sqlite3'
        replacement.write_bytes(self.path.read_bytes())
        self.assert_external_change_rejected(lambda: os.replace(replacement, self.path))

    def test_facet_hardlink_changes_witness_and_is_rejected(self):
        self.assert_external_change_rejected(lambda: os.link(self.facet, self.base / 'unexpected-facet-hardlink.sqlite3'))

    def test_zero_byte_WAL_symlink_is_rejected_even_when_target_has_no_bytes(self):
        empty = self.base / 'zero-byte-sidecar-target'
        empty.write_bytes(b'')
        wal = Path(str(self.facet) + '-wal')
        self.assert_external_change_rejected(lambda: wal.symlink_to(empty))

    def test_dangling_WAL_symlink_is_rejected_even_when_exists_is_false(self):
        wal = Path(str(self.facet) + '-wal')

        def mutate():
            wal.symlink_to(self.base / 'absent-sidecar-target')
            self.assertFalse(wal.exists())
            self.assertTrue(wal.is_symlink())
        self.assert_external_change_rejected(mutate)

    def test_artifact_directory_replaced_with_symlink_is_rejected(self):
        def mutate():
            moved = self.base / 'original-artifact'
            self.directory.rename(moved)
            self.directory.symlink_to(moved, target_is_directory=True)
        self.assert_external_change_rejected(mutate)

    def test_metadata_witness_change_is_rejected_at_next_lookup(self):
        metadata = self.directory / 'metadata.json'
        before = metadata.read_bytes()

        def mutate():
            metadata.write_bytes(before)
        self.assert_external_change_rejected(mutate)


if __name__ == '__main__':
    unittest.main()

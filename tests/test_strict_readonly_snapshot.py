"""Strict request scopes over synthetic snapshots, without inherited test copies."""
from contextlib import closing, contextmanager
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_journey, collector_runtime as runtime
from pokemon_index import collector_release_alias
from pokemon_index import catalog_read_model_artifact as artifact
from tests import test_snapshot_clone_guard as clone_fixture


def typed(value):
    if isinstance(value, dict):
        # Object member order is not JSON value semantics; key/value Python
        # types and every array position still have to match exactly.
        return (type(value), {typed(key): typed(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return (type(value), tuple(typed(item) for item in value))
    return (type(value), value)


class StrictReadonlySnapshotTests(unittest.TestCase):
    def fixture(self):
        # Compose only the existing fixture setup and cleanup. Importing its
        # module, rather than its TestCase class, avoids duplicate discovery.
        fixture = clone_fixture.SnapshotCloneGuardTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.addCleanup(fixture.tearDown)
        return fixture

    def assert_released(self, db, prior=None):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(getattr(db, '_catalog_clone_guard', None))
        self.assertIs(getattr(db, '_catalog_authorizer', None), prior)

    def test_strict_default_and_native_replay_bodies_and_types_match(self):
        fixture = self.fixture()
        payloads = [dict(turns=[dict(type='ask', question=question)], limit=5)
                    for question in ('Recommend Japanese Pikachu cards',
                                     'Recommend English Mew cards',
                                     'ピカチュウのカード', '推荐日文皮卡丘卡牌',
                                     'Recommend cards by Alpha')]
        with closing(core.connect(fixture.path, readonly=True)) as db:
            expected = [collector_journey.replay(db, payload, revision='a' * 64)
                        for payload in payloads]
        for label, model in fixture.models.items():
            for mode in ('default', False, True):
                with self.subTest(model=label, strict_readonly=mode):
                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        scope = model.request(db) if mode == 'default' else model.request(db, strict_readonly=mode)
                        with scope:
                            actual = [collector_journey.replay(db, payload, revision='a' * 64)
                                      for payload in payloads]
                            self.assertEqual(actual, expected)
                            self.assertEqual(typed(actual), typed(expected))
                            self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                            self.assertTrue(db.execute('PRAGMA main.table_info(card)').fetchall())
                            self.assertTrue(db.execute('PRAGMA collector_snapshot.index_list(facets)').fetchall())
                            self.assertEqual(db.execute('SELECT abs(-1)').fetchone()[0], 1)
                        self.assert_released(db)

    def test_default_scope_keeps_existing_query_only_restore_behavior(self):
        fixture = self.fixture()
        for model in fixture.models.values():
            for explicit in (False, True):
                with closing(core.connect(fixture.path, readonly=True)) as db:
                    scope = model.request(db, strict_readonly=False) if explicit else model.request(db)
                    with scope:
                        db.execute('PRAGMA query_only=OFF')
                        self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 0)
                        db.execute('PRAGMA query_only=ON')
                        self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                    self.assert_released(db)

    def mutations(self, fixture):
        return {
            'main_update': lambda db: db.execute('UPDATE main.card SET name=name'),
            'main_ddl': lambda db: db.execute('CREATE TABLE main.strict_poison(value)'),
            'temp_table': lambda db: db.execute('CREATE TEMP TABLE strict_poison(value)'),
            'temp_view': lambda db: db.execute('CREATE TEMP VIEW card AS SELECT * FROM main.card'),
            'clone_update': lambda db: db.execute("UPDATE collector_snapshot.facets SET value='poison'"),
            'clone_delete': lambda db: db.execute('DELETE FROM collector_snapshot.facets'),
            'clone_ddl': lambda db: db.execute('DROP INDEX collector_snapshot.facet_lookup'),
            'query_only': lambda db: db.execute('PRAGMA query_only=OFF'),
            'main_schema_version': lambda db: db.execute('PRAGMA main.schema_version=3'),
            'temp_schema_version': lambda db: db.execute('PRAGMA temp.schema_version=3'),
            'clone_schema_version': lambda db: db.execute('PRAGMA collector_snapshot.schema_version=3'),
            'pragma_optimize': lambda db: db.execute('PRAGMA optimize'),
            'pragma_cache_size': lambda db: db.execute('PRAGMA cache_size=100'),
            'begin': lambda db: db.execute('BEGIN'),
            'commit_sql': lambda db: db.execute('COMMIT'),
            'rollback_sql': lambda db: db.execute('ROLLBACK'),
            'savepoint': lambda db: db.execute('SAVEPOINT strict_poison'),
            'release': lambda db: db.execute('RELEASE strict_poison'),
            'rollback_to': lambda db: db.execute('ROLLBACK TO strict_poison'),
            'attach': lambda db: db.execute("ATTACH DATABASE ':memory:' AS strict_poison"),
            'detach': lambda db: db.execute('DETACH DATABASE collector_snapshot'),
            'connection_executemany': lambda db: db.executemany('UPDATE main.card SET name=name', [()]),
            'connection_executescript': lambda db: db.executescript('CREATE TEMP TABLE strict_poison(value);'),
            'cursor_execute': lambda db: db.cursor().execute('CREATE TEMP TABLE strict_poison(value)'),
            'cursor_executemany': lambda db: db.cursor().executemany('UPDATE main.card SET name=name', [()]),
            'cursor_executescript': lambda db: db.cursor().executescript('CREATE TEMP TABLE strict_poison(value);'),
            'preexisting_cursor': lambda db: db._test_cursor.execute('CREATE TEMP TABLE strict_poison(value)'),
            'base_connection_execute': lambda db: sqlite3.Connection.execute(db, 'CREATE TEMP TABLE strict_poison(value)'),
            'base_cursor_execute': lambda db: sqlite3.Cursor.execute(db._test_cursor, 'CREATE TEMP TABLE strict_poison(value)'),
            'bound_deserialize_clone': lambda db: db.deserialize(fixture.changed_image, name='collector_snapshot'),
            'bound_deserialize_main': lambda db: db.deserialize(fixture.changed_image),
            'base_deserialize_clone': lambda db: sqlite3.Connection.deserialize(db, fixture.changed_image, name='collector_snapshot'),
            'clear_authorizer': lambda db: db.set_authorizer(None),
            'replace_authorizer': lambda db: db.set_authorizer(lambda *args: sqlite3.SQLITE_OK),
        }

    def test_every_namespace_driver_and_cursor_denial_is_sticky_when_caught(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            for name, mutate in self.mutations(fixture).items():
                with self.subTest(model=label, mutation=name):
                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        db._test_cursor = db.cursor()
                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                            with model.request(db, strict_readonly=True):
                                before = fixture.facets(db)
                                changes = db.total_changes
                                with self.assertRaises((runtime.CatalogSnapshotChanged, sqlite3.DatabaseError)):
                                    mutate(db)
                                self.assertEqual(db.total_changes, changes)
                                self.assertEqual(fixture.facets(db), before)
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    runtime.snapshot_character_names(db, False)
                        self.assert_released(db)
                        self.assertFalse(db.in_transaction)
                        self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                        self.assertIsNone(db.execute('SELECT 1 FROM temp.sqlite_master LIMIT 1').fetchone())

    def test_prior_authorizer_chains_denials_and_is_restored_on_every_exit(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            for outcome in ('success', 'body_error', 'caught_forbidden_write'):
                with self.subTest(model=label, outcome=outcome):
                    seen = []

                    def prior(action, first, second, database, source):
                        seen.append((action, first, second, database, source))
                        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_FUNCTION and second == 'abs' else sqlite3.SQLITE_OK

                    marker = ValueError('synthetic body failure')
                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        db.set_authorizer(prior)
                        try:
                            with model.request(db, strict_readonly=True):
                                with self.assertRaises(sqlite3.DatabaseError):
                                    db.execute('SELECT abs(-1)')
                                self.assertFalse(db._catalog_clone_guard['invalid'])
                                self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                                if outcome == 'body_error':
                                    raise marker
                                if outcome == 'caught_forbidden_write':
                                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                                        db.execute('CREATE TEMP TABLE strict_poison(value)')
                        except ValueError as caught:
                            self.assertEqual(outcome, 'body_error')
                            self.assertIs(caught, marker)
                        except runtime.CatalogSnapshotChanged:
                            self.assertEqual(outcome, 'caught_forbidden_write')
                        self.assertTrue(seen)
                        self.assert_released(db, prior)
                        with self.assertRaises(sqlite3.DatabaseError):
                            db.execute('SELECT abs(-1)')
                        db.set_authorizer(None)
                        self.assertEqual(db.execute('SELECT abs(-1)').fetchone()[0], 1)
                        db.execute('PRAGMA query_only=OFF')
                        db.execute('CREATE TEMP TABLE offline_mutability_restored(value)')

    def test_setup_failures_release_guard_restore_prior_and_never_publish_scope(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            for target, name in ((runtime, '_static_snapshot_version'),
                                 (model, '_capture_path_ancestors'),
                                 (model, '_check_sealed_snapshot')):
                with self.subTest(model=label, failure=name):
                    def prior(*args):
                        return sqlite3.SQLITE_OK

                    error = ValueError('synthetic strict setup failure')
                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        db.set_authorizer(prior)
                        with patch.object(target, name, side_effect=error):
                            with self.assertRaises(ValueError) as caught:
                                with model.request(db, strict_readonly=True):
                                    self.fail('failed setup yielded a snapshot')
                        self.assertIs(caught.exception, error)
                        self.assert_released(db, prior)
                        db.execute('PRAGMA query_only=OFF')
                        db.execute('CREATE TEMP TABLE cleanup_was_complete(value)')
                    with closing(core.connect(fixture.path, readonly=True)) as fresh:
                        with model.request(fresh, strict_readonly=True):
                            self.assertIsNotNone(runtime.snapshot_character_names(fresh, False))

    def test_prior_authorizer_setup_denial_is_preserved_without_poison_or_yield(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            with self.subTest(model=label), closing(core.connect(fixture.path, readonly=True)) as db:
                def prior(action, first, second, database, source):
                    return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_PRAGMA and first == 'data_version' else sqlite3.SQLITE_OK

                db.set_authorizer(prior)
                with self.assertRaises(sqlite3.DatabaseError):
                    with model.request(db, strict_readonly=True):
                        self.fail('denied entry stamp yielded shared facts')
                self.assert_released(db, prior)
                with self.assertRaises(sqlite3.DatabaseError):
                    db.execute('PRAGMA main.data_version')
                self.assertEqual(db.execute('SELECT 1').fetchone()[0], 1)

    def test_captured_prior_callback_cannot_clear_itself_and_adopt_mutated_clone(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            with self.subTest(model=label), closing(core.connect(fixture.path, readonly=True)) as db:
                attacks = []

                def prior(action, first, second, database, source):
                    if action == sqlite3.SQLITE_PRAGMA and first == 'query_only' and second == 'ON' and not attacks:
                        attacks.append(True)
                        db.set_authorizer(None)
                        db.execute("UPDATE collector_snapshot.facets SET value='unqualified attach-time mutation'")
                        db.commit()
                        db.execute('PRAGMA query_only=ON')
                    return sqlite3.SQLITE_OK

                db.set_authorizer(prior)
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db, strict_readonly=True):
                        self.fail('attach-time mutated clone was accepted')
                self.assertEqual(attacks, [True])
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                self.assertIn('unqualified attach-time mutation', {row[0] for row in db.execute('SELECT value FROM collector_snapshot.facets')})
                self.assert_released(db)

    def test_caught_denied_write_in_read_pragma_callback_never_exposes_shared_facts(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            with self.subTest(model=label), closing(core.connect(fixture.path, readonly=True)) as db:
                armed = False
                attacks = []

                def prior(action, first, second, database, source):
                    if armed and not attacks and action == sqlite3.SQLITE_PRAGMA and first == 'data_version':
                        attacks.append(True)
                        try:
                            db.execute('CREATE TEMP TABLE callback_poison(value)')
                        except (runtime.CatalogSnapshotChanged, sqlite3.DatabaseError):
                            pass
                    return sqlite3.SQLITE_OK

                db.set_authorizer(prior)
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db, strict_readonly=True):
                        self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                        # Evict the entry's prepared PRAGMA so SQLite invokes
                        # the real prior callback during the next trust read.
                        for index in range(256):
                            db.execute('SELECT ' + str(index)).fetchone()
                        armed = True
                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                            runtime.snapshot_character_names(db, False)
                        self.assertEqual(attacks, [True])
                self.assert_released(db, prior)

    def test_main_data_version_is_fresh_even_when_file_guard_is_test_only_bypassed(self):
        fixture = self.fixture()
        for label in fixture.models:
            path = fixture.base / ('data-version-' + label + '.sqlite3')
            path.write_bytes(fixture.path.read_bytes())
            with closing(sqlite3.connect(path)) as writer:
                self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
                writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                directory = fixture.base / ('data-version-' + label + '-artifact')
                with closing(core.connect(path, readonly=True)) as source:
                    if label == 'native':
                        model = runtime.CatalogReadModel(source)
                    else:
                        receipt = artifact.write(source, fixture.manifest, directory)
                        model, _, _ = artifact.load(source, directory, fixture.manifest,
                                                    expected_seal_sha256=receipt['seal_sha256'])
                with closing(core.connect(path, readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        # Explicit test-only fault injection isolates the SQL
                        # witness from the separate fresh main/WAL/path seal.
                        with patch.object(model, '_check_sealed_snapshot', return_value=None) as bypass:
                            with model.request(db, strict_readonly=True):
                                self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                                before = db.execute('PRAGMA main.data_version').fetchone()[0]
                                writer.execute("UPDATE card SET name=name || ' synthetic external commit'")
                                writer.commit()
                                self.assertNotEqual(db.execute('PRAGMA main.data_version').fetchone()[0], before)
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    runtime.snapshot_character_names(db, False)
                                self.assertGreaterEqual(bypass.call_count, 3)
                    self.assert_released(db)

    def test_invalid_strict_types_reject_before_connection_or_snapshot_io(self):
        fixture = self.fixture()

        class MustNotCoerce:
            def __bool__(self):
                raise AssertionError('strict mode must not coerce caller input')

        for model in fixture.models.values():
            for invalid in (None, 0, 1, 0.0, 'true', [], {}, MustNotCoerce()):
                with self.subTest(value=type(invalid).__name__):
                    with patch.object(runtime, 'checkpoint', side_effect=AssertionError('checkpoint before type validation')):
                        with patch.object(model, '_check_snapshot', side_effect=AssertionError('snapshot I/O before type validation')):
                            with patch.object(model, '_attach', side_effect=AssertionError('attach before type validation')):
                                with self.assertRaises(ValueError):
                                    with model.request(object(), strict_readonly=invalid):
                                        self.fail('non-boolean strict mode was accepted')
                    self.assertIsNone(runtime._snapshot_scope.get())

    @contextmanager
    def path_mutation(self, fixture, mutation):
        if mutation == 'parent_symlink':
            saved = fixture.base.with_name(fixture.base.name + '-moved')
            fixture.base.rename(saved)
            fixture.base.symlink_to(saved, target_is_directory=True)
            try:
                yield
            finally:
                fixture.base.unlink()
                saved.rename(fixture.base)
        elif mutation in {'final_symlink', 'file_replacement'}:
            saved = fixture.base / 'original-main.sqlite3'
            fixture.path.rename(saved)
            if mutation == 'final_symlink':
                fixture.path.symlink_to(saved)
            else:
                fixture.path.write_bytes(saved.read_bytes())
            try:
                yield
            finally:
                fixture.path.unlink()
                saved.rename(fixture.path)
        else:
            wal = Path(str(fixture.path) + '-wal')
            self.assertFalse(wal.exists())
            if mutation == 'wal_nonempty':
                wal.write_bytes(b'synthetic nonempty WAL, never SQLite input')
            elif mutation == 'wal_symlink_empty':
                empty = fixture.base / 'empty-wal-target'
                empty.touch()
                wal.symlink_to(empty)
            elif mutation == 'wal_directory':
                wal.mkdir()
            else:
                self.fail('unknown synthetic path mutation')
            try:
                yield
            finally:
                wal.rmdir() if wal.is_dir() else wal.unlink()

    def test_persistent_parent_final_file_and_wal_changes_reject_before_fact_lookup(self):
        for label in ('native', 'loaded'):
            for mutation in ('parent_symlink', 'final_symlink', 'file_replacement',
                             'wal_nonempty', 'wal_symlink_empty', 'wal_directory'):
                fixture = self.fixture()
                model = fixture.models[label]
                with self.subTest(model=label, mutation=mutation):
                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        try:
                            with model.request(db, strict_readonly=True):
                                self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                                with self.path_mutation(fixture, mutation):
                                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                                        runtime.snapshot_character_names(db, False)
                        except runtime.CatalogSnapshotChanged:
                            # Restoring a moved file can change metadata too;
                            # publication must also reject that changed stamp.
                            pass
                        self.assert_released(db)

    def test_warmed_sql_is_reauthorized_and_caught_mutation_remains_sticky(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            for driver in ('connection', 'preexisting_cursor'):
                with self.subTest(model=label, driver=driver):
                    seen = []

                    def prior(*arguments):
                        seen.append(arguments)
                        return sqlite3.SQLITE_OK

                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        db.set_authorizer(prior)
                        cursor = db.cursor()
                        execute = db.execute if driver == 'connection' else cursor.execute
                        # Prepare and execute the identical setter before the
                        # strict authorizer is installed, on the same handle.
                        execute('PRAGMA query_only=OFF')
                        self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 0)
                        execute('PRAGMA query_only=ON')
                        self.assertTrue(seen)
                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                            with model.request(db, strict_readonly=True):
                                before = fixture.facets(db)
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    execute('PRAGMA query_only=OFF')
                                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                                self.assertEqual(fixture.facets(db), before)
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    runtime.snapshot_character_names(db, False)
                        self.assert_released(db, prior)
                        # The original policy and the ordinary offline setter
                        # are restored after the poisoned scope has ended.
                        count = len(seen)
                        execute('PRAGMA query_only=OFF')
                        self.assertGreater(len(seen), count)
                        self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 0)

    def test_strict_deadline_setup_and_sql_expiry_restore_policy_and_contexts(self):
        fixture = self.fixture()
        for label, model in fixture.models.items():
            for failure in ('entry_stamp', 'ancestor_capture', 'sql_work'):
                with self.subTest(model=label, failure=failure):
                    def prior(action, first, second, database, source):
                        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_FUNCTION and second == 'abs' else sqlite3.SQLITE_OK

                    with closing(core.connect(fixture.path, readonly=True)) as db:
                        db.set_authorizer(prior)
                        with self.assertRaises(runtime.CatalogDeadline):
                            with runtime.sqlite_deadline(db, runtime.time.monotonic() + (0.05 if failure == 'sql_work' else 1)):
                                if failure == 'sql_work':
                                    with model.request(db, strict_readonly=True):
                                        self.assertIsNotNone(runtime.snapshot_character_names(db, False))
                                        db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
                                else:
                                    target, name = ((runtime, '_static_snapshot_version')
                                        if failure == 'entry_stamp' else (model, '_capture_path_ancestors'))
                                    with patch.object(target, name, side_effect=runtime.CatalogDeadline()):
                                        with model.request(db, strict_readonly=True):
                                            self.fail('expired strict setup yielded shared facts')
                        self.assert_released(db, prior)
                        self.assertIsNone(runtime._work_deadline.get())
                        self.assertEqual(runtime._sql_scopes.get(), ())
                        with self.assertRaises(sqlite3.DatabaseError):
                            db.execute('SELECT abs(-1)')
                        self.assertEqual(db.execute('SELECT 42').fetchone()[0], 42)
                    with closing(core.connect(fixture.path, readonly=True)) as fresh:
                        fresh.set_authorizer(prior)
                        with runtime.sqlite_deadline(fresh, runtime.time.monotonic() + 1):
                            with model.request(fresh, strict_readonly=True):
                                self.assertIsNotNone(runtime.snapshot_character_names(fresh, False))
                        self.assert_released(fresh, prior)
                        self.assertIsNone(runtime._work_deadline.get())
                        self.assertEqual(runtime._sql_scopes.get(), ())

    def test_release_alias_specific_file_parent_and_wal_guards_are_fresh(self):
        fixture = self.fixture()
        original = collector_release_alias.BINDINGS_PATH.read_bytes()
        for label in ('native', 'loaded'):
            for mutation in ('final_symlink', 'parent_symlink', 'wal_symlink_empty', 'wal_nonempty'):
                with self.subTest(model=label, mutation=mutation):
                    parent = fixture.base / ('alias-only-' + label + '-' + mutation)
                    parent.mkdir()
                    alias = parent / 'aliases.json'; alias.write_bytes(original)
                    with patch.object(collector_release_alias, 'BINDINGS_PATH', alias):
                        with closing(core.connect(fixture.path, readonly=True)) as source:
                            if label == 'native':
                                model = runtime.CatalogReadModel(source)
                            else:
                                directory = fixture.base / ('alias-artifact-' + mutation)
                                receipt = artifact.write(source, fixture.manifest, directory)
                                model, _, _ = artifact.load(source, directory, fixture.manifest,
                                    expected_seal_sha256=receipt['seal_sha256'])

                        @contextmanager
                        def changed_alias():
                            if mutation == 'parent_symlink':
                                saved = parent.with_name(parent.name + '-moved')
                                parent.rename(saved); parent.symlink_to(saved, target_is_directory=True)
                                try:
                                    yield
                                finally:
                                    parent.unlink(); saved.rename(parent)
                            elif mutation == 'final_symlink':
                                saved = parent / 'original-aliases.json'
                                alias.rename(saved); alias.symlink_to(saved)
                                try:
                                    yield
                                finally:
                                    alias.unlink(); saved.rename(alias)
                            else:
                                wal = Path(str(alias) + '-wal')
                                self.assertFalse(wal.exists())
                                if mutation == 'wal_symlink_empty':
                                    empty = parent / 'empty-alias-wal-target'; empty.touch()
                                    wal.symlink_to(empty)
                                else:
                                    wal.write_bytes(b'synthetic alias WAL identity change')
                                try:
                                    yield
                                finally:
                                    wal.unlink()

                        with closing(core.connect(fixture.path, readonly=True)) as db:
                            observed = []
                            try:
                                with model.request(db, strict_readonly=True):
                                    self.assertIsNotNone(runtime.snapshot_release_aliases(db, ['ja']))
                                    observed.append('warmed')
                                    with changed_alias():
                                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                                            runtime.snapshot_release_aliases(db, ['ja'])
                                        observed.append('denied')
                            except runtime.CatalogSnapshotChanged:
                                # Restoring a renamed file may also change its
                                # exit metadata; the lookup denial is required
                                # independently by the inner assertion above.
                                pass
                            self.assertEqual(observed, ['warmed', 'denied'])
                            self.assert_released(db)


if __name__ == '__main__':
    unittest.main()

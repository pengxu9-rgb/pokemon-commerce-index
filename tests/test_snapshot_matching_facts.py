"""Typed text membership, native matching and unsafe snapshot rejection."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime, collector_discovery as discovery
from pokemon_index import collector_release_alias
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class SnapshotMatchingFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with closing(core.connect(self.path, readonly=True)) as db:
            self.model = runtime.CatalogReadModel(db)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def test_text_map_preserves_sqlite_in_affinity_and_storage_without_cast(self):
        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
            db.execute('CREATE TABLE collector_snapshot.facets '
                       '(card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)')
            ids = ('25', '025', '25e0', 'float', 'null', 'upper', 'UPPER', b'25', b'\xff')
            for i, cid in enumerate(ids):
                db.execute('INSERT INTO card VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (cid, 'ja', 'TEST', str(i), 'normal', 'Synthetic', '',
                            'synthetic', 'synthetic', 0, 1, '{}'))
            values = [(25, '25'), ('25', 25), ('25', 25.0), ('025', '025'),
                      ('25e0', '25e0'), ('float', 25.9), ('float', '25.9'),
                      ('null', None), ('upper', '25foo'), ('UPPER', '２５'),
                      (b'25', '25'), (b'25', b'25'), (b'\xff', '25'),
                      ('25', '26'), ('25', '25')]
            for cid, value in values:
                db.execute('INSERT INTO collector_snapshot.facets VALUES (?,?,?,?,?)',
                           (cid, 'dex_id', value, 'synthetic', 'synthetic'))
            index = runtime.CatalogReadModel._build_text_dex_card_ids(db)
            for operands in (('25',), ('025',), ('25e0',), ('25.9',), ('25foo',),
                             ('２５',), ('26',), ('25', '26', '25'), ('missing',)):
                marks = ','.join('?' for _ in operands)
                expected = {row[0] for row in db.execute(
                    "SELECT c.card_id FROM main.card c WHERE c.card_id IN "
                    "(SELECT f.card_id FROM collector_snapshot.facets f "
                    "WHERE f.facet_type='dex_id' AND f.value IN (" + marks + '))', operands)}
                actual = {cid for value in operands for cid in index.get(value, ())}
                self.assertEqual(actual, expected, operands)
            self.assertNotIn('null', index.get('0', ()))
            self.assertNotIn('float', index.get('25', ()))
            self.assertIn(b'\xff', index['25'])
            with self.assertRaises(TypeError):
                index['25'] = frozenset()

    def test_native_character_release_and_alias_matching_is_preserved(self):
        texts = ['Japanese Pikachu cards', '日本語のピカチュウ', 'Mew ex',
                 'Pikachu EX', 'Nidoran♀', 'Nidoran♂', 'Japanese FIX cards',
                 'Pikachu family cards', 'English Pikachu cards by Alpha']
        def evaluate(db):
            return [(discovery._compute_character_mentions(db, discovery._norm(text),
                         maximal=maximal, current_only=current),
                     discovery._release_name_mentions(db, discovery._norm(text), ['ja', 'en']),
                     discovery.reviewed_release_interpretations(db, text, ['ja', 'en']))
                    for text in texts for maximal in (False, True) for current in (False, True)]
        with closing(core.connect(self.path, readonly=True)) as db:
            expected = evaluate(db)
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            self.assertEqual(evaluate(db), expected)
            self.assertEqual(runtime.card_scan(db, narrow_ids=False), 'card c')
            self.assertEqual(runtime.card_scan(db, narrow_ids=True),
                             'main.card AS c INDEXED BY sqlite_autoindex_card_1')

    def test_large_or_nontext_operands_retain_native_sql(self):
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            for values in ((), (None,), (25,), (25.0,), (True,), (b'25',), tuple(map(str, range(33)))):
                self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, values))
            self.assertIsInstance(runtime.snapshot_text_dex_card_ids(db, ('25',)), frozenset)
            with patch.object(runtime.CatalogReadModel, 'MAX_DEX_QUERY_IDS', 1):
                self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, ('25',)))
        with closing(core.connect(self.path, readonly=True)) as db:
            self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, ('25',)))
            self.assertIsNone(runtime.snapshot_character_names(db, True))
            self.assertIsNone(runtime.snapshot_release_names(db, ['ja']))
            self.assertIsNone(runtime.snapshot_release_aliases(db, ['ja']))
            self.assertEqual(runtime.card_scan(db, narrow_ids=True), 'card c')

    def test_all_new_static_readers_reject_mutable_or_shadowed_active_scope(self):
        readers = [lambda db: runtime.snapshot_text_dex_card_ids(db, ('25',)),
                   lambda db: runtime.snapshot_character_names(db, True),
                   lambda db: runtime.snapshot_release_names(db, ['ja']),
                   lambda db: runtime.snapshot_release_aliases(db, ['ja']),
                   lambda db: runtime.card_scan(db, narrow_ids=True)]
        for shadow in (False, True):
            for reader in readers:
                with self.subTest(shadow=shadow, reader=reader), closing(
                        core.connect(self.path, readonly=True)) as db, self.assertRaises(runtime.CatalogSnapshotChanged), self.model.request(db):
                    db.execute('PRAGMA query_only=OFF')
                    if shadow:
                        db.execute('CREATE TEMP VIEW character_family_member AS SELECT 999 dex_id')
                        db.execute('PRAGMA query_only=ON')
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        reader(db)

    def test_reviewed_alias_source_file_drift_rejects_cached_matching(self):
        alias_path = Path(self.tmp.name) / 'release-aliases.json'
        alias_path.write_bytes(collector_release_alias.BINDINGS_PATH.read_bytes())
        with patch.object(collector_release_alias, 'BINDINGS_PATH', alias_path):
            with closing(core.connect(self.path, readonly=True)) as db:
                model = runtime.CatalogReadModel(db)
            # Even equivalent JSON bytes with a different file identity require
            # rebuilding; a cached source rendering cannot survive file drift.
            alias_path.write_bytes(alias_path.read_bytes() + b'\n')
            with closing(core.connect(self.path, readonly=True)) as db, self.assertRaises(
                    runtime.CatalogSnapshotChanged):
                with model.request(db):
                    self.fail('stale source rendering accepted')

    def test_matching_fact_count_and_byte_bounds_do_not_publish_partial_model(self):
        fields = ('MAX_CHARACTER_NAME_ROWS', 'MAX_CHARACTER_NAME_BYTES',
                  'MAX_RELEASE_NAME_ROWS', 'MAX_RELEASE_NAME_BYTES', 'MAX_RELEASE_ALIAS_BYTES')
        for field in fields:
            with self.subTest(field=field), closing(core.connect(self.path, readonly=True)) as db:
                with patch.object(runtime.CatalogReadModel, field, 1):
                    with self.assertRaisesRegex(ValueError, 'matching facts'):
                        runtime.CatalogReadModel(db)
                self.assertIsNone(runtime._snapshot_scope.get())


if __name__ == '__main__':
    unittest.main()

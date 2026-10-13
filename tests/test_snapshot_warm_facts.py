"""Exact static match facts and bounded SQLite scan planning, synthetic only."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime, collector_discovery as discovery
from pokemon_index import collector_release_alias
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class SnapshotWarmFactsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        with closing(core.connect(self.path, readonly=True)) as db:
            self.model = runtime.CatalogReadModel(db)

    def test_text_membership_preserves_sqlite_storage_id_affinity_and_binary_collation(self):
        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
            db.execute('CREATE TABLE collector_snapshot.facets(card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)')
            ids = ['25', '025', '25e0', 'upper', 'UPPER', b'25', b'025', 'missing']
            for i, cid in enumerate(ids):
                db.execute('INSERT INTO card VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (cid, 'ja', 'RAW', str(i), 'normal', 'Synthetic', '', 'synthetic', 'synthetic', 0, 1, '{}'))
            values = [None, 0, 25, 25.9, '25', '025', '25e0', '25.9', '25foo', 'foo', '', b'25', -1,
                      '9223372036854775808', '-9223372036854775809', 'UPPER', 'upper']
            for i, value in enumerate(values):
                db.execute('INSERT INTO collector_snapshot.facets VALUES (?,?,?,?,?)',
                    (ids[i % 7], 'dex_id', value, 'synthetic', 'synthetic'))
            # A numeric facet ID must retain native BLOB/column-IN affinity;
            # replacing it with Python str(25) would manufacture a membership.
            db.execute('INSERT INTO collector_snapshot.facets VALUES (?,?,?,?,?)', (25, 'dex_id', '25', 'synthetic', 'synthetic'))
            db.execute('INSERT INTO collector_snapshot.facets VALUES (?,?,?,?,?)', ('025', 'dex_id', '25', 'synthetic', 'synthetic'))
            db.commit()
            index = runtime.CatalogReadModel._build_text_dex_card_ids(db)
            for operands in [('25',), ('025',), ('25e0',), ('UPPER',), ('upper',), ('25', '25', 'foo'), ('',), ('missing',)]:
                native = list(db.execute("SELECT c.card_id,typeof(c.card_id) FROM main.card c WHERE c.card_id IN (SELECT f.card_id FROM collector_snapshot.facets f WHERE f.facet_type='dex_id' AND f.value IN (" + ','.join('?' for _ in operands) + ')) ORDER BY c.card_id', operands))
                candidates = frozenset(cid for v in operands for cid in index.get(v, ()))
                actual = list(db.execute('SELECT c.card_id,typeof(c.card_id) FROM main.card c INDEXED BY sqlite_autoindex_card_1 WHERE c.card_id IN (' + ','.join('?' for _ in candidates) + ') ORDER BY c.card_id', tuple(candidates))) if candidates else []
                self.assertEqual(native, actual, operands)
            self.assertNotIn('missing', index.get('25', ()))
            self.assertNotIn('25', index['25'])
            self.assertIn('025', index['25'])
            with self.assertRaises(TypeError): index['25'] = frozenset()

    def test_text_map_never_uses_cast_and_abstains_on_nontext_or_unbounded_operands(self):
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            with patch.object(runtime, 'snapshot_cast_dex_card_ids', side_effect=AssertionError('CAST used')):
                self.assertIsInstance(runtime.snapshot_text_dex_card_ids(db, ('25',)), frozenset)
            for operands in [(), (None,), (25,), (25.0,), (True,), (b'25',), tuple(str(i) for i in range(33))]:
                self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, operands))
            with patch.object(runtime.CatalogReadModel, 'MAX_DEX_QUERY_IDS', 0):
                self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, ('25',)))
        with closing(core.connect(self.path, readonly=True)) as db:
            self.assertIsNone(runtime.snapshot_text_dex_card_ids(db, ('25',)))

    def test_primary_key_hint_only_inside_trusted_exact_id_path_preserves_full_order(self):
        with closing(core.connect(self.path, readonly=True)) as db:
            ids = tuple(r[0] for r in db.execute('SELECT card_id FROM card'))
            where = 'c.card_id IN (' + ','.join('?' for _ in ids) + ')'
            expected = [dict(row) for row in discovery._rows(db, where, ids)]
            self.assertEqual(runtime.card_scan(db, narrow_ids=True), 'card c')
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            self.assertEqual(runtime.card_scan(db), 'card c')
            self.assertIn('INDEXED BY sqlite_autoindex_card_1', runtime.card_scan(db, narrow_ids=True))
            self.assertEqual([dict(row) for row in discovery._rows(db, where, ids, narrow_ids=True)], expected)

    def test_matching_facts_keep_unicode_nested_names_qualifiers_and_release_scope(self):
        texts = ['ピカチュウ', 'ミュウとミュウツー', 'mew and mewtwo', 'pikachu ex and pikachu',
                 "Rocket’s Pikachu", 'alolan pikachu', 'pikachu VMAX', 'pikachu EX', 'synthetic unknown',
                 'eevee family cards', 'Japanese FIX cards', 'English FIX cards']
        with closing(core.connect(self.path, readonly=True)) as db:
            expected = [(discovery._compute_character_mentions(db, discovery._norm(text), maximal=maximum, current_only=current),
                         discovery._release_name_mentions(db, discovery._norm(text), languages))
                        for text in texts for maximum in (False, True) for current in (False, True)
                        for languages in (['ja'], ['en'], ['ja', 'en'])]
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            actual = [(discovery._compute_character_mentions(db, discovery._norm(text), maximal=maximum, current_only=current),
                       discovery._release_name_mentions(db, discovery._norm(text), languages))
                      for text in texts for maximum in (False, True) for current in (False, True)
                      for languages in (['ja'], ['en'], ['ja', 'en'])]
            self.assertEqual(actual, expected)

    def test_release_proofs_are_detached_connection_bound_and_source_file_drift_rejects(self):
        binding = Path(self.tmp.name) / 'release.json'
        binding.write_bytes(collector_release_alias.BINDINGS_PATH.read_bytes())
        with patch.object(collector_release_alias, 'BINDINGS_PATH', binding):
            with closing(core.connect(self.path, readonly=True)) as db:
                model = runtime.CatalogReadModel(db)
            model._release_aliases_json = '[{"language":"ja","alias":"synthetic","proof":["original"]}]'
            with closing(core.connect(self.path, readonly=True)) as a, closing(core.connect(self.path, readonly=True)) as b, model.request(a):
                proof = runtime.snapshot_release_aliases(a, ['ja']); proof[0]['proof'].append('changed')
                self.assertEqual(runtime.snapshot_release_aliases(a, ['ja'])[0]['proof'], ['original'])
                self.assertIsNone(runtime.snapshot_release_aliases(b, ['ja']))
            binding.write_bytes(binding.read_bytes() + b'\n')
            with closing(core.connect(self.path, readonly=True)) as db, self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.request(db): self.fail('source drift published')

    def test_mutable_temp_and_rollback_scopes_cannot_serve_static_names_or_ids(self):
        readers = [lambda db: runtime.snapshot_text_dex_card_ids(db, ('25',)),
                   lambda db: runtime.snapshot_character_names(db, False),
                   lambda db: runtime.snapshot_release_names(db, ['ja']),
                   lambda db: runtime.snapshot_release_aliases(db, ['ja']),
                   lambda db: runtime.card_scan(db, narrow_ids=True)]
        for mutation in ['transaction', 'rollback', 'temp_table', 'temp_view']:
            for reader in readers:
                with self.subTest(mutation=mutation), closing(core.connect(self.path)) as db, self.assertRaises(runtime.CatalogSnapshotChanged), self.model.request(db):
                    db.execute('PRAGMA query_only=OFF')
                    if mutation in ['transaction', 'rollback']:
                        db.execute("UPDATE card SET name='Changed'")
                        if mutation == 'rollback': db.rollback(); db.execute('PRAGMA query_only=ON')
                    else:
                        db.execute('CREATE TEMP ' + ('TABLE shadow(x)' if mutation == 'temp_table' else 'VIEW shadow AS SELECT 1 x'))
                        db.commit(); db.execute('PRAGMA query_only=ON')
                    with self.assertRaises(runtime.CatalogSnapshotChanged): reader(db)
                    db.rollback()
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE card SET name='Changed'")
            self.assertIsNone(runtime.snapshot_character_names(db, False)); db.rollback()

    def test_fact_size_bounds_fail_without_publishing_request_scope(self):
        for field in ['MAX_CHARACTER_NAME_ROWS', 'MAX_CHARACTER_NAME_BYTES', 'MAX_RELEASE_NAME_ROWS',
                      'MAX_RELEASE_NAME_BYTES', 'MAX_RELEASE_ALIAS_BYTES']:
            with self.subTest(field=field), closing(core.connect(self.path, readonly=True)) as db, patch.object(runtime.CatalogReadModel, field, 0):
                with self.assertRaisesRegex(ValueError, 'matching facts'): runtime.CatalogReadModel(db)
                self.assertIsNone(runtime._snapshot_scope.get())


if __name__ == '__main__': unittest.main()

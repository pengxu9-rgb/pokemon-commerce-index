"""Lookup indexes preserve live provenance, withdrawal and collision checks."""
import copy
import unittest
from contextlib import closing

from pokemon_index import catalog_locale, catalog_locale_indexes, collector_runtime, core
import test_international_coverage as fixture_module


class LocaleScaleIndexesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.InternationalCoverageTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.db = self.fixture.db
        catalog_locale_indexes.import_manifest_evidence(self.db, [catalog_locale_indexes.RECORD])

    def indexes(self):
        return {row['name']: row['sql'] for row in self.db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='index'")}

    def remove_indexes(self):
        for name in ('catalog_locale_evidence_card', 'catalog_source_mapping_card'):
            self.db.execute('DROP INDEX ' + name)

    def test_point_lookups_use_indexes_at_thousand_record_scale(self):
        records = []
        for number in range(1, 2001):
            seed = dict(self.fixture.seed, collector_number=f'{number:04d}/2000')
            core.import_cards(self.db, [seed])
            cid = core.card_id('ja', 'FIX', seed['collector_number'], 'normal')
            records.append((f'evidence:{number}', cid, '{}'))
            self.db.execute('INSERT INTO catalog_source_mapping VALUES (?,?,?,?,?,?,?)',
                ('test', 'ja', 'ZZ', 'FIX', f'test/{number}', 'normal', cid))
        self.db.executemany('INSERT INTO catalog_locale_evidence VALUES (?,?,?)', records)
        for table, index in [('catalog_locale_evidence', 'catalog_locale_evidence_card'),
                             ('catalog_source_mapping', 'catalog_source_mapping_card')]:
            plan = ' '.join(row['detail'] for row in self.db.execute(
                'EXPLAIN QUERY PLAN SELECT * FROM ' + table + ' WHERE card_id=?', (records[-1][1],)))
            self.assertIn(index, plan)
            self.assertNotIn('SCAN ' + table, plan)
            self.assertEqual(len(self.db.execute('SELECT * FROM ' + table + ' WHERE card_id=?',
                                                 (records[-1][1],)).fetchall()), 1)

    def test_explicit_index_import_preserves_rows_search_and_legacy_init_schema(self):
        catalog_locale.import_evidence(self.db, [self.fixture.row])
        self.remove_indexes()
        tables = [r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        old = {table: [tuple(r) for r in self.db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
               for table in tables}
        before = core.catalog_search_internal(self.db, 'Ｐｉｋａｃｈｕ ja FIX 001/100')
        core.init_db(self.db)
        self.assertFalse({'catalog_locale_evidence_card', 'catalog_source_mapping_card'} & set(self.indexes()))
        self.assertEqual(catalog_locale_indexes.import_manifest_evidence(self.db, [catalog_locale_indexes.RECORD]), 2)
        self.assertTrue({'catalog_locale_evidence_card', 'catalog_source_mapping_card'} <= set(self.indexes()))
        self.assertEqual(old, {table: [tuple(r) for r in self.db.execute('SELECT * FROM ' + table + ' ORDER BY rowid')]
                              for table in tables})
        self.assertEqual(before, core.catalog_search_internal(self.db, 'Ｐｉｋａｃｈｕ ja FIX 001/100'))
        self.assertEqual(catalog_locale_indexes.import_manifest_evidence(self.db, [catalog_locale_indexes.RECORD]), 0)
        self.assertEqual(before, core.catalog_search_internal(self.db, 'Ｐｉｋａｃｈｕ ja FIX 001/100'))

    def test_indexes_never_cache_withdrawn_stale_or_colliding_evidence(self):
        catalog_locale.import_evidence(self.db, [self.fixture.row])
        for indexed in (True, False):
            if not indexed:
                self.remove_indexes()
            self.assertTrue(catalog_locale.has_current_alias(self.db, self.fixture.cid, [self.fixture.alias]))
            self.db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'")
            self.assertFalse(catalog_locale.has_current_alias(self.db, self.fixture.cid, [self.fixture.alias]))
            self.db.execute("UPDATE bilingual_concept_revision SET status='approved'")
            self.db.execute("UPDATE card SET provenance='test:stale' WHERE card_id=?", (self.fixture.cid,))
            self.assertFalse(catalog_locale.has_current_alias(self.db, self.fixture.cid, [self.fixture.alias]))
            self.db.execute('UPDATE card SET provenance=? WHERE card_id=?',
                            (self.fixture.seed['provenance'], self.fixture.cid))
            changed = copy.deepcopy(self.fixture.row)
            changed['source']['region'] = 'KR'
            self.fixture.sign(changed)
            self.assertEqual(catalog_locale.import_evidence(self.db, [changed])['quarantined'], 1)
            self.assertEqual(self.db.execute('SELECT count(*) FROM catalog_source_mapping').fetchone()[0], 1)

    def test_manifest_cannot_supply_arbitrary_sql_unique_or_partial_indexes(self):
        self.remove_indexes()
        for mutation in ('unique', 'name', 'columns'):
            record = copy.deepcopy(catalog_locale_indexes.RECORD)
            record['indexes'][0][mutation] = True if mutation == 'unique' else ['other_column'] if mutation == 'columns' else 'unsafe'
            with self.assertRaises(ValueError):
                catalog_locale_indexes.import_manifest_evidence(self.db, [record])
        with self.assertRaises(ValueError):
            catalog_locale_indexes.import_manifest_evidence(self.db, [dict(schema='test', sql='DROP TABLE card')])
        self.db.execute('CREATE INDEX catalog_locale_evidence_card ON catalog_locale_evidence(evidence_id)')
        with self.assertRaises(ValueError):
            catalog_locale_indexes.import_manifest_evidence(self.db, [catalog_locale_indexes.RECORD])

    def test_read_model_accepts_both_exact_indexes_and_rejects_partial_or_altered(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.sqlite3'
            with closing(core.connect(path)) as db:
                core.init_db(db)
                core.import_cards(db, [self.fixture.seed])
                db.commit()
                with closing(core.connect(path, readonly=True)) as reader:
                    collector_runtime.CatalogReadModel(reader)
                catalog_locale_indexes.import_manifest_evidence(db, [catalog_locale_indexes.RECORD])
                db.commit()
                with closing(core.connect(path, readonly=True)) as reader:
                    collector_runtime.CatalogReadModel(reader)
                db.execute('DROP INDEX catalog_source_mapping_card'); db.commit()
                with closing(core.connect(path, readonly=True)) as reader:
                    with self.assertRaises(collector_runtime.CatalogReadModelUnsupported):
                        collector_runtime.CatalogReadModel(reader)
                db.execute('CREATE INDEX catalog_source_mapping_card ON catalog_source_mapping(provider)'); db.commit()
                with closing(core.connect(path, readonly=True)) as reader:
                    with self.assertRaises(collector_runtime.CatalogReadModelUnsupported):
                        collector_runtime.CatalogReadModel(reader)


if __name__ == '__main__':
    unittest.main()

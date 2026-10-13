"""Alias memoization retains native checks and live mutation/rollback isolation."""
import tempfile,unittest
from pathlib import Path
from contextlib import closing
from pokemon_index import core,catalog_locale,collector_runtime,catalog_locale_indexes
import test_international_coverage as fixture_module


class LocaleRequestCacheTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.InternationalCoverageTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown);self.db=self.fixture.db
        catalog_locale_indexes.import_manifest_evidence(self.db,[catalog_locale_indexes.RECORD]);catalog_locale.import_evidence(self.db,[self.fixture.row])

    def test_thousand_calls_share_validated_map_but_return_fresh_values(self):
        traces=[];self.db.set_trace_callback(traces.append)
        @collector_runtime.catalog_request
        def probe(db):
            for number in range(1000):
                found=catalog_locale.search_aliases(db,set_code='fix')
                self.assertEqual(found,{self.fixture.cid:['Pikachu']})
                found[self.fixture.cid].append('poison');found['other']=['poison']
        probe(self.db)
        self.assertEqual(sum(s.startswith('SELECT e.record_json FROM catalog_locale_evidence') for s in traces),1)
        probe(self.db)
        self.assertEqual(sum(s.startswith('SELECT e.record_json FROM catalog_locale_evidence') for s in traces),2)

    def test_transaction_rollback_withdrawal_and_mapping_mutations_invalidate(self):
        @collector_runtime.catalog_request
        def probe(db):
            self.assertTrue(catalog_locale.search_aliases(db))
            db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'")
            self.assertFalse(catalog_locale.search_aliases(db));db.rollback()
            self.assertTrue(catalog_locale.search_aliases(db))
            db.execute("UPDATE card SET provenance='synthetic:stale'")
            self.assertFalse(catalog_locale.search_aliases(db));db.rollback()
            self.assertTrue(catalog_locale.search_aliases(db))
            db.execute('SAVEPOINT fixture')
            db.execute("UPDATE catalog_source_mapping SET region='KR'")
            self.assertFalse(catalog_locale.search_aliases(db));db.execute('ROLLBACK TO fixture');db.execute('RELEASE fixture')
            self.assertTrue(catalog_locale.search_aliases(db))
        probe(self.db)

    def test_external_committed_write_invalidates_readonly_connection_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'snapshot.sqlite3'
            with closing(core.connect(path)) as writer:self.db.backup(writer)
            with closing(core.connect(path,readonly=True)) as reader,closing(core.connect(path)) as writer:
                @collector_runtime.catalog_request
                def probe(db):
                    self.assertTrue(catalog_locale.search_aliases(db))
                    writer.execute("UPDATE bilingual_concept_revision SET status='withdrawn'");writer.commit()
                    self.assertFalse(catalog_locale.search_aliases(db))
                    writer.execute("UPDATE bilingual_concept_revision SET status='approved'");writer.commit()
                    self.assertTrue(catalog_locale.search_aliases(db))
                probe(reader)

    def test_native_query_results_equal_uncached_queries_without_stale_evidence(self):
        query='Ｐｉｋａｃｈｕ ja FIX 001/100';expected=core.catalog_search_internal(self.db,query)
        @collector_runtime.catalog_request
        def probe(db):
            for unused in range(20):self.assertEqual(core.catalog_search_internal(db,query),expected)
            db.execute("UPDATE bilingual_concept_revision SET status='withdrawn'");db.commit()
            self.assertEqual(core.catalog_search_internal(db,query)['total'],0)
        probe(self.db)
        self.assertEqual(core.catalog_search_internal(self.db,query)['total'],0)


if __name__=='__main__':unittest.main()

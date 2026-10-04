"""Catalog-only acceleration equivalence, lifetime and session isolation."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pokemon_index import core,collector_runtime as runtime,collector_journey,collector_discovery
from pokemon_index import collector_character_affiliation as affiliation
from pokemon_index.cli import create_server
from scripts.rehearse_collector_recommendations import SUITE,create_fixture


class CatalogReadModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'catalog.sqlite3'
        self.suite=json.loads(SUITE.read_text());create_fixture(self.path,self.suite)
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with closing(core.connect(self.path,readonly=True)) as db:
            self.model=runtime.CatalogReadModel(db)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._catalog_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)
        self.tmp.cleanup()

    def rows(self,db,table):
        cols=self.model.COLUMNS
        return Counter(tuple(r) for r in db.execute('SELECT '+','.join(cols)+','+
            ','.join('typeof('+c+')' for c in cols)+' FROM '+table))

    def test_image_has_only_facets_indexes_and_preserves_typed_multiset_and_affinities(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertEqual(self.rows(db,'main.discovery_card_facet'),self.rows(db,'temp.discovery_card_facet'))
            self.assertEqual([tuple(r) for r in db.execute('PRAGMA main.table_info(discovery_card_facet)')],
                             [tuple(r) for r in db.execute('PRAGMA temp.table_info(discovery_card_facet)')])
            self.assertEqual({tuple(r) for r in db.execute("SELECT type,name FROM collector_snapshot.sqlite_master")},
                {('table','facets'),('index','facet_lookup'),('index','card_lookup')})
            for value in ('0313','313',313,'25',25,None):
                for operator in ('=','IS'):
                    q='SELECT card_id FROM {} WHERE value '+operator+' ? ORDER BY card_id'
                    self.assertEqual(list(db.execute(q.format('main.discovery_card_facet'),(value,))),
                                     list(db.execute(q.format('temp.discovery_card_facet'),(value,))))

    def test_snapshot_and_fresh_clone_are_readonly(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)
            for sql in ["UPDATE main.card SET name='changed'",'DELETE FROM collector_snapshot.facets',
                        'CREATE TEMP TABLE forbidden(value)']:
                with self.assertRaises(sqlite3.OperationalError):db.execute(sql)

    def test_mutating_expendable_clone_cannot_change_next_request_or_image(self):
        original=hashlib.sha256(self.model._image).hexdigest()
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            db.execute('PRAGMA query_only=OFF');db.execute('DELETE FROM collector_snapshot.facets');db.commit()
            self.assertEqual(db.execute('SELECT count(*) FROM discovery_card_facet').fetchone()[0],0)
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertGreater(db.execute('SELECT count(*) FROM discovery_card_facet').fetchone()[0],0)
            self.assertEqual(self.rows(db,'main.discovery_card_facet'),self.rows(db,'temp.discovery_card_facet'))
        self.assertEqual(hashlib.sha256(self.model._image).hexdigest(),original)

    def test_all_frozen_recommendation_prefixes_equal_unaccelerated_results(self):
        for journey in self.suite['journeys']:
            turns=[]
            for step in journey['steps']:
                turns.append(step['action']);payload={'turns':copy.deepcopy(turns),'limit':self.suite['limit']}
                with self.subTest(journey=journey['id'],turn=len(turns)):
                    outputs=[]
                    for accelerated in (False,True):
                        with closing(core.connect(self.path,readonly=True)) as db:
                            def run():
                                try:return ('result',collector_journey.replay(db,payload,revision='a'*64))
                                except ValueError as exc:return ('error',str(exc))
                            if accelerated:
                                with self.model.request(db):outputs.append(run())
                            else:outputs.append(run())
                    self.assertEqual(outputs[0],outputs[1]);self.assertEqual(payload['turns'],turns)

    def test_concurrent_distinct_sessions_keep_exact_baselines_and_immutable_inputs(self):
        payloads=[{'turns':[{'type':'ask','question':q}]} for q in
                  ['Recommend Japanese Pikachu cards','Recommend English Mew cards',
                   'Recommend cards by Alpha','Recommend cards by Beta']]
        with closing(core.connect(self.path,readonly=True)) as db:
            expected=[collector_journey.replay(db,p,revision='a'*64) for p in payloads]
        barrier=threading.Barrier(4)
        def run(index):
            payload=copy.deepcopy(payloads[index]);saved=copy.deepcopy(payload)
            with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
                barrier.wait(2);out=collector_journey.replay(db,payload,revision='a'*64)
            self.assertEqual(payload,saved);self.assertIsNone(runtime._snapshot_scope.get())
            return out
        with ThreadPoolExecutor(4) as executor:self.assertEqual(list(executor.map(run,range(4))),expected)

    def test_affiliation_proofs_are_detached_and_only_shared_on_bound_connection(self):
        self.model._affiliations_json='{"synthetic":{"reason":{"proof":["original"]}}}'
        with closing(core.connect(self.path,readonly=True)) as a,closing(core.connect(self.path,readonly=True)) as b:
            with self.model.request(a):
                first=runtime.snapshot_affiliations(a);first['synthetic']['reason']['proof'].append('changed')
                self.assertEqual(runtime.snapshot_affiliations(a)['synthetic']['reason']['proof'],['original'])
                self.assertIsNone(runtime.snapshot_affiliations(b))
            self.assertIsNone(runtime.snapshot_affiliations(a))

    def test_vocabulary_cache_is_immutable_exact_sql_and_connection_bound(self):
        with closing(core.connect(self.path,readonly=True)) as a,closing(core.connect(self.path,readonly=True)) as b:
            sql=runtime.VOCABULARY_SQL['artists']
            with self.model.request(a):
                cached=runtime.vocabulary(a,'artists',sql)
                self.assertIs(cached,self.model._vocabularies['artists'])
                self.assertIsNot(runtime.vocabulary(b,'artists',sql),cached)
                self.assertEqual(tuple(tuple(r) for r in runtime.vocabulary(a,'artists',"SELECT 'custom'")),(('custom',),))
                with self.assertRaises(TypeError):self.model._vocabularies['artists']=()
                with self.assertRaises(TypeError):cached[0][0]='changed'

    def test_other_database_cannot_use_the_image(self):
        other=Path(self.tmp.name)/'other.sqlite3';create_fixture(other,self.suite)
        with closing(core.connect(other,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.model.request(db):self.fail('wrong catalog accepted')

    def test_exception_and_expired_budget_restore_context_and_allow_recovery(self):
        with closing(core.connect(self.path,readonly=True)) as db:
            with self.assertRaisesRegex(ValueError,'expected'):
                with self.model.request(db):raise ValueError('expected')
        self.assertIsNone(runtime._snapshot_scope.get())
        with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogDeadline):
            with runtime.sqlite_deadline(db,time.monotonic()-1),self.model.request(db):pass
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            self.assertGreater(db.execute('SELECT count(*) FROM discovery_card_facet').fetchone()[0],0)

    def test_clone_step_cannot_buy_a_new_work_budget(self):
        original=self.model._alias
        def slow(db):time.sleep(.02);original(db)
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(self.model,'_alias',side_effect=slow):
            with self.assertRaises(runtime.CatalogDeadline):
                with runtime.sqlite_deadline(db,time.monotonic()+.005),self.model.request(db):
                    self.fail('expired cloning entered computation')

    def test_old_main_mutation_before_and_during_context_fails_closed(self):
        # This test intentionally changes a separate catalog, not the fixture.
        path=Path(self.tmp.name)/'mutable.sqlite3';create_fixture(path,self.suite)
        with closing(core.connect(path,readonly=True)) as db:model=runtime.CatalogReadModel(db)
        with closing(core.connect(path,readonly=True)) as reader:
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.request(reader):
                    with closing(core.connect(path)) as writer:
                        writer.execute("UPDATE card SET name='Changed'");writer.commit()
        with closing(core.connect(path,readonly=True)) as reader,self.assertRaises(runtime.CatalogSnapshotChanged):
            with model.request(reader):self.fail('stale catalog accepted')

    def test_low_image_quota_fails_without_changing_main_or_publishing_partial_model(self):
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(runtime.CatalogReadModel,'MAX_IMAGE_BYTES',4096):
            with self.assertRaises(sqlite3.OperationalError):runtime.CatalogReadModel(db)
        self.assertIsNone(runtime._snapshot_scope.get())

    def test_unsupported_acceleration_keeps_original_server_compatibility(self):
        with patch.object(runtime,'CatalogReadModel',side_effect=runtime.CatalogReadModelUnsupported()):
            with create_server(str(self.path),'127.0.0.1',0,True) as server:
                self.assertGreater(server.server_port,0)


class RequestMentionCacheTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE value(x)')
        self.db.execute("INSERT INTO value VALUES('before')");self.db.commit()
    def tearDown(self):
        self.db.close();self.assertIsNone(runtime._catalog_scope.get())
    def read(self,key=('question',True,False)):
        return runtime.request_mentions(self.db,key,lambda:tuple(self.db.execute('SELECT x FROM value')))
    def test_repeated_nested_lookups_reuse_immutable_values_only_within_one_request(self):
        @runtime.catalog_request
        def inner(db):return self.read()
        @runtime.catalog_request
        def outer(db):
            a=self.read();self.assertIs(a,inner(db));return a
        first=outer(self.db);self.assertIsNot(first,outer(self.db))
    def test_transaction_rollback_and_temp_schema_invalidate_matches(self):
        @runtime.catalog_request
        def run(db):
            self.assertEqual(self.read(),(('before',),))
            db.execute("UPDATE value SET x='temporary'");self.assertEqual(self.read(),(('temporary',),))
            db.rollback();self.assertEqual(self.read(),(('before',),))
            db.execute("CREATE TEMP VIEW value AS SELECT 'override' x")
            self.assertEqual(self.read(),(('override',),))
        run(self.db)
    def test_cache_is_bounded_and_cleared_after_error(self):
        @runtime.catalog_request
        def run(db):
            for i in range(100):self.read((str(i),True,False))
            self.assertEqual(len(runtime._catalog_scope.get()['mentions']),64)
            raise ValueError('expected')
        with self.assertRaises(ValueError):run(self.db)
    def test_custom_vocabulary_sql_does_not_create_unbounded_entries(self):
        @runtime.catalog_request
        def run(db):
            for i in range(100):
                self.assertEqual(runtime.vocabulary(db,'release_codes','SELECT '+str(i)),((i,),))
            self.assertEqual(len(runtime._catalog_scope.get()['rows']),3)
        run(self.db)
    def test_failed_computation_never_poisoned_a_later_lookup(self):
        @runtime.catalog_request
        def run(db):
            with self.assertRaises(ValueError):runtime.request_mentions(db,('q',True,False),lambda:(_ for _ in ()).throw(ValueError()))
            self.assertEqual(self.read(('q',True,False)),(('before',),))
        run(self.db)


if __name__=='__main__':unittest.main()

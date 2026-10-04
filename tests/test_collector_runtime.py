"""Deterministic resource, cache-isolation and real HTTP guard regressions."""
import concurrent.futures
import http.client
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch

from pokemon_index import collector_journey, collector_runtime as runtime, core
from pokemon_index.cli import create_server


class VocabularyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE value(x)')
        self.db.execute("INSERT INTO value VALUES('before')")
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def rows(self, db=None, sql='SELECT x FROM value'):
        return runtime.vocabulary(db or self.db, 'release_codes', sql)

    def test_nested_calls_reuse_rows_only_until_request_ends(self):
        @runtime.catalog_request
        def inner(db):return self.rows(db)
        @runtime.catalog_request
        def outer(db):
            first=self.rows(db)
            self.assertIs(first,inner(db))
            return first
        first=outer(self.db)
        self.assertEqual(first,(('before',),))
        self.assertIsNot(first,outer(self.db))
        self.assertIsNone(runtime._catalog_scope.get())

    def test_local_writes_and_main_and_temp_schema_changes_invalidate(self):
        @runtime.catalog_request
        def run(db):
            first=self.rows()
            db.execute("UPDATE value SET x='after'")
            self.assertEqual(self.rows(),(('after',),))
            db.execute("CREATE TEMP VIEW value AS SELECT 'temporary' AS x")
            self.assertEqual(self.rows(),(('temporary',),))
            db.execute('DROP VIEW temp.value')
            db.execute('ALTER TABLE value RENAME TO old_value')
            db.execute("CREATE VIEW value AS SELECT 'schema' AS x")
            self.assertEqual(self.rows(),(('schema',),))
            self.assertEqual(first,(('before',),))
        run(self.db)

    def test_external_commits_and_other_connections_are_not_shared(self):
        with tempfile.TemporaryDirectory() as directory:
            with closing(sqlite3.connect(Path(directory)/'db')) as a, closing(sqlite3.connect(Path(directory)/'db')) as b:
                a.execute('CREATE TABLE value(x)');a.execute("INSERT INTO value VALUES('first')");a.commit()
                @runtime.catalog_request
                def run(db):
                    first=self.rows(a)
                    self.assertIsNot(first,self.rows(b))
                    b.execute("UPDATE value SET x='second'");b.commit()
                    self.assertEqual(self.rows(a),(('second',),))
                run(a)

    def test_exception_restores_scope_and_unknown_keys_reject(self):
        @runtime.catalog_request
        def run(db):
            self.rows(db)
            raise ValueError('expected')
        with self.assertRaises(ValueError):run(self.db)
        self.assertIsNone(runtime._catalog_scope.get())
        with self.assertRaises(ValueError):runtime.vocabulary(self.db,'inventory','SELECT 1')

    def test_rollback_and_savepoint_rollback_do_not_retain_uncommitted_rows(self):
        @runtime.catalog_request
        def run(db):
            self.assertEqual(self.rows(),(('before',),))
            db.execute("UPDATE value SET x='uncommitted'")
            self.assertEqual(self.rows(),(('uncommitted',),))
            db.execute('SAVEPOINT temporary')
            db.execute("UPDATE value SET x='savepoint'")
            self.assertEqual(self.rows(),(('savepoint',),))
            db.execute('ROLLBACK TO temporary')
            self.assertEqual(self.rows(),(('uncommitted',),))
            db.rollback()
            self.assertEqual(self.rows(),(('before',),))
        run(self.db)



class AdmissionTests(unittest.TestCase):
    def wait_for(self, predicate):
        until=time.monotonic()+2
        while not predicate():
            if time.monotonic()>=until:self.fail('worker did not reach expected state')
            time.sleep(.001)

    def test_fifo_full_queue_and_exception_cleanup(self):
        gate=runtime.CatalogAdmission(queue_size=2,queue_wait=1)
        order=[]
        def worker(number):
            with gate.acquire():order.append(number)
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            with gate.acquire():
                first=executor.submit(worker,1);self.wait_for(lambda:len(gate._waiting)==1)
                second=executor.submit(worker,2);self.wait_for(lambda:len(gate._waiting)==2)
                with self.assertRaises(runtime.CatalogBusy):
                    with gate.acquire():self.fail('full queue accepted work')
            first.result();second.result()
        self.assertEqual(order,[1,2])
        with self.assertRaises(ValueError):
            with gate.acquire():raise ValueError('expected')
        with gate.acquire():pass
        self.assertEqual(gate._active,0);self.assertEqual(len(gate._waiting),0)

    def test_expired_waiter_is_removed_without_entering(self):
        gate=runtime.CatalogAdmission(queue_wait=.02)
        with gate.acquire():
            def worker():
                with self.assertRaises(runtime.CatalogBusy):
                    with gate.acquire():self.fail('expired waiter entered')
            with concurrent.futures.ThreadPoolExecutor(1) as executor:executor.submit(worker).result()
        self.assertFalse(gate._waiting)
        with gate.acquire():pass


class RuntimeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'catalog.sqlite3'
        with closing(core.connect(self.path)) as db:core.init_db(db)
        self.payload={'turns':[{'type':'ask','question':'What should I collect next?'}]}

    def tearDown(self):self.tmp.cleanup()

    @contextmanager
    def server(self,internal_catalog_api=True,**kwargs):
        with create_server(str(self.path),'127.0.0.1',0,internal_catalog_api,**kwargs) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:yield server
            finally:server.shutdown();thread.join(timeout=5)

    def call(self,server,route='/collector-journey'):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        try:
            if route=='/health' or route.startswith('/discover'):client.request('GET',route)
            else:client.request('POST',route,json.dumps(self.payload),{'Content-Type':'application/json'})
            response=client.getresponse()
            return response.status,dict(response.getheaders()),json.loads(response.read())
        finally:client.close()

    def test_busy_rejects_without_replay_health_bypasses_and_slot_recovers(self):
        entered=threading.Event();release=threading.Event();original=collector_journey.replay
        def hold(*args,**kwargs):
            entered.set();release.wait(2)
            return original(*args,**kwargs)
        with self.server(catalog_queue_size=0) as server, patch.object(collector_journey,'replay',side_effect=hold) as replay:
            with concurrent.futures.ThreadPoolExecutor(1) as executor:
                active=executor.submit(self.call,server)
                self.assertTrue(entered.wait(2))
                status,headers,body=self.call(server)
                self.assertEqual((status,body),(503,{'error':'catalog_busy'}))
                self.assertEqual(headers['Retry-After'],'1');self.assertEqual(replay.call_count,1)
                with patch('pokemon_index.cli.core.connect',side_effect=AssertionError('health opened DB')):
                    self.assertEqual(self.call(server,'/health')[0],200)
                release.set();self.assertEqual(active.result()[0],200)
            self.assertEqual(self.call(server)[0],200)

    def test_sql_deadline_is_explicit_and_connection_and_slot_are_released(self):
        def expensive(db,*args,**kwargs):
            db.execute('WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        with self.server(catalog_deadline=.03) as server:
            with patch.object(collector_journey,'replay',side_effect=expensive):
                status,headers,body=self.call(server)
            self.assertEqual((status,body),(504,{'error':'catalog_work_budget_exceeded'}))
            self.assertEqual(headers['X-Collector-Error'],'catalog_work_budget_exceeded')
            self.assertEqual(self.call(server)[0],200)

    def test_locked_catalog_setup_is_bounded_and_health_remains_live(self):
        with self.server() as server,closing(core.connect(self.path)) as writer:
            writer.execute('BEGIN EXCLUSIVE')
            started=time.monotonic();status,_,body=self.call(server)
            self.assertEqual(status,503);self.assertLess(time.monotonic()-started,1)
            self.assertEqual(body,{'error':'catalog_temporarily_unavailable'})
            self.assertEqual(self.call(server,'/health')[0],200)
            writer.rollback();self.assertEqual(self.call(server)[0],200)

    def test_catalog_change_cannot_be_served_under_old_startup_revision(self):
        with self.server() as server:
            with closing(core.connect(self.path)) as writer:
                writer.execute('CREATE TABLE changed(x)');writer.commit()
            status,headers,body=self.call(server)
            self.assertEqual((status,body),(503,{'error':'catalog_snapshot_changed'}))
            self.assertEqual(headers['X-Collector-Error'],'catalog_snapshot_changed')
            self.assertEqual(self.call(server,'/health')[0],200)

    def test_cold_wal_snapshot_accepts_readonly_sidecar_creation(self):
        with closing(core.connect(self.path)) as writer:writer.execute('PRAGMA journal_mode=WAL')
        with self.server() as server:
            for _ in range(3):self.assertEqual(self.call(server)[0],200)

    def test_non_internal_legacy_server_can_read_after_database_updates(self):
        with self.server(internal_catalog_api=False) as server:
            with closing(core.connect(self.path)) as writer:
                writer.execute('CREATE TABLE changed(x)');writer.commit()
            self.assertEqual(self.call(server,'/discover?q=unknown')[0],200)


if __name__=='__main__':unittest.main()

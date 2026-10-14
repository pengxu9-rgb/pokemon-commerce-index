"""Independent admission, cancellation, and parser-cache failure cases."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, nullcontext
import http.client
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pokemon_index import collector_runtime as runtime, collector_journey, core
from pokemon_index.cli import create_server


class ContinuationRuntimeReview(unittest.TestCase):
    def test_waiter_expiry_and_application_error_do_not_leak_capacity(self):
        admission = runtime.CatalogAdmission(workers=1, queue_size=1, queue_wait=.03)
        with admission.acquire():
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(self._try_acquire, admission)
                self.assertEqual(pending.result(timeout=2), 'busy')
        with self.assertRaisesRegex(RuntimeError, 'fixture failure'):
            with admission.acquire():
                raise RuntimeError('fixture failure')
        self.assertEqual(self._try_acquire(admission), 'accepted')

    @staticmethod
    def _try_acquire(admission):
        try:
            with admission.acquire():
                return 'accepted'
        except runtime.CatalogBusy:
            return 'busy'

    def test_full_queue_rejects_without_displacing_earlier_waiter(self):
        admission = runtime.CatalogAdmission(workers=1, queue_size=1, queue_wait=1)
        entered = threading.Event()
        released = threading.Event()
        def waiting():
            with admission.acquire():
                entered.set()
                self.assertTrue(released.wait(2))
        with ThreadPoolExecutor(max_workers=1) as executor:
            with admission.acquire():
                future = executor.submit(waiting)
                until = time.monotonic() + 1
                while not admission._waiting and time.monotonic() < until:
                    threading.Event().wait(.001)
                self.assertEqual(len(admission._waiting), 1)
                self.assertEqual(self._try_acquire(admission), 'busy')
                self.assertFalse(entered.is_set())
            self.assertTrue(entered.wait(1))
            released.set()
            future.result(timeout=2)
        self.assertEqual(self._try_acquire(admission), 'accepted')

    def test_sql_deadline_interrupt_cleans_progress_handler_and_admission(self):
        admission = runtime.CatalogAdmission(deadline=.025)
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaises(runtime.CatalogDeadline):
                with admission.acquire() as expires, runtime.sqlite_deadline(db, expires):
                    db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL '
                               'SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
            self.assertEqual(db.execute('SELECT 42').fetchone()[0], 42)
            with admission.acquire() as expires, runtime.sqlite_deadline(db, expires):
                self.assertEqual(db.execute('SELECT 7').fetchone()[0], 7)

    def test_non_deadline_sql_error_retains_type_and_cleans_progress_handler(self):
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaises(sqlite3.OperationalError):
                with runtime.sqlite_deadline(db, time.monotonic()+1):
                    db.execute('SELECT * FROM table_that_does_not_exist')
            self.assertEqual(db.execute('SELECT 1').fetchone()[0], 1)

    def test_vocabulary_scope_isolated_between_requests_and_nested_databases(self):
        @runtime.catalog_request
        def read(db, nested=None):
            before = runtime.vocabulary(db, 'artists', 'SELECT name FROM artist')
            inner = read(nested)[0] if nested is not None else None
            after = runtime.vocabulary(db, 'artists', 'SELECT name FROM artist')
            self.assertEqual(before, after)
            return before, inner
        with closing(sqlite3.connect(':memory:')) as left, closing(sqlite3.connect(':memory:')) as right:
            for db, name in [(left, 'Left'), (right, 'Right')]:
                db.execute('CREATE TABLE artist(name TEXT)')
                db.execute('INSERT INTO artist VALUES (?)', (name,))
            self.assertEqual(read(left, right), ((('Left',),), (('Right',),)))
            left.execute("UPDATE artist SET name='Changed'")
            self.assertEqual(read(left)[0], (('Changed',),))
            self.assertIsNone(runtime._catalog_scope.get())

    def test_vocabulary_context_is_reset_after_exception(self):
        @runtime.catalog_request
        def broken(db):
            runtime.vocabulary(db, 'release_codes', 'SELECT 1')
            raise LookupError('fixture')
        with closing(sqlite3.connect(':memory:')) as db:
            with self.assertRaises(LookupError):
                broken(db)
            self.assertIsNone(runtime._catalog_scope.get())


class ContinuationHttpReview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'catalog.sqlite3'
        with closing(core.connect(self.path)) as db:
            core.init_db(db)

    def tearDown(self):
        self.temp.cleanup()

    @contextmanager
    def server(self, native_read_model=False, **options):
        # Keep deliberate request deadlines separate from startup timing.
        bootstrap = (patch.object(runtime, 'CatalogReadModel',
            side_effect=runtime.CatalogReadModelUnsupported) if native_read_model else nullcontext())
        with bootstrap as constructor:
            server = create_server(str(self.path), '127.0.0.1', 0, True, **options)
            if native_read_model:
                constructor.assert_called_once()
        with server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield server
            finally:
                server.shutdown()
                thread.join(timeout=3)

    @staticmethod
    def request(server, method='POST', path='/collector-journey', body=None):
        client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            client.request(method, path, body if body is not None else '{"turns":[]}',
                           {'Content-Type': 'application/json'})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), json.loads(response.read())
        finally:
            client.close()

    def test_busy_and_invalid_payload_do_not_block_health_or_leak_compute_slot(self):
        entered, release = threading.Event(), threading.Event()
        def held(*args, **kwargs):
            entered.set()
            if not release.wait(2):
                raise RuntimeError('fixture release timed out')
            return {'fixture': True}
        with self.server(catalog_queue_size=0) as server:
            with patch.object(collector_journey, 'replay', side_effect=held) as replay:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    first = executor.submit(self.request, server)
                    try:
                        self.assertTrue(entered.wait(1))
                        status, headers, body = self.request(server)
                        self.assertEqual((status, body), (503, {'error': 'catalog_busy'}))
                        self.assertEqual(headers['Retry-After'], '1')
                        self.assertEqual(self.request(server, 'GET', '/health')[0], 200)
                        self.assertEqual(self.request(server, body='[]'*1000)[0], 400)
                        self.assertEqual(replay.call_count, 1)
                    finally:
                        release.set()
                    self.assertEqual(first.result(timeout=2)[0], 200)
            self.assertEqual(self.request(server)[0], 400)
            self.assertEqual(self.request(server, 'GET', '/health')[0], 200)

    def test_sql_timeout_returns_typed_json_and_next_request_can_run(self):
        def expensive(db, *args, **kwargs):
            db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL '
                       'SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        with self.server(catalog_deadline=.025,native_read_model=True) as server:
            with patch.object(collector_journey, 'replay', side_effect=expensive):
                status, headers, body = self.request(server)
                self.assertEqual(status, 504)
                self.assertEqual(headers['X-Collector-Error'], 'catalog_work_budget_exceeded')
                self.assertEqual(body, {'error': 'catalog_work_budget_exceeded'})
            self.assertEqual(self.request(server)[0], 400)
            self.assertEqual(self.request(server, 'GET', '/health')[0], 200)

    def test_disconnected_reader_does_not_retain_compute_slot(self):
        entered, release, completed = threading.Event(), threading.Event(), threading.Event()
        def held(*args, **kwargs):
            entered.set()
            release.wait(2)
            completed.set()
            return {'fixture': 'x'*100000}
        with self.server(catalog_queue_wait=1) as server:
            with patch.object(collector_journey, 'replay', side_effect=held):
                client = socket.create_connection(('127.0.0.1', server.server_port), timeout=2)
                try:
                    client.sendall(b'POST /collector-journey HTTP/1.0\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{}')
                    self.assertTrue(entered.wait(1))
                finally:
                    client.close()
                    release.set()
                self.assertTrue(completed.wait(1))
            self.assertEqual(self.request(server)[0], 400)
            self.assertEqual(self.request(server, 'GET', '/health')[0], 200)

    def test_wal_commit_during_compute_discards_result_and_keeps_health_live(self):
        with closing(core.connect(self.path)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        with self.server() as server:
            def mutate_then_answer(*args, **kwargs):
                with closing(core.connect(self.path)) as writer:
                    writer.execute('CREATE TABLE post_start_mutation(value)')
                    writer.commit()
                return {'fixture': 'must not escape under the old revision'}
            with patch.object(collector_journey, 'replay', side_effect=mutate_then_answer) as replay:
                status, headers, body = self.request(server)
                self.assertEqual((status, body), (503, {'error': 'catalog_snapshot_changed'}))
                self.assertEqual(headers['X-Collector-Error'], 'catalog_snapshot_changed')
                self.assertEqual(self.request(server)[0], 503)
                self.assertEqual(replay.call_count, 1)
            self.assertEqual(self.request(server, 'GET', '/health')[0], 200)

    def test_atomic_catalog_replacement_cannot_reuse_startup_revision(self):
        with self.server() as server:
            replacement = self.path.with_name('replacement.sqlite3')
            with closing(core.connect(replacement)) as db:
                core.init_db(db)
            replacement.replace(self.path)
            with patch.object(collector_journey, 'replay', side_effect=AssertionError('stale snapshot ran')):
                self.assertEqual(self.request(server)[2], {'error': 'catalog_snapshot_changed'})
            self.assertEqual(self.request(server, 'GET', '/health')[0], 200)

    @unittest.skipUnless(shutil.which('node'), 'actual Node caller required')
    def test_node_busy_retry_waits_for_capacity_and_replays_identical_input_once(self):
        entered, release = threading.Event(), threading.Event()
        original = collector_journey.replay
        def held_once(db, payload, **kwargs):
            if not entered.is_set():
                entered.set()
                release.wait(3)
            return original(db, payload, **kwargs)
        program = '''const {createCollectorClient}=require(process.argv[1]);
const bodies=[],times=[];
const client=createCollectorClient({baseUrl:process.argv[2],allowLoopback:true,retryDelayMs:0,
fetchImpl:async(url,options)=>{bodies.push(options.body);times.push(performance.now());return fetch(url,options);}});
client.start({question:'What should I collect next?'}).then(out=>process.stdout.write(JSON.stringify({
status:out.status,calls:bodies.length,identical:bodies[0]===bodies[1],wait:times[1]-times[0],
turns:out.session.turns,target:out.target_intent}))).catch(e=>{process.stderr.write(String(e));process.exitCode=1;});'''
        with self.server(catalog_queue_size=0) as server:
            with patch.object(collector_journey, 'replay', side_effect=held_once) as replay:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    first = executor.submit(self.request, server)
                    self.assertTrue(entered.wait(1))
                    timer = threading.Timer(.6, release.set)
                    timer.start()
                    try:
                        result = json.loads(subprocess.check_output(['node', '-e', program,
                            str(Path('integrations/pivota/collectorClient.cjs').resolve()),
                            'http://127.0.0.1:'+str(server.server_port)], text=True, timeout=5))
                    finally:
                        release.set()
                        timer.cancel()
                    self.assertEqual(first.result(timeout=1)[0], 400)
                    self.assertEqual((result['status'], result['calls'], result['identical']),
                                     ('accepted', 2, True))
                    self.assertGreaterEqual(result['wait'], 900)
                    self.assertLess(result['wait'], 2000)
                    self.assertEqual(result['turns'], [{'type':'ask', 'question':'What should I collect next?'}])
                    self.assertIsNone(result['target'])
                    self.assertEqual(replay.call_count, 2)

    @unittest.skipUnless(shutil.which('node'), 'actual Node caller required')
    def test_node_does_not_retry_server_work_budget_exhaustion(self):
        def expensive(db, *args, **kwargs):
            db.execute('WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL '
                       'SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        program = '''const {createCollectorClient}=require(process.argv[1]);
const client=createCollectorClient({baseUrl:process.argv[2],allowLoopback:true,retryDelayMs:0});
client.start({question:'Japanese cards'}).then(()=>process.stdout.write('accepted'))
.catch(e=>process.stdout.write(JSON.stringify({code:e.code,retryable:e.retryable})));'''
        with self.server(catalog_deadline=.025,native_read_model=True) as server:
            with patch.object(collector_journey, 'replay', side_effect=expensive) as replay:
                result = subprocess.check_output(['node', '-e', program,
                    str(Path('integrations/pivota/collectorClient.cjs').resolve()),
                    'http://127.0.0.1:'+str(server.server_port)], text=True, timeout=5)
                result = json.loads(result)
                self.assertFalse(result['retryable'])
                self.assertEqual(replay.call_count, 1)


if __name__ == '__main__':
    unittest.main()

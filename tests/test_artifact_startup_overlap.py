"""Bootstrap overlap is bounded IO, never early acceptance of unverified facts."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class ArtifactStartupOverlapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text('{"synthetic_test_only":true}')
        self.directory = self.base / 'artifact'
        with closing(core.connect(self.path, readonly=True)) as db:
            self.exported = artifact.write(db, self.manifest, self.directory)

    def tearDown(self):
        self.assertIsNone(runtime._work_deadline.get())
        self.assertIsNone(runtime._snapshot_scope.get())

    def load(self, db, timings):
        return artifact.load(db, self.directory, self.manifest,
                             expected_seal_sha256=self.exported['seal_sha256'],
                             bootstrap_timings=timings)

    def test_single_hash_worker_overlaps_both_reads_without_early_decode_or_restore(self):
        original_hash = artifact._database_hash
        original_read = artifact._read
        original_validate = artifact._validate_image
        original_json = artifact._json
        original_restore = artifact._restore
        started, image_read, finished = threading.Event(), threading.Event(), threading.Event()
        lock = threading.Lock()
        active = maximum = calls = 0
        worker_threads = []

        def database_hash(path):
            nonlocal active, maximum, calls
            with lock:
                active += 1
                calls += 1
                maximum = max(maximum, active)
                worker_threads.append(threading.current_thread())
            started.set()
            try:
                self.assertTrue(image_read.wait(1), 'hash ran serially before image read')
                return original_hash(path)
            finally:
                with lock:
                    active -= 1
                finished.set()

        def read(path, limit):
            if Path(path).name in ('metadata.json', 'facet-image.sqlite3'):
                self.assertTrue(started.wait(1), 'artifact read preceded hash worker')
                self.assertFalse(finished.is_set(), 'hash did not overlap artifact reads')
                with lock:
                    self.assertEqual(active, 1)
            result = original_read(path, limit)
            if Path(path).name == 'facet-image.sqlite3':
                image_read.set()
            return result

        def accepted():
            self.assertTrue(finished.is_set(), 'unchecked database reached artifact facts')
            with lock:
                self.assertEqual(active, 0)

        def validate(image):
            accepted()
            return original_validate(image)

        def decode(raw, limit):
            if limit == artifact.MAX_METADATA_BYTES:
                accepted()
            return original_json(raw, limit)

        def restore(state, image):
            accepted()
            return original_restore(state, image)

        timings = {}
        with closing(core.connect(self.path, readonly=True)) as db:
            with patch.object(artifact, '_database_hash', database_hash), \
                    patch.object(artifact, '_read', read), \
                    patch.object(artifact, '_validate_image', validate), \
                    patch.object(artifact, '_json', decode), \
                    patch.object(artifact, '_restore', restore), \
                    patch.object(artifact, 'ThreadPoolExecutor', wraps=artifact.ThreadPoolExecutor) as pool:
                loaded, revision, receipt = self.load(db, timings)
        self.assertEqual(calls, 1)
        self.assertEqual(maximum, 1)
        self.assertNotEqual(worker_threads[0].ident, threading.get_ident())
        self.assertFalse(worker_threads[0].is_alive(), 'bootstrap hash worker was not joined')
        self.assertEqual(pool.call_count, 1)
        self.assertEqual(pool.call_args.kwargs['max_workers'], 1)
        self.assertEqual(receipt['seal_sha256'], self.exported['seal_sha256'])
        self.assertEqual(revision, self.exported['canonical_revision'])
        self.assertEqual(artifact.model_state(loaded),
                         json.loads((self.directory / 'metadata.json').read_bytes()))
        self.assertEqual(len(timings), 8)
        self.assertTrue(all(type(value) is float and value >= 0 for value in timings.values()))

    def test_main_and_worker_keep_the_same_absolute_deadline(self):
        original_hash, original_read = artifact._database_hash, artifact._read
        seen = []
        deadline = time.monotonic() + 3

        def database_hash(path):
            seen.append(('worker', runtime._work_deadline.get(), threading.get_ident()))
            runtime.checkpoint()
            return original_hash(path)

        def read(path, limit):
            if Path(path).name == 'metadata.json':
                seen.append(('main', runtime._work_deadline.get(), threading.get_ident()))
                runtime.checkpoint()
            return original_read(path, limit)

        with closing(core.connect(self.path, readonly=True)) as db, runtime.sqlite_deadline(db, deadline):
            with patch.object(artifact, '_database_hash', database_hash), patch.object(artifact, '_read', read):
                self.load(db, {})
        self.assertEqual({item[0] for item in seen}, {'main', 'worker'})
        self.assertTrue(all(item[1] == deadline for item in seen))
        self.assertEqual(len({item[2] for item in seen}), 2)

    def test_worker_deadline_expiry_aborts_before_image_sql_decode_or_publication(self):
        original_hash = artifact._database_hash
        finished = threading.Event()
        deadline = time.monotonic() + 3

        def database_hash(path):
            self.assertEqual(runtime._work_deadline.get(), deadline)
            try:
                with patch.object(runtime.time, 'monotonic', return_value=deadline + 1):
                    return original_hash(path)
            finally:
                finished.set()

        timings = {}
        with closing(core.connect(self.path, readonly=True)) as db, runtime.sqlite_deadline(db, deadline):
            with patch.object(artifact, '_database_hash', database_hash), \
                    patch.object(artifact, '_validate_image', side_effect=AssertionError('expired hash reached SQLite')), \
                    patch.object(artifact, '_restore', side_effect=AssertionError('expired hash published model')):
                with self.assertRaises(runtime.CatalogDeadline):
                    self.load(db, timings)
        self.assertTrue(finished.is_set())
        self.assertEqual(timings, {})

    def test_hash_and_read_failures_join_and_database_failure_precedes_read_error(self):
        original_hash, original_read = artifact._database_hash, artifact._read
        for failure in ('hash', 'read', 'both', 'mismatch_and_read'):
            with self.subTest(failure=failure):
                started, attempted_read, finished = threading.Event(), threading.Event(), threading.Event()
                threads = []

                def database_hash(path):
                    threads.append(threading.current_thread())
                    started.set()
                    try:
                        self.assertTrue(attempted_read.wait(1), 'failed read never overlapped hash')
                        if failure in ('hash', 'both'):
                            raise artifact.ArtifactInvalid('synthetic database hash failure')
                        digest, size = original_hash(path)
                        return ('0' * 64, size) if failure == 'mismatch_and_read' else (digest, size)
                    finally:
                        finished.set()

                def read(path, limit):
                    if Path(path).name == 'metadata.json':
                        self.assertTrue(started.wait(1))
                        attempted_read.set()
                        if failure in ('read', 'both', 'mismatch_and_read'):
                            raise artifact.ArtifactInvalid('synthetic metadata read failure')
                    return original_read(path, limit)

                expected = ('database byte mismatch' if failure == 'mismatch_and_read' else
                            'synthetic database hash failure' if failure in ('hash', 'both') else
                            'synthetic metadata read failure')
                timings = {}
                with closing(core.connect(self.path, readonly=True)) as db:
                    with patch.object(artifact, '_database_hash', database_hash), \
                            patch.object(artifact, '_read', read), \
                            patch.object(artifact, '_validate_image', side_effect=AssertionError('failed proof reached image SQL')), \
                            patch.object(artifact, '_restore', side_effect=AssertionError('failed proof published model')):
                        with self.assertRaisesRegex(artifact.ArtifactInvalid, expected):
                            self.load(db, timings)
                        self.assertTrue(finished.is_set(), 'load returned while hash worker remained live')
                        self.assertFalse(threads[0].is_alive(), 'failed bootstrap worker was not joined')
                self.assertEqual(timings, {})

    def test_main_read_deadline_expiry_joins_worker_without_publishing_diagnostics(self):
        original_hash, original_read = artifact._database_hash, artifact._read
        started, released, finished = threading.Event(), threading.Event(), threading.Event()
        deadline = time.monotonic() + 3
        threads = []

        def database_hash(path):
            threads.append(threading.current_thread())
            self.assertEqual(runtime._work_deadline.get(), deadline)
            started.set()
            try:
                self.assertTrue(released.wait(1))
                return original_hash(path)
            finally:
                finished.set()

        def read(path, limit):
            if Path(path).name != 'metadata.json':
                return original_read(path, limit)
            self.assertTrue(started.wait(1))
            self.assertEqual(runtime._work_deadline.get(), deadline)
            try:
                with patch.object(runtime.time, 'monotonic', return_value=deadline + 1):
                    return original_read(path, limit)
            finally:
                released.set()

        timings = {}
        with closing(core.connect(self.path, readonly=True)) as db, runtime.sqlite_deadline(db, deadline):
            with patch.object(artifact, '_database_hash', database_hash), patch.object(artifact, '_read', read), \
                    patch.object(artifact, '_validate_image', side_effect=AssertionError('expired read reached SQLite')), \
                    patch.object(artifact, '_restore', side_effect=AssertionError('expired read published model')):
                with self.assertRaises(runtime.CatalogDeadline):
                    self.load(db, timings)
                self.assertTrue(finished.is_set())
                self.assertFalse(threads[0].is_alive())
        self.assertEqual(timings, {})

    def test_metadata_hash_mismatch_never_reaches_decoder_or_model(self):
        original_read = artifact._read
        original_json = artifact._json

        def read(path, limit):
            raw, identity = original_read(path, limit)
            return (raw + b' ', identity) if Path(path).name == 'metadata.json' else (raw, identity)

        def decode(raw, limit):
            self.assertNotEqual(limit, artifact.MAX_METADATA_BYTES, 'unverified metadata was decoded')
            return original_json(raw, limit)

        timings = {}
        with closing(core.connect(self.path, readonly=True)) as db:
            with patch.object(artifact, '_read', read), patch.object(artifact, '_json', decode), \
                    patch.object(artifact, '_validate_image', side_effect=AssertionError('bad metadata reached image SQL')), \
                    patch.object(artifact, '_restore', side_effect=AssertionError('bad metadata published model')):
                with self.assertRaisesRegex(artifact.ArtifactInvalid, 'metadata hash mismatch'):
                    self.load(db, timings)
        self.assertEqual(timings, {})


if __name__ == '__main__':
    unittest.main()

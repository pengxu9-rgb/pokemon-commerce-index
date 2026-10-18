"""Fixed packaged file requests preserve programmatic memory-clone behavior."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime, collector_journey
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import create_fixture, SUITE


def typed(value):
    if type(value) is dict:
        return ('dict', tuple((key, typed(item)) for key, item in sorted(value.items())))
    if type(value) in (tuple, list):
        return (type(value).__name__, tuple(typed(item) for item in value))
    return (type(value).__name__, value)


class PackagedFacetFileRequestTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.path = self.base / 'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        self.manifest = self.base / 'manifest.json'
        self.manifest.write_text('{"synthetic_only":true}')
        self.directory = self.base / "artifact ?#%日本語'"
        with closing(core.connect(self.path, readonly=True)) as db:
            self.written = artifact.write(db, self.manifest, self.directory)
        with closing(core.connect(self.path, readonly=True)) as db:
            self.materialized = runtime.CatalogReadModel(db)
        with closing(core.connect(self.path, readonly=True)) as db:
            self.loaded, _, self.loaded_evidence = artifact.load(
                db, self.directory, self.manifest,
                expected_seal_sha256=self.written['seal_sha256'])
        with closing(core.connect(self.path, readonly=True)) as db, \
                patch.object(artifact, '_PACKAGED_DIR', self.directory), \
                patch.object(artifact, '_PACKAGED_MANIFEST', self.manifest):
            self.packaged, _, self.packaged_evidence = artifact.load_packaged(db, required=True)
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def test_only_owned_packaged_context_attaches_fixed_file_and_keeps_typed_DTOs(self):
        payloads = [dict(turns=[dict(type='ask', question=question)], limit=5)
                    for question in ('Recommend Japanese Pikachu cards',
                                     'Recommend English Mew cards', 'ピカチュウのカード',
                                     '推荐日文皮卡丘卡牌', 'Recommend cards by Alpha')]
        with closing(core.connect(self.path, readonly=True)) as db:
            expected = [collector_journey.replay(db, payload, revision='a' * 64)
                        for payload in payloads]
        for model in (self.materialized, self.loaded, self.packaged):
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db, strict_readonly=True):
                namespace = {row[1]: row[2] for row in db.execute('PRAGMA database_list')}
                self.assertEqual(namespace['collector_snapshot'], '')
                actual = [collector_journey.replay(db, payload, revision='a' * 64)
                          for payload in payloads]
                self.assertEqual(typed(actual), typed(expected))
        with patch.object(core._CatalogConnection, 'deserialize',
                          side_effect=AssertionError('owned request copied the facet image')):
            for _ in range(2):
                with self.packaged.owned_http_request(expires=time.monotonic() + 8) as db:
                    namespace = {row[1]: row[2] for row in db.execute('PRAGMA database_list')}
                    self.assertEqual(namespace['collector_snapshot'],
                                     str(self.directory / 'facet-image.sqlite3'))
                    self.assertIs(type(db.execute('SELECT 1')), core._CatalogCursor)
                    self.assertTrue(db._catalog_clone_guard['private_reader'])
                    self.assertTrue(runtime._snapshot_scope.get()['file_backed'])
                    actual = [collector_journey.replay(db, payload, revision='a' * 64)
                              for payload in payloads]
                    self.assertEqual(typed(actual), typed(expected))
        # A mutation of one result cannot poison another request's nested DTOs.
        actual[0]['selection_blockers'].append('synthetic response mutation')
        with self.packaged.owned_http_request(expires=time.monotonic() + 8) as db:
            fresh = collector_journey.replay(db, payloads[0], revision='a' * 64)
        self.assertEqual(typed(fresh), typed(expected[0]))

    def test_witness_is_process_local_charged_and_never_portable_or_custom_loaded(self):
        self.assertFalse(hasattr(self.loaded, '_packaged_facet_file'))
        self.assertFalse(hasattr(self.materialized, '_packaged_facet_file'))
        self.assertEqual(artifact.model_state(self.packaged), artifact.model_state(self.loaded))
        self.assertIs(type(self.packaged._packaged_facet_file.path), str)
        charge = (artifact._deep_size(self.packaged._packaged_facet_file)
                  + sys.getsizeof('_packaged_facet_file')
                  + max(0, sys.getsizeof(self.packaged.__dict__)
                        - sys.getsizeof(self.loaded.__dict__)))
        self.assertEqual(self.packaged_evidence['decoded_state_bytes'],
                         self.loaded_evidence['decoded_state_bytes'] + charge)
        for model in (self.loaded, self.materialized):
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.owned_http_request(expires=time.monotonic() + 8):
                    self.fail('custom load acquired packaged-file authority')
        self.packaged._packaged_facet_file = ('malformed',)
        with self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.packaged.owned_http_request(expires=time.monotonic() + 8):
                self.fail('malformed process witness acquired authority')

    def test_body_error_releases_policy_before_deadline_restoration_and_closes_connection(self):
        held = []
        marker = ValueError('synthetic body error')
        with self.assertRaises(ValueError) as caught:
            with self.packaged.owned_http_request(expires=time.monotonic() + 8) as db:
                held.append(db)
                raise marker
        self.assertIs(caught.exception, marker)
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(held[0]._catalog_clone_guard)
        with self.assertRaises(sqlite3.ProgrammingError):
            held[0].execute('SELECT 1')
        with self.packaged.owned_http_request(expires=time.monotonic() + 8) as db:
            self.assertEqual(db.execute('SELECT 1').fetchone()[0], 1)

    def test_absent_or_invalid_artifact_does_not_fall_back_from_required_packaging(self):
        with closing(core.connect(self.path, readonly=True)) as db, \
                patch.object(artifact, '_PACKAGED_DIR', self.base / 'absent'):
            with self.assertRaises(artifact.ArtifactInvalid):
                artifact.load_packaged(db, required=True)
        with patch.object(self.packaged, '_artifact_guard',
                          side_effect=runtime.CatalogSnapshotChanged()):
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.packaged.owned_http_request(expires=time.monotonic() + 8):
                    self.fail('invalid packaged source fell back')

    def test_programmatic_callback_keyword_APIs_keep_original_behavior(self):
        trace = []
        progress = []
        with closing(core.connect(self.path, readonly=True)) as db:
            db.set_trace_callback(trace_callback=trace.append)
            db.set_progress_handler(progress_handler=lambda: progress.append(True) or 0, n=1)
            self.assertEqual(db.execute('SELECT 1').fetchone()[0], 1)
            self.assertTrue(trace)
            self.assertTrue(progress)
            db.set_trace_callback(trace_callback=None)
            db.set_progress_handler(progress_handler=None, n=0)

    def test_fixed_bootstrap_system_alias_binds_same_canonical_file(self):
        parent_alias = self.base / 'synthetic-trusted-system-alias'
        parent_alias.symlink_to(self.base, target_is_directory=True)
        with closing(core.connect(self.path, readonly=True)) as db, \
                patch.object(artifact, '_PACKAGED_DIR', parent_alias / self.directory.name), \
                patch.object(artifact, '_PACKAGED_MANIFEST', self.manifest):
            model, _, _ = artifact.load_packaged(db, required=True)
        self.assertEqual(model._packaged_facet_file.path,
                         str(self.directory / 'facet-image.sqlite3'))
        with model.owned_http_request(expires=time.monotonic() + 8) as db:
            self.assertIsNotNone(runtime.snapshot_character_names(db, False))

    def test_public_adapter_registry_replacement_cannot_redirect_driver_witness(self):
        with patch.object(sqlite3, 'adapters', dict(sqlite3.adapters)):
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.packaged.owned_http_request(expires=time.monotonic() + 8):
                    self.fail('replacement public registry concealed native adapters')


if __name__ == '__main__':
    unittest.main()

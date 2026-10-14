"""Fixed snapshot parsers cannot borrow callback results or skip trust checks."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from pokemon_index import core, collector_runtime as runtime
from pokemon_index import collector_discovery as discovery
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import create_fixture, SUITE


class ImmutableParserReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve(); self.path = base/'catalog.sqlite3'
        create_fixture(self.path, json.loads(SUITE.read_text()))
        manifest = base/'manifest.json'; manifest.write_text('{"synthetic_only":true}')
        with closing(core.connect(self.path, readonly=True)) as db:
            native = runtime.CatalogReadModel(db)
        with closing(core.connect(self.path, readonly=True)) as db:
            seal = artifact.write(db, manifest, base/'artifact')
        with closing(core.connect(self.path, readonly=True)) as db:
            loaded, _, _ = artifact.load(db, base/'artifact', manifest, expected_seal_sha256=seal['seal_sha256'])
        self.models = (native, loaded)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertIsNone(runtime._catalog_scope.get())

    def test_generic_and_mentions_keys_cannot_populate_fixed_reader_cache(self):
        @runtime.catalog_request
        def probe(db):
            fixed = ('artists', 'cards by alpha')
            forged = ('immutable_parser', 'artists', fixed)
            for key in (fixed, forged, ('generic_parser', forged)):
                self.assertEqual(runtime.request_parser_result(db, key, lambda: ('poison',)), ('poison',))
                self.assertEqual(runtime.request_mentions(db, key, lambda: ('poison',)), ('poison',))
            self.assertEqual(discovery._artists(db, 'cards by alpha'), ['Alpha'])
        for model in self.models:
            with self.subTest(loaded=model is self.models[1]), closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                probe(db)

    def test_fixed_snapshot_dispatch_never_calls_arbitrary_builder(self):
        callback = Mock(side_effect=AssertionError('arbitrary builder entered'))
        @runtime.catalog_request
        def probe(db):
            for _ in range(2):
                self.assertEqual(runtime.request_parser_result(db, ('artists', 'cards by alpha'), callback, immutable_parser='artists'), ('Alpha',))
        for model in self.models:
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                probe(db)
        callback.assert_not_called()
        native = Mock(return_value=('native',))
        with closing(core.connect(self.path, readonly=True)) as db:
            self.assertEqual(runtime.request_parser_result(db, ('artists', 'cards by alpha'), native, immutable_parser='artists'), ('native',))
        native.assert_called_once_with()

    def test_malformed_fixed_key_rejects_before_callback_or_cached_lookup(self):
        callback = Mock(side_effect=AssertionError('builder entered'))
        @runtime.catalog_request
        def probe(db):
            discovery._artists(db, 'cards by alpha')
            cases = [('unknown', ('artists', 'cards by alpha')), ('artists', ('artists', 12)), ('artists', ('release_name_mentions', 'cards by alpha')), ('release_name_mentions', ('release_name_mentions', 'fix', ['ja'])), ('release_name_mentions', ('release_name_mentions', 'fix', (1,)))]
            for kind, key in cases:
                with self.assertRaises(ValueError):
                    runtime.request_parser_result(db, key, callback, immutable_parser=kind)
        for model in self.models:
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                probe(db)
        callback.assert_not_called()

    def test_combined_memo_bound_cannot_grow_via_fixed_reader_dispatch(self):
        @runtime.catalog_request
        def probe(db):
            for index in range(64):
                runtime.request_mentions(db, ('arbitrary', index), lambda: ('old',))
            for index in range(70):
                self.assertEqual(discovery._artists(db, f'cards by alpha {index}'), ['Alpha'])
            scope = runtime._catalog_scope.get()
            self.assertLessEqual(sum(len(scope.get(key, {})) for key in ('mentions', 'immutable_parsers')), 64)
        for model in self.models:
            with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                probe(db)

    def test_fixed_hit_miss_capped_and_direct_reject_before_rollback(self):
        for model in self.models:
            for mode in ('hit', 'miss', 'capped', 'direct'):
                with self.subTest(loaded=model is self.models[1], mode=mode):
                    escaped = []
                    def body(db):
                        if mode == 'hit': discovery._artists(db, 'cards by alpha')
                        if mode == 'capped':
                            for n in range(64): runtime.request_parser_result(db, ('generic', n), lambda: ())
                        db.execute('PRAGMA query_only=OFF'); db.execute('BEGIN')
                        db.execute('CREATE TEMP VIEW synthetic_parser_shadow AS SELECT 1')
                        db.execute('PRAGMA query_only=ON')
                        try: escaped.append(discovery._artists(db, 'cards by alpha'))
                        finally: db.rollback(); db.execute('PRAGMA query_only=ON')
                    probe = body if mode == 'direct' else runtime.catalog_request(body)
                    with closing(core.connect(self.path, readonly=True)) as db, self.assertRaises(runtime.CatalogSnapshotChanged), model.request(db):
                        probe(db)
                    self.assertEqual(escaped, [])
                    with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                        self.assertEqual(discovery._artists(db, 'cards by alpha'), ['Alpha'])


if __name__ == '__main__': unittest.main()

"""Synthetic parser cache isolation and canonical file-guard regressions."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_discovery as discovery, collector_runtime as runtime
from pokemon_index import collector_journey
from scripts.rehearse_collector_recommendations import create_fixture, SUITE


class RequestParserRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve(); self.path = self.base/'catalog.sqlite3'
        self.suite = json.loads(SUITE.read_text()); create_fixture(self.path, self.suite)
        with closing(core.connect(self.path)) as db:
            db.execute("UPDATE catalog_set_localized SET name='Shared Archive' WHERE language='ja'")
            db.execute("UPDATE catalog_set_localized SET name='Other Archive' WHERE language='en'")
            db.execute("INSERT INTO catalog_set_localized (language,set_code,name,official_card_count,provenance,rights_reference,display_allowed) VALUES ('en','EXTRA','Shared Archive',1,'synthetic:test','synthetic:no-display',0)")
            db.commit()
        with closing(core.connect(self.path, readonly=True)) as db:
            self.model = runtime.CatalogReadModel(db)
        self.before = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        self.assertIsNone(runtime._catalog_scope.get())
        self.assertIsNone(runtime._snapshot_scope.get())

    def test_exact_language_keys_and_fresh_containers(self):
        @runtime.catalog_request
        def probe(db):
            first = discovery._release_name_mentions(db, 'shared archive', ['ja'])
            self.assertEqual({row[0] for row in first}, {'FIX'})
            first.append(('poison', 0, 1, 'poison'))
            self.assertEqual({row[0] for row in discovery._release_name_mentions(db, 'shared archive', ['ja'])}, {'FIX'})
            self.assertEqual({row[0] for row in discovery._release_name_mentions(db, 'shared archive', ['en'])}, {'EXTRA'})
            codes = discovery._release_codes(db, 'shared archive', ['ja']); codes.clear(); codes.add('poison')
            self.assertEqual(discovery._release_codes(db, 'shared archive', ['ja']), {'FIX'})
            self.assertEqual(discovery._release_codes(db, 'shared archive', ['en']), {'EXTRA'})
            artists = discovery._artists(db, 'cards by alpha'); artists.append('poison')
            self.assertEqual(discovery._artists(db, 'cards by alpha'), ['Alpha'])
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            with patch.object(discovery, '_compute_release_name_mentions', wraps=discovery._compute_release_name_mentions) as names:
                probe(db); self.assertEqual(names.call_count, 2)

    def test_nested_qualifier_values_cannot_poison_cached_result(self):
        fixture = [dict(value='Synthetic qualifier', active=False, card_ids=['synthetic:test-only'])]
        @runtime.catalog_request
        def probe(db):
            first = discovery._qualifier_findings(db, 'synthetic qualifier', ['ja'])
            first[0]['active'] = True; first[0]['card_ids'].append('poison'); first.clear()
            self.assertEqual(discovery._qualifier_findings(db, 'synthetic qualifier', ['ja']), fixture)
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            with patch.object(discovery, '_compute_qualifier_findings', return_value=fixture) as build:
                probe(db); self.assertEqual(build.call_count, 1)

    def test_parser_values_do_not_survive_replay_or_enter_shared_model(self):
        @runtime.catalog_request
        def probe(db):
            discovery._artists(db, 'cards by alpha'); discovery._artists(db, 'cards by alpha')
        with patch.object(discovery, '_compute_artists', wraps=discovery._compute_artists) as build:
            for unused in range(2):
                with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db): probe(db)
            self.assertEqual(build.call_count, 2)
        self.assertNotIn('cards by alpha', repr(vars(self.model)))

    def test_native_live_sql_never_uses_snapshot_parser_memo(self):
        @runtime.catalog_request
        def probe(db):
            self.assertEqual(discovery._release_codes(db, 'shared archive', ['ja']), {'FIX'})
            with closing(core.connect(self.path)) as writer:
                writer.execute("UPDATE catalog_set_localized SET name='Changed Archive' WHERE language='ja'"); writer.commit()
            self.assertEqual(discovery._release_codes(db, 'shared archive', ['ja']), set())
        with closing(core.connect(self.path, readonly=True)) as db: probe(db)

    def test_parser_cache_bound_falls_back_without_losing_new_queries(self):
        @runtime.catalog_request
        def probe(db):
            for number in range(65): discovery._artists(db, f'cards by alpha {number}')
            self.assertLessEqual(len(runtime._catalog_scope.get()['mentions']), 64)
            self.assertEqual(discovery._artists(db, 'cards by alpha 64'), ['Alpha'])
        with closing(core.connect(self.path, readonly=True)) as db, self.model.request(db):
            with patch.object(discovery, '_compute_artists', wraps=discovery._compute_artists) as build:
                probe(db); self.assertEqual(build.call_count, 66)

    def test_cache_hit_rechecks_source_alias_file_identity(self):
        alias = self.base/'test-only-alias.json'; alias.write_text('synthetic-only')
        self.model._release_alias_path = alias
        self.model._release_alias_identity = runtime.snapshot_identity(alias)
        @runtime.catalog_request
        def probe(db):
            discovery._artists(db, 'cards by alpha')
            alias.write_text('changed synthetic-only alias')
            with self.assertRaises(runtime.CatalogSnapshotChanged): discovery._artists(db, 'cards by alpha')
        with closing(core.connect(self.path, readonly=True)) as db, self.assertRaises(runtime.CatalogSnapshotChanged), self.model.request(db): probe(db)

    def test_cache_hit_rechecks_query_only_and_temp_namespace(self):
        @runtime.catalog_request
        def probe(db):
            discovery._artists(db, 'cards by alpha')
            db.execute('PRAGMA query_only=OFF')
            with self.assertRaises(runtime.CatalogSnapshotChanged): discovery._artists(db, 'cards by alpha')
            db.execute('CREATE TEMP VIEW synthetic_shadow AS SELECT 1')
            db.commit(); db.execute('PRAGMA query_only=ON')
            with self.assertRaises(runtime.CatalogSnapshotChanged): discovery._artists(db, 'cards by alpha')
        with closing(core.connect(self.path, readonly=True)) as db, self.assertRaises(runtime.CatalogSnapshotChanged), self.model.request(db): probe(db)
        with closing(core.connect(self.path, readonly=True)) as fresh, self.model.request(fresh):
            self.assertEqual(discovery._artists(fresh, 'cards by alpha'), ['Alpha'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)

    def test_same_inode_symlink_substitution_still_fails_fresh_main_resolve(self):
        alternate = self.base/'same-inode.sqlite3'; os.link(self.path, alternate)
        with closing(core.connect(self.path, readonly=True)) as db:
            self.path.unlink(); self.path.symlink_to(alternate)
            # Stat/WAL identity alone would miss this same-inode link substitution.
            with self.assertRaises(runtime.CatalogSnapshotChanged): self.model._check_snapshot(db)

    def test_empty_and_nonempty_wal_public_identity_contract_unchanged(self):
        canonical = self.path.resolve(strict=True)
        before = runtime.snapshot_identity(canonical)
        self.assertEqual(runtime._identity_at_path(canonical), before)
        wal = Path(str(canonical)+'-wal'); wal.touch()
        self.assertEqual(runtime.snapshot_identity(canonical), before)
        wal.write_bytes(b'synthetic nonempty WAL')
        self.assertNotEqual(runtime.snapshot_identity(canonical), before)
        self.assertEqual(runtime._identity_at_path(canonical), runtime.snapshot_identity(canonical))

    def test_all_frozen_journey_prefixes_match_native_full_bodies_and_errors(self):
        for journey in self.suite['journeys']:
            turns = []
            for step in journey['steps']:
                turns.append(step['action']); payload = dict(turns=turns, limit=self.suite['limit'])
                with self.subTest(journey=journey['id'], turns=len(turns)):
                    with closing(core.connect(self.path, readonly=True)) as db:
                        try: expected = collector_journey.replay(db, payload, revision='a'*64)
                        except ValueError:
                            with closing(core.connect(self.path, readonly=True)) as cached, self.model.request(cached), self.assertRaises(ValueError):
                                collector_journey.replay(cached, payload, revision='a'*64)
                        else:
                            with closing(core.connect(self.path, readonly=True)) as cached, self.model.request(cached):
                                actual = collector_journey.replay(cached, payload, revision='a'*64)
                            self.assertEqual(actual, expected)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), self.before)


if __name__ == '__main__': unittest.main()

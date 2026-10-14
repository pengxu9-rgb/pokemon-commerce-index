"""Source-context copies retain real snapshot boundaries and exact identities."""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import (card_metadata, collector_discovery as discovery,
                           collector_release_alias, collector_runtime as runtime,
                           core, source_image_facts)
from pokemon_index import catalog_read_model_artifact as artifact
from tests import test_official_card_metadata as metadata_fixtures
from tests import test_catalog_media as media_fixtures


class CardSourceContextGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = self.base / 'catalog.sqlite3'
        fixture = metadata_fixtures.OfficialMetadataTests()
        fixture.setUp()
        self.addCleanup(fixture.db.close)
        card_metadata.import_evidence(fixture.db, [fixture.record])
        self.hit = fixture.cid
        for language, code, variant, name in (
                ('en', 'FIX', 'normal', 'Pikachu'),
                ('ja', 'FIX', 'holo', 'ピカチュウ'),
                ('ja', 'FIX', 'normal_stamp', 'ピカチュウ'),
                ('ja', 'PR', 'normal', 'ピカチュウ'),
                ('ja', 'NONE', 'normal', 'ピカチュウ')):
            core.import_cards(fixture.db, [dict(
                language=language, set_code=code, collector_number='001/100',
                variant=variant, name=name, rarity='raw rarity',
                provenance='synthetic:pinned', rights_reference='synthetic',
                match_eligible=False, display_allowed=False)])
        fixture.db.commit()
        with closing(core.connect(self.path)) as target:
            fixture.db.backup(target)
        self.absent = 'ja:NONE:001/100:normal'
        # Keep source-alias drift tests wholly inside the disposable fixture.
        self.alias = self.base / 'aliases.json'
        self.alias.write_bytes(collector_release_alias.BINDINGS_PATH.read_bytes())
        alias_patch = patch.object(collector_release_alias, 'BINDINGS_PATH', self.alias)
        alias_patch.start()
        self.addCleanup(alias_patch.stop)
        self.models = self.build_models(self.path, 'models')
        with closing(core.connect(self.path, readonly=True)) as db:
            self.rows = {row['card_id']: dict(row) for row in self.rows_from(db)}
            self.expected = {cid: discovery._card_result(db, row)
                             for cid, row in self.rows.items()}

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())

    def rows_from(self, db):
        return db.execute('''SELECT c.*, s.name AS set_name, s.release_date,
            s.provenance AS release_provenance FROM card c
            LEFT JOIN catalog_set_localized s
            ON c.language=s.language AND c.set_code=s.set_code
            ORDER BY c.card_id''').fetchall()

    def build_models(self, path, label):
        manifest = self.base / (label + '-manifest.json')
        manifest.write_text('{"synthetic_test_only":true}')
        directory = self.base / (label + '-artifact')
        with closing(core.connect(path, readonly=True)) as db:
            receipt = artifact.write(db, manifest, directory)
        with closing(core.connect(path, readonly=True)) as db:
            loaded, _, _ = artifact.load(db, directory, manifest,
                                        expected_seal_sha256=receipt['seal_sha256'])
        with closing(core.connect(path, readonly=True)) as db:
            native = runtime.CatalogReadModel(db)
        return {'materialized': native, 'loaded': loaded}

    def test_hits_and_complete_known_absence_avoid_native_sql_and_copy_freshly(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db:
                with model.request(db):
                    statements = []
                    db.set_trace_callback(statements.append)
                    with patch.object(discovery, '_card_context',
                                      side_effect=AssertionError('native context repeated')):
                        for cid, row in self.rows.items():
                            self.assertEqual(discovery._card_result(db, row), self.expected[cid])
                        first = discovery._card_result(db, self.rows[self.hit])
                        first['official_metadata']['official']['rarity'] = 'caller poison'
                        first['media_availability']['warnings'].append('caller poison')
                        self.assertEqual(discovery._card_result(db, self.rows[self.hit]),
                                         self.expected[self.hit])
                    self.assertFalse(any('card_metadata_evidence' in sql.lower()
                                         for sql in statements))

    def test_no_scope_other_connection_and_unknown_or_wrong_typed_ids_use_native(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db:
                self.assertIsNone(runtime.snapshot_card_context(db, self.hit))
                with patch.object(discovery, '_card_context', wraps=discovery._card_context) as native:
                    self.assertEqual(discovery._card_result(db, self.rows[self.hit]), self.expected[self.hit])
                    self.assertEqual(native.call_count, 1)
                with model.request(db), closing(core.connect(self.path, readonly=True)) as other:
                    self.assertIsNone(runtime.snapshot_card_context(other, self.hit))
                    for cid in ('synthetic:unknown', 1, True, None):
                        with self.subTest(cid=cid):
                            self.assertIsNone(runtime.snapshot_card_context(db, cid))
                            row = dict(self.rows[self.absent], card_id=cid)
                            with patch.object(discovery, '_card_context', wraps=discovery._card_context) as native:
                                with self.assertRaises(ValueError) as accelerated_error:
                                    discovery._card_result(db, row)
                                self.assertEqual(native.call_count, 1)
                            with self.assertRaises(ValueError) as native_error:
                                discovery._card_result(other, row)
                            self.assertEqual(accelerated_error.exception.args, native_error.exception.args)

    def test_raw_fields_official_rarity_and_missing_input_errors_remain_native(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as native:
                changes = dict(self.rows[self.hit], rarity='incoming rarity', name='incoming name',
                               set_name=None, release_date=None, match_eligible=0)
                expected = discovery._card_result(native, changes)
                self.assertEqual(expected['source_rarity'], 'incoming rarity')
                self.assertEqual(expected['rarity'], 'C')
                with closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                    self.assertEqual(discovery._card_result(db, changes), expected)
                    for field in ('card_id', 'rarity', 'release_provenance', 'match_eligible'):
                        incomplete = dict(changes)
                        del incomplete[field]
                        for connection in (native, db):
                            with self.assertRaises(KeyError) as error:
                                discovery._card_result(connection, incomplete)
                            self.assertEqual(error.exception.args, (field,))

    def test_language_stamp_foil_and_promo_do_not_inherit_coordinate_metadata(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db, model.request(db):
                for cid, row in self.rows.items():
                    card = discovery._card_result(db, row)
                    self.assertEqual(card, self.expected[cid])
                    if cid != self.hit:
                        self.assertNotIn('official_metadata', card)
                        self.assertEqual(card['rarity'], 'raw rarity')
                    self.assertIs(card['price_comparable'], False)
                    self.assertIs(card['automatic_offer_join_allowed'], False)
                    self.assertIs(card['media_availability']['display_allowed'], False)

    def test_exact_scan_id_does_not_transfer_to_same_art_name_number_or_variant(self):
        fixture = media_fixtures.CatalogMediaTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        source_image_facts.import_evidence(fixture.db, [fixture.fact()])
        for language, code, variant in (('ja', 'SVP', 'holo_set_logo'),
                                        ('en', 'SVP', 'normal_stamp'),
                                        ('en', 'PR', 'holo_set_logo')):
            core.import_cards(fixture.db, [dict(language=language, set_code=code,
                collector_number='037/225', variant=variant, name='Cleffa',
                provenance='synthetic:shared-art', rights_reference='synthetic',
                match_eligible=False, display_allowed=False)])
        fixture.db.commit()
        path = self.base / 'media.sqlite3'
        with closing(core.connect(path)) as target:
            fixture.db.backup(target)
        models = self.build_models(path, 'media')
        with closing(core.connect(path, readonly=True)) as db:
            rows = self.rows_from(db)
            expected = {row['card_id']: discovery._card_result(db, row) for row in rows}
        self.assertIs(expected[fixture.cid]['media_availability']['with_source_scans_eligible'], True)
        for label, model in models.items():
            with self.subTest(model=label), closing(core.connect(path, readonly=True)) as db, model.request(db):
                for row in rows:
                    card = discovery._card_result(db, row)
                    self.assertEqual(card, expected[row['card_id']])
                    if row['card_id'] != fixture.cid:
                        self.assertIs(card['media_availability']['with_source_scans_eligible'], False)

    def test_temp_transactions_rollback_and_query_only_reject_before_any_context_copy(self):
        for label, model in self.models.items():
            for mutation in ('transaction', 'transaction_rollback', 'temp', 'temp_drop', 'temp_rollback', 'query_only'):
                with self.subTest(model=label, mutation=mutation), closing(core.connect(self.path, readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            if mutation.startswith('transaction'):
                                db.execute('BEGIN')
                                if mutation == 'transaction_rollback':
                                    db.rollback()
                                    # A completed transaction with no SQL changes is safe.
                                    self.assertEqual(discovery._card_result(db, self.rows[self.absent]), self.expected[self.absent])
                                    db.execute('BEGIN')
                            else:
                                db.execute('PRAGMA query_only=OFF')
                                if mutation in ('temp', 'temp_drop', 'temp_rollback'):
                                    db.execute('CREATE TEMP TABLE card_source_poison(v)')
                                    if mutation == 'temp_rollback':
                                        db.execute("INSERT INTO card_source_poison VALUES ('changed then rolled back')")
                                        db.rollback()
                                    if mutation == 'temp_drop':
                                        db.execute('DROP TABLE card_source_poison')
                                        db.execute('PRAGMA query_only=ON')
                            with patch.object(type(model._card_source_context_index), 'lookup',
                                              side_effect=AssertionError('unsafe cached copy')):
                                for cid in (self.hit, self.absent):
                                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                                        discovery._card_result(db, self.rows[cid])
                    db.rollback()

    def test_unsafe_entry_and_late_exit_each_guard_independently(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db:
                db.execute('CREATE TEMP VIEW card AS SELECT * FROM main.card')
                with patch.object(model, '_attach', side_effect=AssertionError('unsafe attach')):
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            self.fail('unsafe entry accepted')
            with closing(core.connect(self.path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        self.assertEqual(discovery._card_result(db, self.rows[self.absent]), self.expected[self.absent])
                        db.execute('BEGIN')  # No reader follows; exit must still reject.
                db.rollback()

    def test_clone_replacement_poison_rejects_before_hit_or_absence_copy(self):
        for label, model in self.models.items():
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                            db.deserialize(model._image, name='collector_snapshot')
                        with patch.object(type(model._card_source_context_index), 'lookup',
                                          side_effect=AssertionError('poisoned clone copied context')):
                            for cid in (self.hit, self.absent):
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    discovery._card_result(db, self.rows[cid])

    def test_changed_source_alias_is_freshly_guarded_for_absence_and_hit(self):
        for ordinal, label in enumerate(self.models):
            model = (self.models[label] if ordinal == 0 else
                     self.build_models(self.path, 'alias-drift')[label])
            with self.subTest(model=label), closing(core.connect(self.path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        self.assertEqual(discovery._card_result(db, self.rows[self.absent]), self.expected[self.absent])
                        self.alias.write_bytes(self.alias.read_bytes() + b'\n ')
                        with patch.object(type(model._card_source_context_index), 'lookup',
                                          side_effect=AssertionError('changed alias copied context')):
                            for cid in (self.hit, self.absent):
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    discovery._card_result(db, self.rows[cid])

    def test_same_path_replacement_inode_cannot_copy_old_contexts(self):
        replacement = self.base / 'replacement.sqlite3'
        replacement.write_bytes(self.path.read_bytes())
        with closing(core.connect(self.path, readonly=True)) as stale:
            os.replace(replacement, self.path)
            for model in self.models.values():
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(stale):
                        self.fail('stale open handle entered')

    def test_path_replacement_after_entry_rejects_before_default_or_hit_lookup(self):
        for label in self.models:
            path = self.base / ('replace-' + label + '.sqlite3')
            path.write_bytes(self.path.read_bytes())
            replacement = self.base / ('replace-new-' + label + '.sqlite3')
            replacement.write_bytes(path.read_bytes())
            model = self.build_models(path, 'replace-' + label)[label]
            with self.subTest(model=label), closing(core.connect(path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        self.assertEqual(discovery._card_result(db, self.rows[self.absent]), self.expected[self.absent])
                        os.replace(replacement, path)
                        with patch.object(type(model._card_source_context_index), 'lookup',
                                          side_effect=AssertionError('replaced path copied context')):
                            for cid in (self.hit, self.absent):
                                with self.assertRaises(runtime.CatalogSnapshotChanged):
                                    discovery._card_result(db, self.rows[cid])

    def test_same_inode_source_write_invalidates_both_models(self):
        before = self.path.stat().st_ino
        with closing(core.connect(self.path)) as writer:
            writer.execute('UPDATE card SET provenance=? WHERE card_id=?', ('changed', self.hit))
            writer.commit()
        self.assertEqual(self.path.stat().st_ino, before)
        for model in self.models.values():
            with closing(core.connect(self.path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        self.fail('changed source entered')

    def test_same_inode_symlink_retarget_fails_closed(self):
        saved = self.base / 'same-inode.sqlite3'
        self.path.rename(saved)
        self.path.symlink_to(saved)
        for model in self.models.values():
            with closing(core.connect(self.path, readonly=True)) as db:
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with model.request(db):
                        self.fail('retargeted source entered')

    def test_real_wal_commit_after_entry_rejects_before_context_copy(self):
        # A genuine SQLite writer creates a WAL commit, rather than fabricating
        # a sidecar byte string. The writer stays open to retain the WAL.
        for label in self.models:
            path = self.base / ('wal-' + label + '.sqlite3')
            path.write_bytes(self.path.read_bytes())
            with self.subTest(model=label), closing(core.connect(path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                model = self.build_models(path, 'wal-' + label)[label]
                with closing(core.connect(path, readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            self.assertEqual(discovery._card_result(db, self.rows[self.absent]), self.expected[self.absent])
                            writer.execute('UPDATE card SET name=? WHERE card_id=?', ('changed', self.absent))
                            writer.commit()
                            self.assertGreater(Path(str(path) + '-wal').stat().st_size, 0)
                            with patch.object(type(model._card_source_context_index), 'lookup',
                                              side_effect=AssertionError('WAL drift copied context')):
                                for cid in (self.hit, self.absent):
                                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                                        discovery._card_result(db, self.rows[cid])


if __name__ == '__main__':
    unittest.main()

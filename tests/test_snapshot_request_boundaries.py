"""Publication boundaries for native and loaded catalog models, synthetic only."""
from contextlib import closing
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime, collector_journey
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import SUITE, create_fixture


class SnapshotRequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.path=self.base/'catalog.sqlite3'
        create_fixture(self.path,json.loads(SUITE.read_text()))
        self.manifest=self.base/'manifest.json';self.manifest.write_text('{"synthetic_only":true}')
        self.directory=self.base/'artifact'
        with closing(core.connect(self.path,readonly=True)) as db:
            receipt=artifact.write(db,self.manifest,self.directory)
        self.seal_pin=receipt['seal_sha256']
        with closing(core.connect(self.path,readonly=True)) as db:
            self.loaded,_,_=artifact.load(db,self.directory,self.manifest,expected_seal_sha256=receipt['seal_sha256'])
        with closing(core.connect(self.path,readonly=True)) as db:self.native=runtime.CatalogReadModel(db)

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())

    def test_late_namespace_and_clone_mutations_fail_before_successful_publication(self):
        for model in (self.native,self.loaded):
            for mutation in ('begin','query_only','temp_table','temp_view','temp_create_drop','clone_rollback','clone_schema','clone_view','clone_alter'):
                with self.subTest(model=type(model).__name__,mutation=mutation),closing(core.connect(self.path,readonly=True)) as db:
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(db):
                            self.assertIsNotNone(runtime.snapshot_character_names(db,False))
                            # No cached reader follows this mutation: context
                            # exit itself must guard the result being published.
                            if mutation=='begin':db.execute('BEGIN')
                            else:
                                db.execute('PRAGMA query_only=OFF')
                                if mutation=='temp_table':db.execute('CREATE TEMP TABLE late_shadow(x)')
                                elif mutation=='temp_view':db.execute('CREATE TEMP VIEW card AS SELECT * FROM main.card')
                                elif mutation=='temp_create_drop':
                                    db.execute('CREATE TEMP TABLE late_shadow(x)');db.execute('DROP TABLE late_shadow');db.execute('PRAGMA query_only=ON')
                                elif mutation=='clone_rollback':
                                    db.execute("UPDATE collector_snapshot.facets SET value='synthetic changed'");db.rollback();db.execute('PRAGMA query_only=ON')
                                elif mutation=='clone_schema':
                                    db.execute('DROP INDEX collector_snapshot.facet_lookup');db.execute('PRAGMA query_only=ON')
                                elif mutation=='clone_view':
                                    db.execute('CREATE VIEW collector_snapshot.unreviewed AS SELECT * FROM facets');db.execute('PRAGMA query_only=ON')
                                elif mutation=='clone_alter':
                                    db.execute('ALTER TABLE collector_snapshot.facets ADD COLUMN unreviewed TEXT');db.execute('PRAGMA query_only=ON')
                    db.rollback()
                self.assertIsNone(runtime._snapshot_scope.get())

    def test_unsafe_entry_rejects_before_attach_or_partial_scope_and_fresh_connection_recovers(self):
        for model in (self.native,self.loaded):
            for mutation in ('begin','temp_table','temp_view'):
                with self.subTest(mutation=mutation),closing(core.connect(self.path,readonly=True)) as db:
                    if mutation=='begin':db.execute('BEGIN')
                    elif mutation=='temp_table':db.execute('CREATE TEMP TABLE card(x)')
                    else:db.execute('CREATE TEMP VIEW character_family_member AS SELECT 999 dex_id')
                    with patch.object(model,'_attach',side_effect=AssertionError('unsafe connection attached')):
                        with self.assertRaises(runtime.CatalogSnapshotChanged):
                            with model.request(db):self.fail('unsafe entry accepted')
                    self.assertIsNone(runtime._snapshot_scope.get());db.rollback()
            with closing(core.connect(self.path,readonly=True)) as db:
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],0)
                with model.request(db):
                    self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)
                    self.assertIsNotNone(runtime.snapshot_character_names(db,False))

    def test_clone_schema_mutation_invalidates_cached_reader_and_exit(self):
        for model in (self.native,self.loaded):
            with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.request(db):
                    self.assertIsNotNone(runtime.snapshot_text_dex_card_ids(db,('25',)))
                    db.execute('PRAGMA query_only=OFF');db.execute('DROP INDEX collector_snapshot.card_lookup');db.execute('PRAGMA query_only=ON')
                    with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_text_dex_card_ids(db,('25',))

    def test_stale_open_handle_cannot_load_replacement_database_artifact_or_revision(self):
        replacement=self.base/'replacement.sqlite3';replacement.write_bytes(self.path.read_bytes())
        with closing(core.connect(replacement)) as db:
            db.execute("UPDATE card SET name='Synthetic replacement source name'");db.commit()
        replacement_directory=self.base/'replacement-artifact'
        with closing(core.connect(replacement,readonly=True)) as db:
            receipt=artifact.write(db,self.manifest,replacement_directory)
        with closing(core.connect(self.path,readonly=True)) as old:
            before=collector_journey.catalog_revision(old)
            old_name=old.execute('SELECT name FROM card ORDER BY card_id LIMIT 1').fetchone()[0]
            os.replace(replacement,self.path)
            # SQLite's already-open handle remains on A while the pathname is B.
            self.assertEqual(old.execute('SELECT name FROM card ORDER BY card_id LIMIT 1').fetchone()[0],old_name)
            self.assertNotEqual(before,receipt['canonical_revision'])
            with patch.object(artifact,'_restore',side_effect=AssertionError('stale handle allocated facts')):
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    artifact.load(old,replacement_directory,self.manifest,expected_seal_sha256=receipt['seal_sha256'])
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(old)
            with self.assertRaises(runtime.CatalogSnapshotChanged):
                with self.native.request(old):self.fail('stale native handle served')
        with closing(core.connect(self.path,readonly=True)) as fresh:
            loaded,revision,_=artifact.load(fresh,replacement_directory,self.manifest,expected_seal_sha256=receipt['seal_sha256'])
            self.assertEqual(revision,collector_journey.catalog_revision(fresh))
            with loaded.request(fresh):self.assertIsNotNone(runtime.snapshot_character_names(fresh,False))

    def test_unknown_raw_handle_or_wrong_fresh_file_stamp_never_allocates_shared_facts(self):
        with closing(sqlite3.connect(self.path)) as raw:
            raw.row_factory=sqlite3.Row
            with patch.object(artifact,'_restore',side_effect=AssertionError('untracked handle allocated facts')):
                with self.assertRaises(runtime.CatalogReadModelUnsupported):
                    artifact.load(raw,self.directory,self.manifest,expected_seal_sha256=self.seal_pin)
            with self.assertRaises(runtime.CatalogReadModelUnsupported):runtime.CatalogReadModel(raw)
            self.assertGreater(raw.execute('SELECT count(*) FROM card').fetchone()[0],0)
        for model in (self.native,self.loaded):
            with closing(core.connect(self.path,readonly=True)) as fresh:
                path,device,inode=fresh._catalog_open_file_identity
                fresh._catalog_open_file_identity=(str(self.base/'wrong.sqlite3'),device,inode)
                with patch.object(model,'_attach',side_effect=AssertionError('wrong stamp attached')):
                    with self.assertRaises(runtime.CatalogSnapshotChanged):
                        with model.request(fresh):self.fail('wrong file stamp served')

    def test_first_creation_allows_native_imports_but_requires_reopen_before_acceleration(self):
        created=self.base/'new-catalog.sqlite3'
        with closing(core.connect(created)) as first:
            self.assertIsNone(first._catalog_open_file_identity)
            core.init_db(first)
            core.import_cards(first,[dict(language='ja',set_code='SYNTHETIC',collector_number='001',
                variant='normal',name='Synthetic test-only',provenance='synthetic',
                rights_reference='synthetic-test-only',match_eligible=True)])
            first.commit()
            self.assertEqual(first.execute('SELECT count(*) FROM card').fetchone()[0],1)
            with self.assertRaises(runtime.CatalogReadModelUnsupported):runtime.CatalogReadModel(first)
            with patch.object(artifact,'_restore',side_effect=AssertionError('first-created handle allocated facts')):
                with self.assertRaises(runtime.CatalogReadModelUnsupported):
                    artifact.load(first,self.directory,self.manifest,expected_seal_sha256=self.seal_pin)
        directory=self.base/'new-catalog-artifact'
        with closing(core.connect(created,readonly=True)) as finalized:
            self.assertIsNotNone(finalized._catalog_open_file_identity)
            receipt=artifact.write(finalized,self.manifest,directory)
        with closing(core.connect(created,readonly=True)) as finalized:
            loaded,revision,_=artifact.load(finalized,directory,self.manifest,expected_seal_sha256=receipt['seal_sha256'])
            self.assertEqual(revision,collector_journey.catalog_revision(finalized))
            with loaded.request(finalized):
                self.assertEqual(finalized.execute('SELECT count(*) FROM card').fetchone()[0],1)


if __name__=='__main__':unittest.main()

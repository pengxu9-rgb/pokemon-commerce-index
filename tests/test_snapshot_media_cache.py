"""Disposable synthetic source facts; no artwork or authority is acquired."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch

from pokemon_index import (catalog_media, collector_discovery, collector_runtime as runtime,
                           core, number_evidence, source_image_facts, variant_dimension_hold)
from tests import test_catalog_media as fixtures


class SnapshotMediaCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'catalog.sqlite3'
        self.fixture=fixtures.CatalogMediaTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.cid=self.fixture.cid;self.fact=self.fixture.fact()
        source_image_facts.import_evidence(self.fixture.db,[self.fact])
        # Shared names, numbers and artworks never transfer source evidence.
        for language,code,number,variant,name in [
                ('ja','SVP','037/225','holo_set_logo','ピィ'),
                ('en','SVP','037/225','holo','Cleffa'),
                ('en','SVP','037/225','normal_stamp','Cleffa'),
                ('en','PR','037/225','normal','Cleffa'),
                ('en','SVP','038/225','normal','Cleffa ex'),
                ('en','SVP','039/225','normal','Cleffa EX'),
                ('en','SVP','040/225','normal',"Trainer’s Cleffa")]:
            core.import_cards(self.fixture.db,[dict(language=language,set_code=code,
                collector_number=number,variant=variant,name=name,provenance='synthetic-test-only',
                rights_reference='synthetic-test-only',match_eligible=True)])
        with closing(core.connect(self.path)) as db:self.fixture.db.backup(db)
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.model=self.build()

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    def build(self,path=None):
        with closing(core.connect(path or self.path,readonly=True)) as db:
            with runtime.sqlite_deadline(db,time.monotonic()+8):
                return runtime.CatalogReadModel(db)

    def copy_path(self,name):
        path=Path(self.tmp.name)/name
        with closing(core.connect(self.path,readonly=True)) as a,closing(core.connect(path)) as b:a.backup(b)
        return path

    def test_only_fully_validated_exact_ids_cached_and_returned_sets_are_detached(self):
        with closing(core.connect(self.path,readonly=True)) as db:
            native=catalog_media.current_ids(db)
            contexts={r[0]:catalog_media.availability(db,r[0]) for r in db.execute('SELECT card_id FROM card')}
        self.assertEqual(native,{self.cid})
        self.assertIsInstance(self.model._media_ids,frozenset)
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            # Membership requires no repeat evidence sweep, but full per-card
            # response validation still uses the original native implementation.
            with patch.object(catalog_media,'subjects',side_effect=AssertionError('repeat sweep')):
                first=catalog_media.current_ids(db);first.clear();first.add('synthetic:poison')
                self.assertEqual(catalog_media.current_ids(db),native)
            self.assertEqual({cid:catalog_media.availability(db,cid) for cid in contexts},contexts)
            for ctx in contexts.values():
                for field in ('display_allowed','physical_printing_verified','live_fetch_verified'):
                    self.assertIs(ctx[field],False)

    def test_constructor_rejects_any_temp_table_or_view_before_native_builders(self):
        # These readers use SQLite's native namespace resolution. A constructor
        # must abstain before validating even one shadowed row or publishing facts.
        names=('card','card_reference','discovery_card_facet',
               'source_image_fact_evidence','card_number_reading_evidence')
        for kind in ('TABLE','VIEW'):
            for name in names:
                with self.subTest(kind=kind,name=name),closing(core.connect(self.path,readonly=True)) as db:
                    statement=(f'CREATE TEMP TABLE {name}(synthetic TEXT)' if kind=='TABLE'
                               else f'CREATE TEMP VIEW {name} AS SELECT "poison" AS synthetic')
                    db.execute(statement);db.commit()
                    with patch.object(catalog_media,'current_ids',side_effect=AssertionError('partial cache built')):
                        with self.assertRaises(runtime.CatalogReadModelUnsupported):runtime.CatalogReadModel(db)
                    self.assertEqual([r[1] for r in db.execute('PRAGMA database_list')],['main','temp'])
        with closing(core.connect(self.path,readonly=True)) as fresh,self.model.request(fresh):
            self.assertEqual(catalog_media.current_ids(fresh),{self.cid})

    def test_uncommitted_identity_source_or_rights_changes_revalidate_and_rollback(self):
        for column,value in [('name','Changed ピィ'),('provenance','other-source'),
                             ('rights_reference','other-rights'),('collector_number','038/225'),
                             ('variant','synthetic_finish'),('language','fr')]:
            with self.subTest(column=column),closing(core.connect(self.path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
                self.assertEqual(catalog_media.current_ids(db),{self.cid})
                db.execute('PRAGMA query_only=OFF')
                db.execute(f'UPDATE card SET {column}=? WHERE card_id=?',(value,self.cid))
                self.assertIsNone(runtime.snapshot_media_ids(db))
                self.assertEqual(catalog_media.current_ids(db),set())
                self.assertEqual(catalog_media.availability(db,self.cid)['status'],'stale_source_scan_evidence')
                db.rollback();db.execute('PRAGMA query_only=ON')
                self.assertIsNone(runtime.snapshot_media_ids(db))
                self.assertEqual(catalog_media.current_ids(db),{self.cid})

    def test_same_connection_deleted_fact_and_policy_edit_do_not_serve_old_membership(self):
        with closing(core.connect(self.path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
            db.execute('PRAGMA query_only=OFF');db.execute('DELETE FROM source_image_fact_evidence')
            self.assertEqual(catalog_media.current_ids(db),set())
            db.rollback()
            # A policy mutation must invalidate static facts even when the native
            # advisory scan policy itself still denies every display permission.
            db.execute('''INSERT INTO source_policy
                (source,rights_reference,ingest_allowed,display_allowed,cross_source_use_allowed,
                 seller_analytics_allowed,retention_days,listing_ttl_hours)
                VALUES ('synthetic-policy','test-only',0,0,0,0,1,1)''')
            self.assertIsNone(runtime.snapshot_media_ids(db))
            self.assertEqual(catalog_media.current_ids(db),{self.cid})
            self.assertFalse(catalog_media.availability(db,self.cid)['display_allowed'])
            db.rollback()

    def test_corrupt_review_or_hash_raises_and_never_reuses_cached_positive(self):
        for mutation in ('review','hash','permission'):
            with self.subTest(mutation=mutation),closing(core.connect(self.path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
                row=copy.deepcopy(self.fact)
                if mutation=='review':row['reviews'][0]['image_sha256']='e'*64
                if mutation=='hash':row['source_file_sha256']='e'*64
                if mutation=='permission':row['display_allowed']=True
                db.execute('PRAGMA query_only=OFF')
                db.execute('UPDATE source_image_fact_evidence SET record_json=?',(json.dumps(row),))
                with self.assertRaises(ValueError):catalog_media.current_ids(db)
                db.rollback()
                self.assertEqual(catalog_media.current_ids(db),{self.cid})

    def test_constructor_cannot_publish_corrupt_or_partial_evidence_validation(self):
        path=self.copy_path('corrupt.sqlite3')
        with closing(core.connect(path)) as db:
            row=copy.deepcopy(self.fact);row['reviews'][0]['image_sha256']='e'*64
            db.execute('UPDATE source_image_fact_evidence SET record_json=?',(json.dumps(row),));db.commit()
        with self.assertRaises(ValueError):self.build(path)
        self.assertIsNone(runtime._snapshot_scope.get())
        with patch.object(runtime.CatalogReadModel,'MAX_MEDIA_IDS',0):
            with self.assertRaisesRegex(ValueError,'source-scan IDs'):self.build()

    def test_empty_cached_membership_is_not_sticky_after_new_evidence(self):
        path=self.copy_path('empty.sqlite3')
        with closing(core.connect(path)) as db:db.execute('DELETE FROM source_image_fact_evidence');db.commit()
        model=self.build(path)
        with closing(core.connect(path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):
            self.assertEqual(catalog_media.current_ids(db),set())
            db.execute('PRAGMA query_only=OFF')
            db.execute('INSERT INTO source_image_fact_evidence VALUES (?,?,?,?)',
                       (self.fact['event_id'],self.cid,1,json.dumps(self.fact)))
            self.assertEqual(catalog_media.current_ids(db),{self.cid})
            db.rollback()
        with closing(core.connect(path)) as writer:source_image_facts.import_evidence(writer,[self.fact])
        with closing(core.connect(path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
            with model.request(db):self.fail('changed file accepted')
        fresh=self.build(path)
        with closing(core.connect(path,readonly=True)) as db,fresh.request(db):
            self.assertEqual(catalog_media.current_ids(db),{self.cid})

    def test_other_database_and_native_mutable_callers_never_use_shared_ids(self):
        other=self.copy_path('other.sqlite3')
        with closing(core.connect(other)) as db:db.execute('DELETE FROM source_image_fact_evidence');db.commit()
        with closing(core.connect(self.path,readonly=True)) as a,closing(core.connect(other)) as b,self.model.request(a):
            self.assertEqual(catalog_media.current_ids(a),{self.cid})
            self.assertIsNone(runtime.snapshot_media_ids(b));self.assertEqual(catalog_media.current_ids(b),set())
            source_image_facts.import_evidence(b,[self.fact])
            self.assertEqual(catalog_media.current_ids(b),{self.cid})
        with closing(core.connect(other,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
            with self.model.request(db):self.fail('wrong file accepted')

    def test_external_wal_commit_and_atomic_replacement_fail_closed(self):
        for replacement in (False,True):
            path=self.copy_path('replaced.sqlite3' if replacement else 'wal.sqlite3')
            if not replacement:
                with closing(core.connect(path)) as db:db.execute('PRAGMA journal_mode=WAL')
            model=self.build(path)
            with closing(core.connect(path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged):
                with model.request(db):
                    self.assertEqual(catalog_media.current_ids(db),{self.cid})
                    if replacement:
                        substitute=self.copy_path('replacement.sqlite3');substitute.replace(path)
                    else:
                        with closing(core.connect(path)) as writer:
                            writer.execute('DELETE FROM source_image_fact_evidence');writer.commit()
                    catalog_media.current_ids(db)
            self.assertIsNone(runtime._snapshot_scope.get())

    def test_temp_shadow_after_warm_request_uses_native_current_namespace(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
            self.assertEqual(catalog_media.current_ids(db),{self.cid})
            db.execute('PRAGMA query_only=OFF')
            db.execute('CREATE TEMP TABLE source_image_fact_evidence AS SELECT * FROM main.source_image_fact_evidence WHERE 0')
            db.commit();db.execute('PRAGMA query_only=ON')
            self.assertIsNone(runtime.snapshot_media_ids(db))
            self.assertEqual(catalog_media.current_ids(db),set())
            db.execute('PRAGMA query_only=OFF');db.execute('DROP TABLE temp.source_image_fact_evidence')

    def test_new_uncommitted_identity_hold_abstains_without_cache_override(self):
        with closing(core.connect(self.path)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.model.request(db):
            db.execute('PRAGMA query_only=OFF')
            # A deliberately unqualified synthetic hold is conservatively held
            # by native semantics; it is not an identity approval or real source.
            row=dict(schema=variant_dimension_hold.SCHEMA,event_id='synthetic-test-only',
                identity=dict(card_id=self.cid),legacy_variant='holo_set_logo',declared_size='synthetic',
                reason='test-only unresolved dimensions',source=dict(revision='a'*40,sha256='b'*64))
            db.execute('INSERT INTO catalog_identity_quarantine VALUES (?,?,?)',
                       ('variant-dimension-hold:synthetic-test-only',row['reason'],json.dumps(row)))
            self.assertEqual(catalog_media.current_ids(db),set())
            self.assertEqual(catalog_media.availability(db,self.cid)['status'],'identity_hold')
            db.rollback();self.assertEqual(catalog_media.current_ids(db),{self.cid})

    def test_stale_primary_does_not_fall_through_and_secondary_conflict_stays_held(self):
        path=self.copy_path('secondary.sqlite3')
        with closing(core.connect(path)) as db:
            db.execute("UPDATE card SET name='Cleffa updated' WHERE card_id=?",(self.cid,));db.commit()
            row=copy.deepcopy(self.fixture.row);row['endpoint_snapshot']=number_evidence.snapshot(db,self.cid)
            row['identity_sha256']=number_evidence.supported_catalog.digest(row['endpoint_snapshot'])
            for review in row['review_groups'][0]['reviews']:review['observed_name']='Cleffa updated'
            self.fixture.sign(row);number_evidence.import_evidence(db,[row])
        model=self.build(path)
        with closing(core.connect(path,readonly=True)) as db,model.request(db):
            self.assertEqual(catalog_media.current_ids(db),set())
            self.assertEqual(catalog_media.availability(db,self.cid)['evidence_basis'],'source_image_facts')
        with closing(core.connect(path)) as db:
            db.execute('DELETE FROM source_image_fact_evidence');db.execute('DELETE FROM card_number_reading_evidence');db.commit()
            for review in row['review_groups'][0]['reviews']:review['observed_number_text']='038/225'
            row['status']='different_text_observed';self.fixture.sign(row);number_evidence.import_evidence(db,[row])
        model=self.build(path)
        with closing(core.connect(path,readonly=True)) as db,model.request(db):
            self.assertEqual(catalog_media.current_ids(db),set())
            self.assertEqual(catalog_media.availability(db,self.cid)['status'],'held_source_scan_evidence')

    def test_expired_cache_and_constructor_work_cannot_escape_deadline(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
            with self.assertRaises(runtime.CatalogDeadline):
                with runtime.sqlite_deadline(db,time.monotonic()-1):catalog_media.current_ids(db)
        with closing(core.connect(self.path,readonly=True)) as db:
            with patch.object(runtime.time,'monotonic',return_value=0) as clock:
                native_evidence=catalog_media.evidence
                def slow(*args):
                    clock.return_value=2
                    return native_evidence(*args)
                with patch.object(catalog_media,'evidence',side_effect=slow):
                    with self.assertRaises(runtime.CatalogDeadline):
                        with runtime.sqlite_deadline(db,1):runtime.CatalogReadModel(db)
        self.assertIsNone(runtime._snapshot_scope.get())

    def test_exact_native_and_accelerated_json_for_unicode_promos_and_finish_siblings(self):
        for query in (self.cid,'en:SVP:037/225:normal','ja:SVP:037/225:holo_set_logo',
                      'English Cleffa cards','日本語のピィ','Cleffa EX','Trainer’s Cleffa'):
            with self.subTest(query=query):
                with closing(core.connect(self.path,readonly=True)) as db:
                    expected=collector_discovery.execute(db,query,limit=100,with_source_scans=True)
                with closing(core.connect(self.path,readonly=True)) as db,self.model.request(db):
                    self.assertEqual(collector_discovery.execute(db,query,limit=100,with_source_scans=True),expected)


if __name__=='__main__':unittest.main()

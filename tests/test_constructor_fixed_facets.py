"""Fixed constructor facet reuse preserves native queries and sticky namespaces."""
from contextlib import closing
import ast
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pokemon_index import (core,collector_runtime as runtime,collector_character_affiliation as affiliation,
    card_source_context_index as index,catalog_read_model_artifact as artifact,number_evidence,
    source_image_facts,discovery_graph,catalog_media)
from tests import test_catalog_media as media_fixture
from tests import test_collector_character_affiliation as affiliation_fixture
from pokemon_index import supported_catalog


def typed(rows):
    return tuple(tuple((type(value),value) for value in row) for row in rows)


class ConstructorFixedFacetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.path=self.root/'db.sqlite3'
        self.f=media_fixture.CatalogMediaTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.cid=self.f.cid
        source_image_facts.import_evidence(self.f.db,[self.f.fact()])
        self.save()

    def save(self):
        self.f.db.commit()
        with closing(core.connect(self.path)) as db:self.f.db.backup(db)

    def attach(self,db):
        db.execute("ATTACH DATABASE ':memory:' AS collector_snapshot")
        db.execute('CREATE TABLE collector_snapshot.facets(card_id BLOB,facet_type BLOB,value BLOB,provenance TEXT,rights_reference BLOB)')
        db.execute('INSERT INTO collector_snapshot.facets SELECT * FROM main.discovery_card_facet')
        db.execute('CREATE INDEX collector_snapshot.facet_lookup ON facets(facet_type,value,card_id)')
        db.execute('CREATE INDEX collector_snapshot.card_lookup ON facets(card_id,facet_type,value)')
        db.commit();db.execute('PRAGMA query_only=ON')

    def test_original_artist_sql_stays_native_and_alias_rows_order_types_equal(self):
        for reverse in (0,1):
            with closing(core.connect(self.path,readonly=True)) as db:
                db.execute('PRAGMA reverse_unordered_selects='+str(reverse))
                expected=typed(db.execute(runtime.VOCABULARY_SQL['character_aliases']))
                native=affiliation.affiliations(db)
                self.attach(db)
                with runtime._constructor_snapshot(db):
                    self.assertEqual(expected,typed(db.execute(runtime._CONSTRUCTOR_CHARACTER_ALIAS_SQL)))
                    self.assertEqual(native,affiliation._constructor_affiliations(db))
                    self.assertEqual(affiliation._anchor_groups(db,['Cleffa']),
                                     affiliation._constructor_anchor_groups(db,['Cleffa']))
        self.assertIn('FROM discovery_card_facet',runtime.VOCABULARY_SQL['artists'])

    def test_constructor_denies_and_sticky_poison_survives_caught_write(self):
        operations=["PRAGMA query_only=OFF",'PRAGMA main.schema_version=10',
            'PRAGMA temp.schema_version=10','PRAGMA collector_snapshot.schema_version=10',
            'PRAGMA optimize','BEGIN','SAVEPOINT x','CREATE TEMP TABLE poison(x)',
            'CREATE TABLE main.poison(x)',"UPDATE main.card SET name=name", 
            'DELETE FROM collector_snapshot.facets',"ATTACH DATABASE ':memory:' AS poison"]
        for sql in operations:
            with self.subTest(sql=sql),closing(core.connect(self.path,readonly=True)) as db:
                self.attach(db)
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with runtime._constructor_snapshot(db):
                        try:db.execute(sql)
                        except runtime.CatalogSnapshotChanged:pass
                self.assertIsNone(getattr(db,'_catalog_clone_guard',None))
                self.assertIsNone(runtime._constructor_scope.get())
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],1)

    def test_constructor_denies_authorizer_replacement_and_deserialize(self):
        for operation in (lambda db:db.set_authorizer(None),lambda db:db.deserialize(b'')):
            with closing(core.connect(self.path,readonly=True)) as db:
                self.attach(db)
                with self.assertRaises(runtime.CatalogSnapshotChanged):
                    with runtime._constructor_snapshot(db):
                        try:operation(db)
                        except runtime.CatalogSnapshotChanged:pass

    def test_prior_authorizer_restored_after_success_and_original_error(self):
        for error in (None,ValueError('original')):
            with closing(core.connect(self.path,readonly=True)) as db:
                self.attach(db);calls=[]
                def prior(*args):calls.append(args);return sqlite3.SQLITE_OK
                db.set_authorizer(prior)
                try:
                    with runtime._constructor_snapshot(db):
                        db.execute('SELECT name FROM card').fetchall()
                        if error:raise error
                except ValueError as actual:self.assertIs(actual,error)
                self.assertIs(db._catalog_authorizer,prior)
                self.assertIsNone(getattr(db,'_catalog_clone_guard',None));self.assertTrue(calls)
                db.execute('PRAGMA query_only=OFF')
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0],0)

    def corrupt_secondary(self):
        self.f.db.execute('INSERT INTO card_number_reading_evidence VALUES(?,?,?,?)',
            ('invalid-secondary',self.cid,1,'{}'));self.save()

    def test_valid_or_stale_primary_corrupt_secondary_defers_same_native_error(self):
        self.corrupt_secondary()
        for stale in (False,True):
            if stale:
                self.f.db.execute('UPDATE card SET name=? WHERE card_id=?',('Changed snapshot',self.cid));self.save()
            with closing(core.connect(self.path,readonly=True)) as db:
                model=runtime.CatalogReadModel(db)
                self.assertTrue(model._card_source_context_index.enabled)
                self.assertIsNone(model._card_source_context_index.identity_flags)
                self.assertFalse(model._card_source_context_index.counts()['identity_advisory_available'])
                self.assertIsNone(model._card_source_context_index.lookup_identity_flags(self.cid))
            with closing(core.connect(self.path,readonly=True)) as db:
                with self.assertRaisesRegex(ValueError,'invalid number evidence schema'):
                    discovery_graph.endpoint_identity_blockers(db,self.cid)
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                self.assertIsNone(runtime.snapshot_identity_inputs(db,self.cid))
                with self.assertRaisesRegex(ValueError,'invalid number evidence schema'):
                    discovery_graph.endpoint_identity_blockers(db,self.cid)
            restored=index.restore_index(model._card_source_context_index.to_state())
            self.assertIsNone(restored.identity_flags)
            self.assertEqual(restored.to_state(),model._card_source_context_index.to_state())

    def test_no_primary_corrupt_secondary_retains_bootstrap_error(self):
        self.corrupt_secondary()
        self.f.db.execute('DELETE FROM source_image_fact_evidence');self.save()
        with closing(core.connect(self.path,readonly=True)) as db:
            with self.assertRaisesRegex(ValueError,'invalid number evidence schema'):runtime.CatalogReadModel(db)

    def test_deadline_sql_and_primary_errors_are_not_advisory_fallback(self):
        for error in (runtime.CatalogDeadline(),runtime.CatalogSnapshotChanged(),sqlite3.OperationalError('synthetic SQL')):
            with closing(core.connect(self.path,readonly=True)) as db,patch.object(number_evidence,'context',side_effect=error):
                with self.assertRaises(type(error)) as caught:runtime.CatalogReadModel(db)
                self.assertIs(caught.exception,error)
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(source_image_facts,'context',side_effect=ValueError('bad primary')):
            with self.assertRaisesRegex(ValueError,'bad primary'):runtime.CatalogReadModel(db)

    def test_null_unavailable_differs_from_valid_empty_flags(self):
        with closing(core.connect(self.path,readonly=True)) as db:model=runtime.CatalogReadModel(db)
        state=model._card_source_context_index.to_state();state['identity_flags']={}
        empty=index.restore_index(state);self.assertEqual(empty.lookup_identity_flags(self.cid),index.EMPTY_IDENTITY_FLAGS)
        state['identity_flags']=None
        missing=index.restore_index(state);self.assertIsNone(missing.lookup_identity_flags(self.cid))
        self.assertNotEqual(empty.counts(),missing.counts())
        disabled=index.disabled_index().to_state();disabled['identity_flags']={}
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(disabled)

    def test_secondary_failure_cannot_swallow_mutation_then_restore_attempt(self):
        original=number_evidence.context
        def bad(db,cid):
            if cid==self.cid:
                try:db.execute('PRAGMA query_only=OFF')
                except runtime.CatalogSnapshotChanged:pass
                raise ValueError('secondary error')
            return original(db,cid)
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(number_evidence,'context',side_effect=bad):
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(db)

    def test_nonempty_affiliation_full_json_anchor_order_and_direct_set(self):
        f=affiliation_fixture.CharacterAffiliationTests();f.setUp();self.addCleanup(f.tearDown)
        for n in range(2,6):f.add_anchor(f'{n:03}/100',151)
        f.db.commit()
        for reverse in (0,1):
            f.db.execute('PRAGMA reverse_unordered_selects='+str(reverse))
            with patch.object(affiliation,'_bindings',return_value=[f.binding]),patch.object(supported_catalog,'support_for_card',return_value={'status':'supported_for_internal_review','evidence':f.support}):
                expected=affiliation.affiliations(f.db);self.assertTrue(expected)
                self.attach(f.db)
                actual=affiliation._constructor_affiliations(f.db)
                self.assertEqual(artifact._json_bytes(expected),artifact._json_bytes(actual))
                self.assertEqual(expected[f.cid]['reason']['anchor_count'],5)
                self.assertEqual(affiliation._anchor_groups(f.db,['ミュウ']),affiliation._constructor_anchor_groups(f.db,['ミュウ']))
                native={ (type(row[0]),row[0]) for row in f.db.execute("SELECT DISTINCT card_id FROM discovery_card_facet WHERE facet_type='dex_id'") }
                fast={ (type(row[0]),row[0]) for row in f.db.execute("SELECT DISTINCT card_id FROM collector_snapshot.facets WHERE facet_type='dex_id'") }
                self.assertEqual(native,fast)
                f.db.execute('PRAGMA query_only=OFF');f.db.execute('DETACH DATABASE collector_snapshot')

    def test_first_fast_query_atomic_replacement_is_rejected_on_error_exit(self):
        original=core._CatalogConnection.execute;changed=False
        replacement=self.root/'replacement.sqlite3';replacement.write_bytes(self.path.read_bytes())
        def execute(db,sql,parameters=()):
            nonlocal changed
            result=original(db,sql,parameters)
            if sql==runtime._CONSTRUCTOR_CHARACTER_ALIAS_SQL and not changed:
                changed=True;replacement.replace(self.path)
                raise ValueError('original after-fast-query error')
            return result
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(core._CatalogConnection,'execute',execute):
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(db)
            self.assertIsNone(getattr(db,'_catalog_clone_guard',None))
        self.assertTrue(changed)

    def test_first_fast_query_caught_poison_cannot_take_unsupported_fallback(self):
        original=core._CatalogConnection.execute;changed=False
        def execute(db,sql,parameters=()):
            nonlocal changed
            if sql==runtime._CONSTRUCTOR_CHARACTER_ALIAS_SQL and not changed:
                changed=True
                try:original(db,'CREATE TEMP TABLE poison(x)')
                except runtime.CatalogSnapshotChanged:pass
                raise index.ContextIndexUnsupported('unsupported after poison')
            return original(db,sql,parameters)
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(core._CatalogConnection,'execute',execute):
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(db)
        self.assertTrue(changed)

    def test_prior_authorizer_denial_is_not_bypassed_and_restored(self):
        with closing(core.connect(self.path,readonly=True)) as db:
            self.attach(db)
            def prior(action,first,second,database,source):
                return sqlite3.SQLITE_DENY if action==sqlite3.SQLITE_READ and first=='card' else sqlite3.SQLITE_OK
            db.set_authorizer(prior)
            with self.assertRaises(sqlite3.DatabaseError):
                with runtime._constructor_snapshot(db):db.execute('SELECT name FROM card').fetchall()
            self.assertIs(db._catalog_authorizer,prior)
            self.assertIsNone(getattr(db,'_catalog_clone_guard',None))

    def test_advisory_population_uses_historical_table_ids_not_endpoint_json(self):
        # This is a dependency-set fixture, not an assertion that malformed
        # source records qualify as native evidence.
        self.f.db.execute('INSERT INTO card_number_reading_evidence VALUES(?,?,?,?)',
            ('historical-table-subject',self.cid,1,json.dumps({'card_id':'json-only:not-authority'})))
        self.f.db.execute('INSERT INTO source_image_fact_evidence VALUES(?,?,?,?)',
            ('historical-image-subject',self.cid,2,json.dumps({'card_id':'other:json-subject'})))
        self.f.db.commit()
        ids,union,correction,holds,advisory=index._dependency_population(self.f.db,include_advisories=True)
        self.assertIn(self.cid,advisory);self.assertLessEqual(advisory,union)
        self.assertNotIn('json-only:not-authority',advisory)
        self.assertNotIn('en:SVP:037/225:normal',advisory)
        with self.assertRaises(ValueError):index._native_identity_flags(self.f.db,self.cid)

    def test_advisory_population_covers_all_historical_family_variants_not_languages(self):
        from tests import test_coordinate_family as family_fixture
        from pokemon_index import coordinate_family
        f=family_fixture.CoordinateFamilyTests();f.setUp();self.addCleanup(f.tearDown)
        coordinate_family.import_evidence(f.db,[f.row])
        for lang,variant in [('ja','holo'),('en','normal')]:
            core.import_cards(f.db,[dict(language=lang,set_code='FIX',collector_number='001/100',variant=variant,
                name='synthetic',provenance='new',rights_reference='fixture',match_eligible=True)])
        f.db.commit()
        ids,union,_,_,advisory=index._dependency_population(f.db,include_advisories=True)
        for variant in ('normal','reverse','holo'):
            cid='ja:FIX:001/100:'+variant
            self.assertIn(cid,advisory)
            self.assertEqual(index._native_identity_flags(f.db,cid)[0],'stale_coordinate_family_evidence')
        self.assertNotIn('en:FIX:001/100:normal',advisory)

    def test_advisory_population_includes_superseded_correction_and_new_card_ids(self):
        core.import_cards(self.f.db,[dict(language='en',set_code='NEW',collector_number='1',variant='normal',
            name='Synthetic family',provenance='fixture',rights_reference='fixture')])
        new='en:NEW:1:normal';old='en:SVP:037/225:normal'
        for revision,cid in ((1,old),(2,self.cid)):
            record={'snapshot':{'cards':[{'card_id':cid}]},'new_card':{'card_id':new}}
            self.f.db.execute('INSERT INTO source_correction_evidence VALUES(?,?,?,?,?,?,?,?)',
                ('history:'+str(revision),'same-key',revision,'reference_boundary','en','SVP','037/225',json.dumps(record)))
        self.f.db.commit()
        _,union,correction,_,advisory=index._dependency_population(self.f.db,include_advisories=True)
        self.assertLessEqual({old,self.cid,new},advisory)
        self.assertLessEqual(advisory,union);self.assertLessEqual({old,self.cid,new},correction)

    def test_advisory_missing_history_fields_errors_never_become_empty_flags(self):
        for record in ('{','{}','{"snapshot":{"cards":[{}]}}'):
            self.f.db.execute('DELETE FROM source_correction_evidence')
            self.f.db.execute('INSERT INTO source_correction_evidence VALUES(?,?,?,?,?,?,?,?)',
                ('bad','bad',1,'reference_boundary','en','SVP','037/225',record));self.f.db.commit()
            with self.assertRaises(artifact.ArtifactInvalid):index._dependency_population(self.f.db,include_advisories=True)

    def test_advisory_nontext_subject_or_bound_declines_whole_optimization(self):
        self.f.db.execute('PRAGMA foreign_keys=OFF')
        self.f.db.execute('INSERT INTO card_number_reading_evidence VALUES(?,?,?,?)',
            ('unsupported-table-subject',sqlite3.Binary(b'not-text'),1,'{}'));self.f.db.commit()
        with self.assertRaises(index.ContextIndexUnsupported):index._dependency_population(self.f.db,include_advisories=True)
        self.f.db.execute('DELETE FROM card_number_reading_evidence');self.f.db.commit()
        with patch.object(index,'MAX_CID_BYTES',0),self.assertRaises(index.ContextIndexUnsupported):
            index._dependency_population(self.f.db,include_advisories=True)

    def test_unavailable_flags_survive_original_strict_artifact_write_load(self):
        self.corrupt_secondary()
        manifest=self.root/'manifest.json';manifest.write_text('{"synthetic_only":true}')
        directory=self.root/'nullable-artifact'
        with closing(core.connect(self.path,readonly=True)) as db:
            written=artifact.write(db,manifest,directory)
        with closing(core.connect(self.path,readonly=True)) as db:
            model,_,receipt=artifact.load(db,directory,manifest,expected_seal_sha256=written['seal_sha256'])
        self.assertIsNone(model._card_source_context_index.identity_flags)
        self.assertFalse(receipt['fact_counts']['identity_advisory_available'])
        self.assertGreater(receipt['decoded_state_bytes'],0)
        self.assertLessEqual(receipt['decoded_state_bytes'],artifact.MAX_DECODED_BYTES)
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
            self.assertIsNone(runtime.snapshot_identity_inputs(db,self.cid))
            with self.assertRaisesRegex(ValueError,'invalid number evidence schema'):
                discovery_graph.endpoint_identity_blockers(db,self.cid)

    def test_initial_catalog_scope_and_wal_retain_original_native_fallback(self):
        for case in ('catalog_scope','WAL'):
            writer=None
            if case=='WAL':
                writer=core.connect(self.path);writer.execute('PRAGMA journal_mode=WAL')
                writer.execute("UPDATE card SET name='Changed before constructor'");writer.commit()
            try:
                with closing(core.connect(self.path,readonly=True)) as db,patch.object(affiliation,'_constructor_affiliations',side_effect=AssertionError('fast affiliation on unsupported path')):
                    def construct(db):return runtime.CatalogReadModel(db)
                    if case=='catalog_scope':construct=runtime.catalog_request(construct)
                    model=construct(db)
                    self.assertFalse(model._card_source_context_index.enabled)
                    self.assertIsNone(model._card_source_context_index.identity_flags)
                    self.assertIsNone(getattr(db,'_catalog_clone_guard',None))
            finally:
                if writer is not None:writer.close()

    def test_poison_during_initial_unsupported_probe_cannot_fallback(self):
        original=index._constructor_stamp
        def probe(db):
            try:db.execute('PRAGMA query_only=OFF')
            except runtime.CatalogSnapshotChanged:pass
            raise index.ContextIndexUnsupported('cannot adopt poisoned initial probe')
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(index,'_constructor_stamp',probe),patch.object(affiliation,'affiliations',side_effect=AssertionError('poisoned native fallback')):
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(db)
            self.assertIsNone(getattr(db,'_catalog_clone_guard',None))

    def test_initial_probe_sql_deadline_snapshot_and_data_errors_do_not_fallback(self):
        for error in (sqlite3.OperationalError('probe SQL'),runtime.CatalogDeadline(),runtime.CatalogSnapshotChanged(),ValueError('probe data')):
            with closing(core.connect(self.path,readonly=True)) as db,patch.object(index,'_constructor_stamp',side_effect=error):
                with self.assertRaises(type(error)) as caught:runtime.CatalogReadModel(db)
                self.assertIs(caught.exception,error)
                self.assertIsNone(getattr(db,'_catalog_clone_guard',None))

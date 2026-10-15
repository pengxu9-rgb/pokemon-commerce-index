"""Conditional sparse identity advisories retain native errors and snapshot guards."""
from contextlib import closing
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pokemon_index import (core,collector_runtime as runtime,collector_journey as journey,
    collector_discovery as discovery,card_source_context_index as index,
    catalog_read_model_artifact as artifact,discovery_graph,coordinate_family,
    number_evidence,source_image_facts,source_mechanic,source_corrections,collector_release_alias)
from tests import test_catalog_media as media_fixture
from tests import test_coordinate_family as family_fixture
from tests import test_source_corrections as correction_fixture
from scripts.rehearse_collector_recommendations import create_fixture,SUITE


def native_blockers(db,card):
    """Original journey reader sequence, not an oracle built from cached bits."""
    cid=card['card_id'];blocks=discovery_graph.endpoint_identity_blockers(db,cid)
    if blocks:blocks.append('catalog_identity_review_needed')
    if card.get('official_coordinate_family',{}).get('copy_evidence_needed'):blocks.append('coordinate_family_copy_evidence')
    if card.get('official_metadata',{}).get('official',{}).get('page_kind')=='numbered_parts':blocks.append('numbered_part_copy_evidence')
    if source_corrections.family_scope_only(db,cid):blocks.append('source_family_copy_evidence')
    reading=number_evidence.context(db,cid)
    if reading and (not reading['current_endpoint'] or reading['status']=='reading_hold'):blocks.append('catalog_identity_review_needed')
    facts=source_image_facts.context(db,cid)
    if facts and facts['warnings']:blocks.append('source_image_metadata_resolution')
    return sorted(set(blocks))


class IdentityAdvisoryFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.path=self.base/'catalog.sqlite3'
        fixture=media_fixture.CatalogMediaTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.cid=fixture.cid
        row=copy.deepcopy(fixture.row)
        for review in row['review_groups'][0]['reviews']:review['observed_number_text']='038/225'
        row['status']='different_text_observed';fixture.sign(row);number_evidence.import_evidence(fixture.db,[row])
        fact=fixture.fact()
        for review in fact['reviews']:review['reading']['title_text_parts']=['Not the printed source title']
        fact['event_id']=source_image_facts.event_id(fact);source_image_facts.import_evidence(fixture.db,[fact])
        core.import_cards(fixture.db,[dict(language=lang,set_code='NONE',collector_number='001/100',variant='normal',name='Synthetic',provenance='fixture',rights_reference='fixture',match_eligible=False,attributes_json=json.dumps({'family_scope_only':True})) for lang in ['en','ja','zh-Hant']])
        fixture.db.execute("UPDATE card SET attributes_json=? WHERE set_code='NONE'",(json.dumps({'family_scope_only':True}),))
        fixture.db.commit()
        with closing(core.connect(self.path)) as target:fixture.db.backup(target)
        alias=self.base/'aliases.json';alias.write_bytes(collector_release_alias.BINDINGS_PATH.read_bytes());self.alias=alias
        self.alias_patch=patch.object(collector_release_alias,'BINDINGS_PATH',alias);self.alias_patch.start();self.addCleanup(self.alias_patch.stop)
        self.models=self.build_models(self.path,'initial')

    def tearDown(self):
        self.assertIsNone(runtime._snapshot_scope.get());self.assertIsNone(runtime._catalog_scope.get())

    def build_models(self,path,name):
        manifest=self.base/(name+'.json');manifest.write_text('{"synthetic_only":true}')
        with closing(core.connect(path,readonly=True)) as db:native=runtime.CatalogReadModel(db)
        with closing(core.connect(path,readonly=True)) as db:seal=artifact.write(db,manifest,self.base/name)
        with closing(core.connect(path,readonly=True)) as db:loaded,_,_=artifact.load(db,self.base/name,manifest,expected_seal_sha256=seal['seal_sha256'])
        self.assertEqual(artifact.model_state(native),artifact.model_state(loaded))
        return (native,loaded)

    def cards(self,db):return [discovery._card_result(db,row) for row in discovery._rows(db,'1',())]

    def test_native_materialized_loaded_blockers_and_types_all_fixture_ids(self):
        with closing(core.connect(self.path,readonly=True)) as db:
            cards=self.cards(db);expected={card['card_id']:native_blockers(db,card) for card in cards}
        self.assertIn('source_image_metadata_resolution',expected[self.cid])
        for model in self.models:
            sparse=model._card_source_context_index.identity_flags
            self.assertIn(self.cid,sparse);self.assertIs(type(sparse[self.cid][1]),bool)
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                for card in cards:
                    inputs=runtime.snapshot_identity_inputs(db,card['card_id'])
                    actual=journey._identity_blockers_from_snapshot(card,inputs)
                    self.assertEqual(actual,expected[card['card_id']])
                    self.assertTrue(all(type(value) is str for value in actual))
                    self.assertFalse(any(card.get(key,False) for key in ['price_comparable','automatic_offer_join_allowed','purchase_allowed']))

    def test_raw_family_guard_outside_dependency_union_remains_fresh(self):
        cid='zh-hant:NONE:001/100:normal'
        for model in self.models:
            ctx=model._card_source_context_index
            self.assertNotIn(cid,ctx.assignments);self.assertNotIn(cid,ctx.identity_flags)
            self.assertEqual(ctx.lookup_identity_flags(cid),index.EMPTY_IDENTITY_FLAGS)
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                flags,raw=runtime.snapshot_identity_inputs(db,cid)
                self.assertTrue(index._raw_family_scope_only(raw))
                self.assertIn('source_family_copy_evidence',journey._identity_blockers_from_snapshot({'card_id':cid},(flags,raw)))

    def test_known_default_unknown_and_nontext_native_fallback(self):
        class CID(str):pass
        for model in self.models:
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                for cid in ['unknown:card',b'nontext',123,None,CID(self.cid)]:
                    self.assertIsNone(runtime.snapshot_identity_inputs(db,cid))
                with self.assertRaisesRegex(ValueError,'unknown card'):discovery_graph.endpoint_identity_blockers(db,'unknown:card')
        with closing(core.connect(self.path,readonly=True)) as db:
            self.assertIsNone(runtime.snapshot_identity_inputs(db,self.cid))

    def test_strict_sparse_codec_shape_types_keys_and_old_version(self):
        original=self.models[0]._card_source_context_index.to_state()
        for value in ([None,0,False,False,False],[True,False,False,False,False],['unsupported',False,False,False,False],[None,False,False,False],list(index.EMPTY_IDENTITY_FLAGS),tuple([None,True,False,False,False])):
            state=copy.deepcopy(original);state['identity_flags']={self.cid:value}
            with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        for cid in ['unknown','zh-hant:NONE:001/100:normal',1]:
            state=copy.deepcopy(original);state['identity_flags']={cid:[None,True,False,False,False]}
            with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        state=copy.deepcopy(original);state.pop('identity_flags')
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        state=copy.deepcopy(original);state['schema']='pokemon.complete-card-context-index.v1'
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        raw=b'{"x":[null,true,false,false,false],"x":[null,false,false,false,false]}'
        with self.assertRaises(artifact.ArtifactInvalid):artifact._json(raw,4096)
        self.assertEqual(index.restore_index(original),self.models[0]._card_source_context_index)

    def test_same_existing_caps_and_two_allocation_roots_remain(self):
        model=self.models[0];state=artifact.model_state(model);raw=artifact._json_bytes(state)
        index.validate_aggregate_json_members(state,raw)
        total=artifact._deep_size(state)+artifact._deep_size(model.__dict__)+len(raw)+len(model._image)
        self.assertLess(total,artifact.MAX_DECODED_BYTES)
        with patch.object(artifact,'MAX_JSON_MEMBERS',1),self.assertRaises(artifact.ArtifactInvalid):index.validate_aggregate_json_members(state,raw)
        with patch.object(artifact,'MAX_METADATA_BYTES',len(raw)-1),self.assertRaises(artifact.ArtifactInvalid):index.validate_aggregate_json_members(state,raw)
        self.assertEqual(model._card_source_context_index.counts()['identity_advisory_flag_subjects'],1)

    def test_disabled_index_never_retains_partial_sparse_flags(self):
        state=index.disabled_index().to_state();state['identity_flags']={self.cid:[None,True,False,False,False]}
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        self.assertIsNone(index.disabled_index().lookup_identity_flags(self.cid))

    def test_temp_transaction_and_rollback_rejected_on_hit_default_and_fallback(self):
        for model in self.models:
            for cid in (self.cid,'ja:NONE:001/100:normal','unknown:card'):
                escaped=[]
                with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):
                    runtime.snapshot_identity_inputs(db,self.cid)
                    db.execute('PRAGMA query_only=OFF');db.execute('BEGIN');db.execute('CREATE TEMP VIEW advisory_shadow AS SELECT 1');db.execute('PRAGMA query_only=ON')
                    try:escaped.append(runtime.snapshot_identity_inputs(db,cid))
                    finally:db.rollback();db.execute('PRAGMA query_only=ON')
                self.assertEqual(escaped,[])
                with closing(core.connect(self.path,readonly=True)) as db,model.request(db):self.assertIsNotNone(runtime.snapshot_identity_inputs(db,self.cid))

    def test_clone_mutation_during_fresh_raw_query_fails_before_return(self):
        for model in self.models:
            original=discovery_graph._card;escaped=[]
            with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):
                def corrupt(*args):
                    db.execute('CREATE VIEW collector_snapshot.forbidden_flag_mutation AS SELECT 1')
                    return original(*args)
                with patch.object(discovery_graph,'_card',side_effect=corrupt):
                    with self.assertRaises(runtime.CatalogSnapshotChanged):escaped.append(runtime.snapshot_identity_inputs(db,self.cid))
            self.assertEqual(escaped,[])

    def test_source_alias_mutation_rejects_before_any_flag_default(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.models[0].request(db):
            runtime.snapshot_identity_inputs(db,self.cid);self.alias.write_bytes(self.alias.read_bytes()+b' ')
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_identity_inputs(db,'ja:NONE:001/100:normal')

    def test_atomic_same_bytes_database_replacement_cannot_reuse_flags(self):
        with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.models[0].request(db):
            replacement=self.base/'replacement.sqlite3';replacement.write_bytes(self.path.read_bytes());os.replace(replacement,self.path)
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_identity_inputs(db,self.cid)

    def test_constructor_source_or_namespace_drift_never_publishes_partial_flags(self):
        original=index._native_identity_flags
        for mode in ('query_only','temp','external_write'):
            path=self.base/(mode+'.sqlite3');path.write_bytes(self.path.read_bytes());once=[]
            def corrupt(db,cid):
                result=original(db,cid)
                if not once:
                    once.append(True)
                    if mode=='external_write':
                        with closing(core.connect(path)) as writer:writer.execute("UPDATE card SET attributes_json=? WHERE card_id=?",(json.dumps({"changed":True}),self.cid));writer.commit()
                    else:
                        db.execute('PRAGMA query_only=OFF')
                        if mode=='temp':db.execute('CREATE TEMP VIEW construction_shadow AS SELECT 1');db.execute('PRAGMA query_only=ON')
                return result
            with closing(core.connect(path,readonly=True)) as db,patch.object(index,'_native_identity_flags',side_effect=corrupt),self.assertRaises(runtime.CatalogSnapshotChanged):runtime.CatalogReadModel(db)

    def test_native_image_context_keeps_source_mechanic_validation(self):
        with closing(core.connect(self.path,readonly=True)) as db,patch.object(source_mechanic,'context',side_effect=ValueError('synthetic mechanic invalid')) as validation:
            with self.assertRaisesRegex(ValueError,'synthetic mechanic invalid'):index._native_identity_flags(db,self.cid)
            self.assertEqual(validation.call_count,1)

    def test_original_raw_family_shortcircuit_errors_and_history_fallback(self):
        f=correction_fixture.ReferenceBoundaryCorrectionTests();f.setUp();self.addCleanup(f.tearDown)
        source_corrections.import_evidence(f.db,[f.correction]);cid=f.correction['new_card']['card_id']
        self.assertTrue(source_corrections.family_scope_only(f.db,cid))
        self.assertIs(index._native_identity_flags(f.db,cid)[4],False)  # fresh raw shortcut suffices
        f.db.execute("UPDATE card SET attributes_json='{}',variant='rewritten',provenance='rewritten' WHERE card_id=?",(cid,));f.db.commit()
        self.assertTrue(source_corrections.family_scope_only(f.db,cid));self.assertIs(index._native_identity_flags(f.db,cid)[4],True)
        f.db.execute("UPDATE source_correction_evidence SET record_json='not JSON'");f.db.commit()
        with self.assertRaises(sqlite3.OperationalError):source_corrections.family_scope_only(f.db,cid)
        f.db.execute("UPDATE card SET attributes_json='{\"family_scope_only\":true}' WHERE card_id=?",(cid,));f.db.commit()
        self.assertTrue(source_corrections.family_scope_only(f.db,cid))  # never touches malformed history

    def test_wrong_raw_storage_type_declines_index_and_keeps_native_error(self):
        with closing(core.connect(self.path)) as db:db.execute('UPDATE card SET variant=? WHERE card_id=?',(b'blob-variant',self.cid));db.commit()
        with closing(core.connect(self.path,readonly=True)) as db:
            with self.assertRaises(TypeError):source_corrections.family_scope_only(db,self.cid)
            model=runtime.CatalogReadModel(db)
        self.assertFalse(model._card_source_context_index.enabled)
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
            self.assertIsNone(runtime.snapshot_identity_inputs(db,self.cid))
            with self.assertRaises(TypeError):source_corrections.family_scope_only(db,self.cid)

    def test_all_frozen_journey_prefixes_native_and_loaded_body_parity(self):
        path=self.base/'journeys.sqlite3';suite=json.loads(SUITE.read_text());create_fixture(path,suite);models=self.build_models(path,'journeys')
        for record in suite['journeys']:
            for size in range(1,len(record['steps'])+1):
                payload={'turns':[step['action'] for step in record['steps'][:size]],'limit':suite['limit']}
                with closing(core.connect(path,readonly=True)) as db:
                    try:expected=('result',journey.replay(db,payload,revision='a'*64))
                    except ValueError as error:expected=('error',str(error))
                for model in models:
                    with closing(core.connect(path,readonly=True)) as db,model.request(db):
                        try:actual=('result',journey.replay(db,payload,revision='a'*64))
                        except ValueError as error:actual=('error',str(error))
                    self.assertEqual(actual,expected,(record['id'],size))

    def test_original_raw_family_predicate_types_errors_and_short_circuits(self):
        # The unchanged native helper supplies the oracle; no historical family
        # JSON query is copied into the fixed derived predicate.
        class Rows:
            def __init__(self,row):self.row=row
            def execute(self,sql,args=()):
                class Result:
                    def __init__(self,value):self.value=value
                    def fetchone(self):return self.value
                return Result(self.row if sql.startswith('SELECT variant') else None)
        for attributes in ('{}','{"family_scope_only":true}','{"family_scope_only":1}',
                           '{','[]','null',None,b'{}',23):
            for variant,provenance in (('normal','source'),('official_coordinate_family_only_x','source'),
                    ('normal','official-printed-coordinate:x'),(None,'source'),(b'normal','source'),('normal',None)):
                row={'attributes_json':attributes,'variant':variant,'provenance':provenance}
                def outcome(call):
                    try:
                        value=call();return (type(value),value)
                    except Exception as error:return (type(error),str(error))
                self.assertEqual(outcome(lambda:index._raw_family_scope_only(row)),
                                 outcome(lambda:source_corrections.family_scope_only(Rows(row),'id')))


if __name__=='__main__':unittest.main()

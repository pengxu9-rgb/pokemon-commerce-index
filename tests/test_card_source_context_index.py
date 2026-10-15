"""Complete dependency membership and strict context codec, using synthetic facts."""
from contextlib import closing
import copy
import json
import sqlite3
import unittest
from unittest.mock import patch
from pokemon_index import core,collector_discovery as discovery,collector_runtime as runtime
from pokemon_index import card_source_context_index as index,catalog_read_model_artifact as artifact
from tests import test_printing_evidence as fixture_module


def fixture_card(language,number='001/100',variant='normal'):
    return dict(language=language,set_code='FIX',collector_number=number,variant=variant,
        name='Synthetic '+language,rarity='fixture',provenance='synthetic:context-index',
        rights_reference='synthetic:no-display',match_eligible=True)


def state_with_template():
    context=copy.deepcopy(index.DEFAULT_ABSENT)
    context['official_metadata']={'status':'stale_official_metadata','automatic_offer_join_allowed':False}
    return dict(schema=index.SCHEMA,enabled=True,
        known_card_ids=dict(type='str',values=['1','en:FIX:001/100:normal','ja:FIX:001/100:normal']),
        context_strings=[artifact._json_bytes(context).decode()],
        assignments={'ja:FIX:001/100:normal':0},default_string=index.DEFAULT_ABSENT_JSON,identity_flags={})


class CardSourceContextIndexTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');self.addCleanup(self.db.close);core.init_db(self.db)
        core.import_cards(self.db,[fixture_card('ja'),fixture_card('ja',variant='holo'),
                                  fixture_card('ja','002/100'),fixture_card('en')])

    def test_native_default_complete_universe_and_current_raw_fields_not_retained(self):
        compiled=index.compile_index(self.db)
        self.assertTrue(compiled.enabled)
        ids=[row[0] for row in self.db.execute('SELECT card_id FROM card ORDER BY card_id')]
        self.assertEqual(compiled.counts()['source_context_cards'],4)
        self.assertEqual(compiled.counts()['source_context_assignments'],0)
        for cid in ids:
            self.assertEqual(compiled.lookup(cid),discovery._card_context(self.db,cid))
            self.assertFalse(set(compiled.lookup(cid))&index.BASIC_ROW_KEYS_NOT_CACHED)
        self.assertEqual(index.restore_index(compiled.to_state()),compiled)

    def test_exact_typed_known_ids_unknown_and_unicode_namespaces_do_not_borrow(self):
        state=state_with_template();compiled=index.restore_index(state)
        for wrong in (1,True,b'1',None,'unknown','JA:FIX:001/100:normal'):
            self.assertIsNone(compiled.lookup(wrong))
        class TextSubclass(str):pass
        self.assertIsNone(compiled.lookup(TextSubclass('1')))
        self.assertEqual(compiled.lookup('1'),index.DEFAULT_ABSENT)
        self.assertIn('official_metadata',compiled.lookup('ja:FIX:001/100:normal'))
        self.assertNotIn('official_metadata',compiled.lookup('en:FIX:001/100:normal'))

    def test_returned_nested_containers_and_state_are_private(self):
        compiled=index.restore_index(state_with_template());first=compiled.lookup('ja:FIX:001/100:normal')
        first['media_availability']['warnings'].append('caller poison')
        first['official_metadata']['status']='caller poison'
        self.assertEqual(compiled.lookup('ja:FIX:001/100:normal')['media_availability']['warnings'],[])
        state=compiled.to_state();state['assignments'].clear();state['known_card_ids']['values'].clear()
        self.assertEqual(compiled.counts()['source_context_assignments'],1)
        with self.assertRaises(TypeError):compiled.assignments['new']=0
        self.assertGreater(artifact._deep_size(compiled),artifact._deep_size(tuple()))

    def test_present_invalid_codec_rejected_as_artifact_error(self):
        mutations=[lambda s:s.update(extra=True),lambda s:s.update(enabled=1),
            lambda s:s['known_card_ids'].update(type='int'),
            lambda s:s['known_card_ids']['values'].append('1'),
            lambda s:s['known_card_ids']['values'].append(1),
            lambda s:s['assignments'].update({'ja:FIX:001/100:normal':True}),
            lambda s:s['assignments'].update({'unknown':0}),
            lambda s:s['assignments'].update({'ja:FIX:001/100:normal':1}),
            lambda s:s['context_strings'].append(s['context_strings'][0]),
            lambda s:s['context_strings'].append(index.DEFAULT_ABSENT_JSON),
            lambda s:s.update(default_string='{}'),lambda s:s.update(default_string=None),
            lambda s:s['known_card_ids']['values'].append('\ud800')]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                state=state_with_template();mutate(state)
                with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)

    def test_context_string_noncanonical_duplicate_raw_or_authority_fields_reject(self):
        for change in ('whitespace','duplicate','raw','permission','media missing','media type','media eligibility','optional list'):
            state=state_with_template();ctx=json.loads(state['context_strings'][0])
            if change=='whitespace':raw=json.dumps(ctx,sort_keys=True)
            elif change=='duplicate':raw='{"support_status":"research_candidate","support_status":"stale_support_evidence"}'
            else:
                if change=='raw':ctx['source_rarity']='raw row field'
                if change=='permission':ctx['media_availability']['display_allowed']=True
                if change=='media missing':del ctx['media_availability']['status']
                if change=='media type':ctx['media_availability']['status']=[]
                if change=='media eligibility':ctx['media_availability']['with_source_scans_eligible']=True
                if change=='optional list':ctx['official_metadata']=[]
                raw=artifact._json_bytes(ctx).decode()
            state['context_strings']=[raw]
            with self.subTest(change=change),self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)

    def test_disabled_state_never_retains_partial_data(self):
        disabled=index.disabled_index();self.assertIsNone(disabled.lookup('ja:FIX:001/100:normal'))
        self.assertEqual(index.restore_index(disabled.to_state()),disabled)
        state=state_with_template();state['enabled']=False
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)

    def test_partial_tables_and_population_bounds_disable_all(self):
        with patch.object(index,'MAX_CARD_IDS',3):self.assertFalse(index.compile_index(self.db).enabled)
        with patch.object(index,'MAX_CID_BYTES',1):self.assertFalse(index.compile_index(self.db).enabled)
        self.db.execute('DROP TABLE printing_source_evidence');self.db.commit()
        self.assertFalse(index.compile_index(self.db).enabled)

    def test_nontext_storage_disables_whole_index_without_coercion(self):
        self.db.execute('PRAGMA foreign_keys=OFF')
        self.db.execute('UPDATE card SET card_id=? WHERE language=? AND variant=?',(sqlite3.Binary(b'not-text'),'en','normal'));self.db.commit()
        self.assertFalse(index.compile_index(self.db).enabled)

    def test_malformed_history_is_rejected_not_silently_disabled(self):
        self.db.execute("INSERT INTO source_correction_evidence VALUES ('synthetic','synthetic',1,'printed_artist','ja','FIX','001/100','{')");self.db.commit()
        with self.assertRaises(artifact.ArtifactInvalid):index.compile_index(self.db)
        self.db.execute('UPDATE source_correction_evidence SET record_json=?',(json.dumps({'snapshot':{'cards':[{}]}}),));self.db.commit()
        with self.assertRaises(artifact.ArtifactInvalid):index.compile_index(self.db)

    def test_native_json_containers_never_coerce_and_nonfinite_source_rejects(self):
        for value in ((1,2),b'bytes',{1:'non-string-key'}):
            context=copy.deepcopy(index.DEFAULT_ABSENT)
            context['official_metadata']={'status':'stale_official_metadata','unexpected':value}
            with self.subTest(value=value),patch.object(discovery,'_card_context',return_value=context):
                self.assertFalse(index.compile_index(self.db).enabled)
        context=copy.deepcopy(index.DEFAULT_ABSENT)
        context['official_metadata']={'status':'stale_official_metadata','value':float('nan')}
        with patch.object(discovery,'_card_context',return_value=context),self.assertRaises(artifact.ArtifactInvalid):
            index.compile_index(self.db)

    def test_full_historical_release_coordinate_and_new_card_memberships(self):
        # Raw synthetic rows test conservative dependency expansion only; they
        # do not pretend to pass native evidence approval or produce contexts.
        self.db.execute("INSERT INTO catalog_collector_evidence VALUES ('synthetic-old','release','ja:FIX','finish_exists','mirror','release_declaration','official_release_text','withdrawn',?, '{}')",('a'*64,))
        self.db.execute("INSERT INTO printing_source_evidence VALUES ('synthetic-coordinate','coordinate','en:FIX:001/100',1,'{}')")
        record={'snapshot':{'cards':[{'card_id':'ja:FIX:001/100:normal'}]},'new_card':{'card_id':'en:FIX:001/100:normal'}}
        self.db.execute("INSERT INTO source_correction_evidence VALUES ('synthetic-correction','synthetic',1,'reference_boundary','ja','FIX','001/100',?)",(json.dumps(record),));self.db.commit()
        ids,union=index.dependency_population(self.db)
        self.assertEqual(set(ids),set(union))
        self.assertIn('ja:FIX:001/100:holo',union)
        self.assertIn('ja:FIX:002/100:normal',union)
        self.assertIn('en:FIX:001/100:normal',union)

    def test_coordinate_sources_do_not_transfer_languages_or_merge_variants(self):
        self.db.execute("INSERT INTO printing_source_evidence VALUES ('synthetic','coordinate','ja:FIX:001/100',1,'{}')");self.db.commit()
        _,union=index.dependency_population(self.db)
        self.assertEqual(set(union),{'ja:FIX:001/100:normal','ja:FIX:001/100:holo'})

    def test_classification_and_name_similarity_do_not_create_source_context(self):
        ids=[row[0] for row in self.db.execute('SELECT card_id FROM card ORDER BY card_id')]
        for cid,category in zip(ids,['Pokemon','Trainer','Energy','Pokemon']):
            self.db.execute('INSERT INTO card_classification VALUES (?,?,?,?,?)',
                (cid,category,None,'synthetic:class','synthetic:no-display'))
        self.db.commit();compiled=index.compile_index(self.db)
        self.assertTrue(compiled.enabled)
        self.assertEqual(compiled.counts()['source_context_assignments'],0)
        for cid in ids:self.assertEqual(compiled.lookup(cid),discovery._card_context(self.db,cid))

    def test_existing_depth_and_member_caps_are_not_relaxed_by_nested_strings(self):
        state=state_with_template();ctx=json.loads(state['context_strings'][0])
        nested=False
        for unused in range(artifact.MAX_JSON_DEPTH+1):nested=[nested]
        ctx['official_metadata']['nested']=nested
        state['context_strings']=[artifact._json_bytes(ctx).decode()]
        with self.assertRaises(artifact.ArtifactInvalid):index.restore_index(state)
        state=dict(affiliations_json='[]',release_aliases_json='[]',
            card_source_context_index=state_with_template())
        raw=artifact._json_bytes(state)
        with patch.object(artifact,'MAX_JSON_MEMBERS',index._member_count(raw)),self.assertRaises(artifact.ArtifactInvalid):
            index.validate_aggregate_json_members(state,raw)

    def test_native_printing_context_complete_compile_keeps_credit_scope(self):
        fixture=fixture_module.PrintingEvidenceTests();fixture.setUp()
        try:
            from pokemon_index import printing_evidence
            printing_evidence.import_evidence(fixture.db,[fixture.row])
            core.import_cards(fixture.db,[fixture_card('en')])
            compiled=index.compile_index(fixture.db);self.assertTrue(compiled.enabled)
            self.assertEqual(compiled.lookup(fixture.cid),discovery._card_context(fixture.db,fixture.cid))
            self.assertEqual(compiled.lookup(fixture.cid)['printed_artist_credit']['value'],'Printed Artist')
            self.assertNotIn('printed_artist_credit',compiled.lookup('en:FIX:001/100:normal'))
        finally:fixture.tearDown()

    def test_aggregate_counts_old_proofs_and_unique_new_roots_together(self):
        state=dict(affiliations_json='[1,2,3]',release_aliases_json='[4,5]',
                   card_source_context_index=state_with_template())
        raw=artifact._json_bytes(state)
        roots={state['affiliations_json'],state['release_aliases_json'],*state['card_source_context_index']['context_strings'],state['card_source_context_index']['default_string']}
        full=index._member_count(raw)+sum(index._member_count(value.encode()) for value in roots)
        with patch.object(artifact,'MAX_JSON_MEMBERS',full):index.validate_aggregate_json_members(state,raw)
        with patch.object(artifact,'MAX_JSON_MEMBERS',full-1),self.assertRaises(artifact.ArtifactInvalid):index.validate_aggregate_json_members(state,raw)
        state['affiliations_json']=state['release_aliases_json'];raw=artifact._json_bytes(state)
        roots={state['affiliations_json'],*state['card_source_context_index']['context_strings'],state['card_source_context_index']['default_string']}
        unique=index._member_count(raw)+sum(index._member_count(value.encode()) for value in roots)
        with patch.object(artifact,'MAX_JSON_MEMBERS',unique):index.validate_aggregate_json_members(state,raw)

    def test_template_and_string_bounds_disable_all_not_partial(self):
        fixture=fixture_module.PrintingEvidenceTests();fixture.setUp()
        try:
            from pokemon_index import printing_evidence
            printing_evidence.import_evidence(fixture.db,[fixture.row])
            with patch.object(index,'MAX_TEMPLATES',0):self.assertFalse(index.compile_index(fixture.db).enabled)
            with patch.object(index,'MAX_CONTEXT_BYTES',1):self.assertFalse(index.compile_index(fixture.db).enabled)
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()

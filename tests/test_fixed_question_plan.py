"""Fixed eager parser facts: native parity, strict restoration and real guards."""
from contextlib import closing
import copy
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index import core, collector_runtime as runtime
from pokemon_index import collector_discovery as discovery
from pokemon_index import collector_journey as journey
from pokemon_index import collector_recommendation as recommendation
from pokemon_index import catalog_read_model_artifact as artifact
from scripts.rehearse_collector_recommendations import create_fixture, SUITE


class FixedQuestionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve();self.path=self.base/'catalog.sqlite3'
        self.suite=json.loads(SUITE.read_text());create_fixture(self.path,self.suite)
        self.manifest=self.base/'manifest.json';self.manifest.write_text('{"synthetic_only":true}')
        with closing(core.connect(self.path,readonly=True)) as db:self.native=runtime.CatalogReadModel(db)
        with closing(core.connect(self.path,readonly=True)) as db:
            seal=artifact.write(db,self.manifest,self.base/'artifact')
        with closing(core.connect(self.path,readonly=True)) as db:
            self.loaded,_,_=artifact.load(db,self.base/'artifact',self.manifest,expected_seal_sha256=seal['seal_sha256'])
        self.models=(self.native,self.loaded)
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()

    def tearDown(self):
        for context in (runtime._catalog_scope,runtime._snapshot_scope,runtime._parser_plan_scope):
            self.assertIsNone(context.get())
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(),self.before)

    @staticmethod
    def typed(value):
        if type(value) is dict:return ('dict',tuple((k,FixedQuestionPlanTests.typed(v)) for k,v in sorted(value.items())))
        if type(value) in (list,tuple):return (type(value).__name__,tuple(map(FixedQuestionPlanTests.typed,value)))
        return (type(value).__name__,value)

    def test_every_plan_field_matches_public_native_parsers(self):
        questions=['Pikachu','ミュウ','皮卡丘','cards by Alpha','Alpha','Japanese cards from FIX',
            'English Pikachu ex','all languages Pikachu','Professor Oak','博士の研究 オーキド博士',
            'Japanese 25 ポケモンカード','Mewtwo and Mew','Pokemon cards from missing archive']
        for text in questions:
            text=discovery._norm(text)
            for languages in [('ja',),('en',),('ja','en'),('en','ja'),('ja','ja')]:
                with closing(core.connect(self.path,readonly=True)) as db:
                    without=discovery._without_release_names(db,text,list(languages))
                    expected=(discovery._artists(db,text),discovery._release_codes(db,text,list(languages)),
                        without,discovery._character_ids(db,text),discovery._character_ids(db,without),
                        discovery._qualifier_findings(db,text,list(languages)),discovery._unsupported_professors(db,text),
                        discovery.requested_name_suffix(db,text,list(languages)),
                        discovery.reviewed_release_interpretations(db,text,list(languages)))
                for model in self.models:
                    with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                        actual=runtime.snapshot_question_plan(db,text,languages)
                        self.assertIsNotNone(actual)
                        observed=(list(actual.artists),set(actual.codes),actual.without,list(actual.ids),
                            list(actual.without_ids),json.loads(actual.qualifiers_json),list(actual.professors),
                            actual.suffix,json.loads(actual.interpretations_json))
                        self.assertEqual(observed,expected,(text,languages))

    def test_diverse_complete_replays_and_types_equal_native(self):
        questions=['Recommend Japanese Pikachu cards','Recommend English Pikachu cards',
            'Recommend Pikachu cards in all languages','Recommend Japanese cards by Alpha',
            'Recommend Japanese Pikachu cards only by Alpha','Recommend Japanese cards from FIX',
            'Recommend Korean Pikachu cards','Recommend Japanese 皮卡丘 cards','Recommend Japanese ミュウ cards',
            'Recommend cards I do not already own','What should I collect next?','Compare Pikachu and Mew']
        for question in questions:
            payload=dict(turns=[dict(type='ask',question=question)],limit=5)
            with closing(core.connect(self.path,readonly=True)) as db:
                expected=journey.replay(db,payload,revision='a'*64)
            for model in self.models:
                with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                    actual=journey.replay(db,payload,revision='a'*64)
                self.assertEqual(self.typed(actual),self.typed(expected),question)

    def test_scope_keys_include_language_order_multiplicity_and_clear_finally(self):
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            for languages in [('ja','en'),('en','ja'),('ja','ja')]:
                plan=runtime.snapshot_question_plan(db,'pikachu synthetic-private-query-marker',languages)
                self.assertEqual(plan.ids,(25,))
            self.assertEqual(len(runtime._parser_plan_scope.get()['rows']),3)
            raise ValueError('synthetic cancellation')
        for model in self.models:
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db),self.assertRaisesRegex(ValueError,'synthetic cancellation'):
                probe(db)
            self.assertIsNone(runtime._parser_plan_scope.get())
            self.assertNotIn('synthetic-private-query-marker',repr(vars(model)))

    def test_combined_64_cap_including_generic_and_fixed_parsers(self):
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            for n in range(63):runtime.request_mentions(db,('synthetic',n),lambda:())
            first=runtime.snapshot_question_plan(db,'pikachu',('ja',))
            for n in range(4):
                self.assertEqual(runtime.snapshot_question_plan(db,f'pikachu {n}',('ja',)).ids,first.ids)
            self.assertEqual(runtime._parser_cache_size(runtime._catalog_scope.get()),64)
            self.assertEqual(len(runtime._parser_plan_scope.get()['rows']),1)
            discovery._artists(db,'cards by alpha')
            self.assertEqual(runtime._parser_cache_size(runtime._catalog_scope.get()),64)
        for model in self.models:
            with closing(core.connect(self.path,readonly=True)) as db,model.request(db):probe(db)

    def test_large_plan_is_returned_but_not_retained_over_byte_ceiling(self):
        original=discovery._question_plan_from_facts
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            def large(*args):
                return original(*args)._replace(qualifiers_json='x'*(runtime.MAX_PARSER_PLAN_CACHE_BYTES+1))
            with patch.object(discovery,'_question_plan_from_facts',side_effect=large) as builds:
                for unused in range(2):
                    self.assertGreater(len(runtime.snapshot_question_plan(db,'pikachu',('ja',)).qualifiers_json),runtime.MAX_PARSER_PLAN_CACHE_BYTES)
                self.assertEqual(builds.call_count,2)
            scope=runtime._parser_plan_scope.get()
            self.assertEqual((scope['rows'],scope['bytes']),({},0))
            runtime.snapshot_question_plan(db,'pikachu',('ja',))
            self.assertTrue(0<scope['bytes']<=runtime.MAX_PARSER_PLAN_CACHE_BYTES)
        with closing(core.connect(self.path,readonly=True)) as db,self.native.request(db):probe(db)

    def test_native_and_nonbuiltin_inputs_decline_without_plan_computation(self):
        class Text(str):pass
        with patch.object(discovery,'_question_plan_from_facts',side_effect=AssertionError('unexpected plan')):
            with closing(core.connect(self.path,readonly=True)) as db:
                self.assertIsNone(runtime.snapshot_question_plan(db,'pikachu',('ja',)))
            with closing(core.connect(self.path,readonly=True)) as db,self.native.request(db):
                for text,languages in [(Text('pikachu'),('ja',)),('pikachu',['ja']),('pikachu',(Text('ja'),))]:
                    self.assertIsNone(runtime.snapshot_question_plan(db,text,languages))

    def test_hit_miss_capped_and_direct_reject_transient_temp_before_rollback(self):
        for model in self.models:
            for mode in ('hit','miss','capped','direct'):
                escaped=[]
                def body(db):
                    if mode=='hit':runtime.snapshot_question_plan(db,'pikachu',('ja',))
                    if mode=='capped':
                        for n in range(64):runtime.request_mentions(db,('synthetic',n),lambda:())
                    db.execute('PRAGMA query_only=OFF');db.execute('BEGIN')
                    db.execute('CREATE TEMP VIEW synthetic_plan_shadow AS SELECT 1');db.execute('PRAGMA query_only=ON')
                    try:escaped.append(runtime.snapshot_question_plan(db,'pikachu',('ja',)))
                    finally:db.rollback();db.execute('PRAGMA query_only=ON')
                probe=body if mode=='direct' else runtime.catalog_request(runtime.parser_plan_request(body))
                with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):probe(db)
                self.assertEqual(escaped,[],mode)
                with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
                    self.assertEqual(runtime.snapshot_question_plan(db,'pikachu',('ja',)).ids,(25,))

    def test_mutation_inside_pure_plan_rejects_before_memo_publication(self):
        original=discovery._question_plan_from_facts
        for model in self.models:
            for throws in (False,True):
                @runtime.catalog_request
                @runtime.parser_plan_request
                def probe(db):
                    def mutate(*args):
                        db.execute('PRAGMA query_only=OFF')
                        if throws:raise ValueError('synthetic parse error after mutation')
                        return original(*args)
                    with patch.object(discovery,'_question_plan_from_facts',side_effect=mutate):
                        with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_question_plan(db,'pikachu',('ja',))
                    self.assertEqual(runtime._parser_plan_scope.get()['rows'],{})
                with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):probe(db)

    def test_cache_hit_rechecks_real_atomic_database_replacement(self):
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            runtime.snapshot_question_plan(db,'pikachu',('ja',))
            replacement=self.base/'replacement.sqlite3'
            replacement.write_bytes(self.path.read_bytes());os.replace(replacement,self.path)
            with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_question_plan(db,'pikachu',('ja',))
        with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),self.native.request(db):probe(db)
        with closing(core.connect(self.path,readonly=True)) as db:fresh=runtime.CatalogReadModel(db)
        with closing(core.connect(self.path,readonly=True)) as db,fresh.request(db):
            self.assertEqual(runtime.snapshot_question_plan(db,'pikachu',('ja',)).ids,(25,))

    def test_denied_clone_mutation_during_plan_poisoned_before_publication(self):
        for model in self.models:
            @runtime.catalog_request
            @runtime.parser_plan_request
            def probe(db):
                def mutate(*args):
                    db.execute('CREATE VIEW collector_snapshot.synthetic_forbidden AS SELECT 1')
                with patch.object(discovery,'_question_plan_from_facts',side_effect=mutate):
                    with self.assertRaises(runtime.CatalogSnapshotChanged):runtime.snapshot_question_plan(db,'pikachu',('ja',))
                self.assertEqual(runtime._parser_plan_scope.get()['rows'],{})
            with closing(core.connect(self.path,readonly=True)) as db,self.assertRaises(runtime.CatalogSnapshotChanged),model.request(db):probe(db)

    def test_pure_error_without_mutation_preserved_and_not_memoized(self):
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            with patch.object(discovery,'_question_plan_from_facts',side_effect=ValueError('native parse error')):
                with self.assertRaisesRegex(ValueError,'native parse error'):runtime.snapshot_question_plan(db,'pikachu',('ja',))
            self.assertEqual(runtime._parser_plan_scope.get()['rows'],{})
            self.assertEqual(runtime.snapshot_question_plan(db,'pikachu',('ja',)).ids,(25,))
        with closing(core.connect(self.path,readonly=True)) as db,self.native.request(db):probe(db)

    def test_no_rebase_or_reuse_across_snapshot_epochs(self):
        @runtime.catalog_request
        @runtime.parser_plan_request
        def probe(db):
            with self.native.request(db):runtime.snapshot_question_plan(db,'pikachu',('ja',))
            db.execute('DETACH DATABASE collector_snapshot')
            with self.loaded.request(db),self.assertRaises(runtime.CatalogSnapshotChanged):
                runtime.snapshot_question_plan(db,'pikachu',('ja',))
        with closing(core.connect(self.path,readonly=True)) as db:probe(db)

    def test_codec_strict_fields_and_types_do_not_coerce(self):
        original=self.native._parser_facts.to_state()
        malformed=[]
        for key,value in [('schema',True),('vocabulary',{}),('known_qualifiers',[None]),('qualifiers',[{'value':'x','active':1,'card_ids':[],'event_id':'e','language':'ja'}])]:
            state=copy.deepcopy(original);state[key]=value;malformed.append(state)
        state=copy.deepcopy(original);state['extra']=False;malformed.append(state)
        for value in (None,1,b'alias',False):
            state=copy.deepcopy(original);state['vocabulary']=[['ja','FIX','printed_code',value]];malformed.append(state)
        for state in malformed:
            with self.assertRaises(artifact.ArtifactInvalid):discovery._restore_parser_facts(state,self.native)
        restored=discovery._restore_parser_facts(original,self.native)
        self.assertEqual(restored.to_state(),original)
        self.assertIsNone(discovery._restore_parser_facts(None,self.native))

    def test_unsupported_sql_storage_type_disables_static_bundle(self):
        # Native SQL keeps its own ordinary type/error semantics. The bounded
        # projection declines BLOB rather than silently turning it into text.
        with closing(core.connect(self.path)) as db:
            db.execute("INSERT INTO catalog_vocabulary (language,set_code,alias_kind,alias,evidence_json) VALUES (?,?,?,?,?)",('ja','FIX','printed_code',b'FIX','{}'))
            db.commit()
        self.before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with closing(core.connect(self.path,readonly=True)) as db:
            model=runtime.CatalogReadModel(db)
            self.assertIsNone(model._parser_facts)
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
            self.assertIsNone(runtime.snapshot_question_plan(db,'pikachu',('ja',)))
        with closing(core.connect(self.path,readonly=True)) as db:
            with self.assertRaises(TypeError):discovery._release_codes(db,'pikachu',['ja'])
        with closing(core.connect(self.path,readonly=True)) as db,model.request(db):
            with self.assertRaises(TypeError):discovery._release_codes(db,'pikachu',['ja'])

    def test_native_scoring_batch_preserves_custom_collation_and_temp_rows(self):
        # SQL equality using a native user collation is not equivalent to the
        # Python exact-string scorer. The optimization only filters the fixed
        # protected clone, never a native or TEMP namespace.
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory=sqlite3.Row
            db.create_collation('NEVER_EQUAL',lambda left,right:1)
            db.execute('CREATE TEMP TABLE discovery_card_facet (card_id TEXT,facet_type TEXT COLLATE NEVER_EQUAL,value TEXT,provenance TEXT,rights_reference TEXT)')
            db.execute('INSERT INTO discovery_card_facet VALUES (?,?,?,?,?)',('id','dex_id','25','p','r'))
            rows=list(recommendation._facet_batches(db,['id']))[0]['id']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['facet_type'],'dex_id')
            row={'card_id':'id','language':'ja','set_code':'FIX','provenance':'p'}
            desired={'dex_id':{'25'},'illustrator':set()};liked={'dex_id':set(),'illustrator':set()}
            self.assertEqual(recommendation._score(row,rows,desired,liked,[])['explicit_match_axes'],['character'])

    def test_constraint_projection_declines_any_other_scope_or_all_languages(self):
        result={'languages':['ja'],'unfulfilled_constraints':[]}
        self.assertTrue(discovery._redundant_language_constraint_projection(result,{'language':'ja'}))
        for scope in ({},{'language':'en'},{'language':'ja','set_code':'FIX'}):
            self.assertFalse(discovery._redundant_language_constraint_projection(result,scope))
        result['unfulfilled_constraints']=['all_language_coverage']
        self.assertFalse(discovery._redundant_language_constraint_projection(result,{'language':'ja'}))


if __name__=='__main__':unittest.main()

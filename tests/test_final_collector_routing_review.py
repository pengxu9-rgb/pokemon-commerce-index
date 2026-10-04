"""Independent query semantics after the first full-catalog continuation failure."""
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest

from pokemon_index import collector_journey, collector_release_alias, core
import test_independent_recommendation_review as fixture


class FinalCollectorRoutingReview(unittest.TestCase):
    setUp = fixture.IndependentRecommendationReview.setUp
    tearDown = fixture.IndependentRecommendationReview.tearDown
    replay = fixture.IndependentRecommendationReview.replay

    def test_explicit_character_and_artist_stay_conjunctive_with_recommend_word(self):
        expected = {fixture.A, 'ja:AAA:001/100:holo'}
        for question in ['Japanese Pikachu cards illustrated by Yuka Morii',
                         'Recommend Japanese Pikachu cards illustrated by Yuka Morii',
                         'Recommend only Japanese Pikachu cards by Yuka Morii']:
            with self.subTest(question=question):
                result = self.replay([{'type': 'ask', 'question': question}])
                self.assertEqual({c['card_id'] for c in result['candidate_cards']}, expected)
                self.assertFalse(result['purchase_ready'])

    def test_explicit_soft_preference_axes_keep_union_semantics(self):
        result = self.replay([{'type':'ask', 'question':'What should I collect next?'},
            {'type':'preferences', 'preferences':{'collecting':{
                'preferred_dex_ids':[25], 'preferred_illustrators':['Yuka Morii']}}}])
        ids = {c['card_id'] for c in result['candidate_cards']}
        self.assertIn(fixture.B, ids)
        self.assertIn(fixture.MEW, ids)

    def test_unresolved_hard_artist_does_not_disappear_into_character_matches(self):
        turns=[{'type':'ask','question':'Recommend Japanese Pikachu cards by Unknown Artist'}]
        result=self.replay(turns)
        self.assertFalse(result['selection_allowed'])
        with self.assertRaises(ValueError):
            self.replay(turns+[{'type':'select','card_id':fixture.A}])

    def test_artist_clarification_accepts_later_exact_reply_or_profile_without_relaxing_species(self):
        for question in ['Recommend Japanese Pikachu cards by Unknown Artist',
                         'Recommend only Japanese Pikachu cards by Yuka Morii or Tomokazu Komiya']:
            for action in [{'type':'reply','text':'Yuka Morii'},
                           {'type':'preferences','preferences':{'collecting':{'preferred_illustrators':['Yuka Morii']}}}]:
                with self.subTest(question=question,action=action):
                    turns=[{'type':'ask','question':question},action]
                    result=self.replay(turns)
                    self.assertEqual({c['card_id'] for c in result['candidate_cards']},
                                     {fixture.A,'ja:AAA:001/100:holo'})
                    self.assertTrue(result['selection_allowed'])
                    selected=self.replay(turns+[{'type':'select','card_id':fixture.A}])
                    self.assertEqual(selected['target_intent']['card_id'],fixture.A)
                    self.assertFalse(selected['purchase_ready'])

    def test_prior_artist_preference_cannot_resolve_new_unknown_clause_but_later_same_answer_can(self):
        turns=[{'type':'ask','question':'What should I collect next?'},
               {'type':'preferences','preferences':{'collecting':{'preferred_illustrators':['Yuka Morii']}}},
               {'type':'ask','question':'Recommend Japanese Pikachu cards by Unknown Artist'}]
        self.assertFalse(self.replay(turns)['selection_allowed'])
        unrelated=turns+[{'type':'page','offset':0},{'type':'refine','scope':{'set_code':'AAA'}},
                         {'type':'inventory','owned_items':[]}]
        self.assertFalse(self.replay(unrelated)['selection_allowed'])
        resolved=self.replay(unrelated+[{'type':'reply','text':'Yuka Morii'}])
        self.assertEqual({c['card_id'] for c in resolved['candidate_cards']},{fixture.A,'ja:AAA:001/100:holo'})
        self.assertTrue(resolved['selection_allowed'])

    def test_artist_resolution_clear_and_reconfirmation_do_not_keep_old_authority(self):
        prefix=[{'type':'ask','question':'Recommend Japanese Pikachu cards by Unknown Artist'},
                {'type':'reply','text':'Yuka Morii'}]
        selected=prefix+[{'type':'select','card_id':fixture.A}]
        confirmed=self.replay(selected+[{'type':'preferences','preferences':{'collecting':{
            'preferred_illustrators':['Yuka Morii']}}}])
        self.assertIsNone(confirmed['target_intent'])
        for value in [None,[]]:
            cleared=self.replay(selected+[{'type':'preferences','preferences':{'collecting':{
                'preferred_illustrators':value}}}])
            self.assertIsNone(cleared['target_intent'])
            self.assertFalse(cleared['selection_allowed'])
        compared=prefix+[{'type':'compare','left_card_id':fixture.A,'right_card_id':'ja:AAA:001/100:holo'},
                         {'type':'reply','text':'Yuka Morii'}]
        self.assertIsNone(self.replay(compared)['target_intent'])
        with self.assertRaises(ValueError):
            self.replay(compared+[{'type':'choose_comparison','side':'right','card_id':'ja:AAA:001/100:holo'}])

    @unittest.skipUnless(shutil.which('node'), 'actual Node caller required')
    def test_actual_http_node_artist_recovery_and_reconfirmation_keep_authority_separate(self):
        from pokemon_index.cli import create_server
        script=r'''
const {createCollectorClient}=require('./integrations/pivota/collectorClient.cjs');
const client=createCollectorClient({baseUrl:process.argv[1],allowLoopback:true,retryDelayMs:0});
(async()=>{
 let call=await client.start({question:'Recommend Japanese Pikachu cards by Unknown Artist'});
 if(call.result.selection_allowed)throw Error('unknown artist authorized');
 call=await client.advance({session:call.session,action:{type:'reply',text:'Yuka Morii'}});
 if(!call.result.selection_allowed || call.result.candidate_cards.some(c=>c.name!=='Pikachu'))throw Error('artist recovery lost species');
 call=await client.advance({session:call.session,action:{type:'select',card_id:'ja:AAA:001/100:normal'}});
 if(!call.target_intent)throw Error('explicit choice failed');
 call=await client.advance({session:call.session,action:{type:'preferences',preferences:{collecting:{preferred_illustrators:['Yuka Morii']}}}});
 if(call.target_intent)throw Error('same-value confirmation preserved target');
 call=await client.advance({session:call.session,action:{type:'compare',left_card_id:'ja:AAA:001/100:normal',right_card_id:'ja:AAA:001/100:holo'}});
 call=await client.advance({session:call.session,action:{type:'reply',text:'Yuka Morii'}});
 if(call.target_intent || call.result.purchase_ready || call.result.public_display_allowed)throw Error('authority leaked');
 const saved=JSON.stringify(call.session);
 try {await client.advance({session:call.session,action:{type:'choose_comparison',side:'right',card_id:'ja:AAA:001/100:holo'}});throw Error('stale comparison accepted');}
 catch(e){if(e.code!=='catalog_rejected_action')throw e;}
 if(JSON.stringify(call.session)!==saved)throw Error('rejected choice changed session');
 process.stdout.write(JSON.stringify({requests:7,recovered:true,authority:false}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
'''
        self.db.commit()
        with create_server(str(Path(self.temp.name)/'catalog.sqlite3'),'127.0.0.1',0,True) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                result=json.loads(subprocess.check_output(['node','-e',script,
                    'http://127.0.0.1:'+str(server.server_port)],text=True,timeout=30))
                self.assertEqual(result,{'requests':7,'recovered':True,'authority':False})
            finally:
                server.shutdown();thread.join(timeout=5)

    def test_multiple_artists_never_drop_the_artist_constraint_entirely(self):
        cid='ja:AAA:008/100:normal'
        core.import_cards(self.db,[dict(language='ja',set_code='AAA',collector_number='008/100',variant='normal',
            name='Pikachu',match_eligible=True,provenance='review:fixture',rights_reference='review:fixture')])
        core.import_card_facets(self.db,[dict(card_id=cid,facet_type=kind,value=value,
            provenance='review:fixture',rights_reference='review:fixture')
            for kind,value in [('dex_id',25),('illustrator','Third Artist')]])
        turns=[{'type':'ask','question':'Recommend only Japanese Pikachu cards by Yuka Morii or Tomokazu Komiya'}]
        result=self.replay(turns)
        self.assertFalse(cid in [c['card_id'] for c in result['candidate_cards']] and result['selection_allowed'])
        with self.assertRaises(ValueError):
            self.replay(turns+[{'type':'select','card_id':cid}])

    def test_ex_suffix_empty_coordinate_is_no_match_and_cannot_select(self):
        turns = [{'type':'ask', 'question':'Japanese Mew ex AAA 003/100'}]
        result = self.replay(turns)
        self.assertEqual(result['candidate_cards'], [])
        self.assertEqual(result['discovery']['status'], 'no_match')
        self.assertFalse(result['selection_allowed'])
        with self.assertRaises(ValueError):
            self.replay(turns+[{'type':'select', 'card_id':fixture.MEW}])

    def test_species_name_ending_in_ex_is_not_itself_an_ex_qualifier(self):
        for number,name in [('006','Toxapex'),('007','Toxapex ex')]:
            core.import_cards(self.db,[dict(language='en',set_code='AAA',collector_number=number+'/100',
                variant='normal',name=name,match_eligible=True,provenance='review:fixture',rights_reference='review:fixture')])
            core.import_card_facets(self.db,[dict(card_id='en:AAA:'+number+'/100:normal',facet_type='dex_id',value=748,
                provenance='review:fixture',rights_reference='review:fixture')])
        for question in ['Show English Toxapex ex cards','Recommend English Toxapex ex cards']:
            with self.subTest(question=question):
                result=self.replay([{'type':'ask','question':question}])
                self.assertEqual([c['card_id'] for c in result['candidate_cards']],['en:AAA:007/100:normal'])

    def add_reviewed_release(self):
        pin = json.loads(collector_release_alias.BINDINGS_PATH.read_text())['records'][0]
        row = pin['current_release']
        self.db.execute('INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
            tuple(row[k] for k in ['language','set_code','name','release_date','official_card_count',
                                   'provenance','rights_reference','display_allowed']))
        self.db.execute('INSERT INTO catalog_release_evidence VALUES (?,?,?)',
                        ('ja','SV4A',json.dumps(pin['release_evidence'])))
        for number, name, dex in [('327/190','Mew ex',151), ('328/190','Gardevoir ex',282)]:
            core.import_cards(self.db,[dict(language='ja',set_code='SV4A',collector_number=number,
                variant='holo',name=name,match_eligible=True,provenance='review:fixture',rights_reference='review:fixture')])
            cid=core.card_id('ja','SV4A',number,'holo')
            core.import_card_facets(self.db,[dict(card_id=cid,facet_type='dex_id',value=dex,
                provenance='review:fixture',rights_reference='review:fixture')])
        self.db.commit()

    def test_reviewed_english_release_alias_is_current_and_language_bound(self):
        self.add_reviewed_release()
        question='Show Japanese cards from Shiny Treasure ex 327/190'
        result=self.replay([{'type':'ask','question':question}])
        self.assertEqual([c['card_id'] for c in result['candidate_cards']], ['ja:SV4A:327/190:holo'])
        interpretations=result['discovery']['release_name_interpretations']
        self.assertTrue(interpretations)
        self.assertTrue(all(x['source_published_alias'] is False for x in interpretations))
        english=self.replay([{'type':'ask','question':question.replace('Japanese','English')}])
        self.assertFalse(any(c['language']=='ja' for c in english['candidate_cards']))
        self.db.execute("UPDATE catalog_set_localized SET rights_reference='stale' WHERE set_code='SV4A'")
        stale=self.replay([{'type':'ask','question':question}])
        self.assertEqual(stale['candidate_cards'],[])
        self.assertFalse(stale['selection_allowed'])

    def test_ex_in_reviewed_release_title_does_not_filter_ordinary_species_cards(self):
        self.add_reviewed_release()
        cid='ja:SV4A:001/190:normal'
        core.import_cards(self.db,[dict(language='ja',set_code='SV4A',collector_number='001/190',variant='normal',
            name='Pikachu',match_eligible=True,provenance='review:fixture',rights_reference='review:fixture')])
        core.import_card_facets(self.db,[dict(card_id=cid,facet_type='dex_id',value=25,
            provenance='review:fixture',rights_reference='review:fixture')])
        result=self.replay([{'type':'ask','question':'Show Japanese Pikachu cards from Shiny Treasure ex'}])
        self.assertEqual([c['card_id'] for c in result['candidate_cards']],[cid])
        self.assertNotIn('requested_source_name_suffix',result['discovery'])

    def test_hard_artist_intersection_accepts_current_derived_species_proof(self):
        from test_final_adversarial_affiliation import FinalSourceAffiliationTests
        source=FinalSourceAffiliationTests()
        source.setUp()
        try:
            row=source.db.execute('SELECT provenance,rights_reference FROM card WHERE card_id=?',(source.mew,)).fetchone()
            core.import_card_facets(source.db,[dict(card_id=source.mew,facet_type='illustrator',value='Fixture Artist',
                provenance=row['provenance'],rights_reference=row['rights_reference'])])
            result=collector_journey.replay(source.db,{'turns':[{'type':'ask',
                'question':'Recommend Japanese ミュウex cards by Fixture Artist'}],'limit':50})
            self.assertEqual([c['card_id'] for c in result['candidate_cards']],[source.mew])
            self.assertTrue(any(reason['basis']=='source_name_character_affiliation'
                for item in result['recommendation']['items'] for reason in item['reasons']))
            self.assertFalse(result['purchase_ready'])
        finally:
            source.tearDown()

    def test_shared_comparison_scope_needs_separate_selection_and_dies_on_change(self):
        self.add_reviewed_release()
        ask={'type':'ask','question':'Compare Japanese SV4A 327/190 and 328/190'}
        right='ja:SV4A:328/190:holo'
        compared=self.replay([ask])
        self.assertEqual(compared['discovery']['task'],'two_card_comparison')
        self.assertIsNone(compared['target_intent'])
        choose={'type':'choose_comparison','side':'right','card_id':right}
        focused=self.replay([ask,choose])
        self.assertEqual([c['card_id'] for c in focused['candidate_cards']],[right])
        self.assertIsNone(focused['target_intent'])
        selected=self.replay([ask,choose,{'type':'select','card_id':right}])
        self.assertEqual(selected['target_intent']['card_id'],right)
        self.assertFalse(selected['purchase_ready'])
        for action in [{'type':'inventory','owned_items':[]},
                       {'type':'preferences','preferences':{'collecting':{'subjective_notes':['cozy']}}},
                       {'type':'refine','scope':{'set_code':'SV4A'}}]:
            with self.subTest(action=action),self.assertRaises(ValueError):
                self.replay([ask,action,choose])

    def test_shared_comparison_does_not_ignore_conflicting_or_negative_scope(self):
        from pokemon_index import card_comparison
        self.add_reviewed_release()
        self.db.execute('INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
                        ('ja','SV1S','スカーレットex',None,78,'fixture','fixture',0))
        for tail in [' from スカーレットex',' from SV1S',' in English',' but not from SV4A']:
            with self.subTest(tail=tail):
                self.assertIsNone(card_comparison.from_question(self.db,
                    'Compare Japanese SV4A 327/190 and 328/190'+tail))


if __name__ == '__main__':
    unittest.main()

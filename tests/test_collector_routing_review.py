"""Regression cases exposed by ICU-04/09/13/18/28; no longer held-out questions."""
import json
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from pokemon_index import core, collector_discovery, collector_journey, collector_release_alias, card_comparison
from pokemon_index.cli import create_server
import test_final_adversarial_affiliation as source_fixture


class CollectorRoutingReview(unittest.TestCase):
    add_anchor=source_fixture.FinalSourceAffiliationTests.add_anchor
    tearDown=source_fixture.FinalSourceAffiliationTests.tearDown

    def setUp(self):
        source_fixture.FinalSourceAffiliationTests.setUp(self)
        original=next(r for r in map(json.loads,Path('catalog/ja-all-sets.jsonl').read_text().splitlines()) if r['set_code'].upper()=='SV4A')
        core.import_sets(self.db,[original])
        supported={r['card_id']:r for r in map(json.loads,Path('catalog/supported-discovery-v1/supported-cards.jsonl').read_text().splitlines())}
        pikachu=supported['ja:SV4A:236/190:holo']['identity']
        self.pikachu=pikachu['card_id']
        core.import_cards(self.db,[dict(pikachu,rights_reference=original['rights_reference'],match_eligible=True)])
        core.import_card_facets(self.db,[dict(card_id=self.pikachu,facet_type='dex_id',value=25,
            provenance=pikachu['provenance'],rights_reference=original['rights_reference'])])
        self.artist_pikachu=self.add_card('010','ピカチュウ',25,'Yuka Morii')
        self.artist_mew=self.add_card('011','ミュウ',151,'Yuka Morii')
        self.add_card('012','ミュウVMAX',151,'Yuka Morii')
        self.add_card('013','ミュウex',151,'Yuka Morii')
        target=self.db.execute('SELECT provenance,rights_reference FROM card WHERE card_id=?',(self.other_mew,)).fetchone()
        core.import_card_facets(self.db,[dict(card_id=self.other_mew,facet_type='illustrator',value='USGMEN',
            provenance=target['provenance'],rights_reference=target['rights_reference'])])
        for number,name,dex in [('001','Mew',151),('002','Pikachu',25)]:
            core.import_cards(self.db,[dict(language='en',set_code='ALIAS',collector_number=number+'/100',
                variant='normal',name=name,provenance='synthetic:english:'+number,rights_reference='synthetic:no-display',match_eligible=True)])
            core.import_card_facets(self.db,[dict(card_id=core.card_id('en','ALIAS',number+'/100','normal'),
                facet_type='dex_id',value=dex,provenance='synthetic:english:'+number,rights_reference='synthetic:no-display')])
        self.db.commit()

    def add_card(self,number,name,dex,artist):
        cid=core.card_id('ja','TEST',number+'/100','normal')
        core.import_cards(self.db,[dict(language='ja',set_code='TEST',collector_number=number+'/100',variant='normal',
            name=name,provenance='synthetic:routing:'+number,rights_reference='synthetic:no-display',match_eligible=True)])
        for kind,value in [('dex_id',str(dex)),('illustrator',artist)]:
            core.import_card_facets(self.db,[dict(card_id=cid,facet_type=kind,value=value,
                provenance='synthetic:routing:'+number,rights_reference='synthetic:no-display')])
        return cid

    def replay(self,turns):
        return collector_journey.replay(self.db,dict(turns=turns,limit=50),revision='a'*64)

    def test_icu13_reviewed_release_rendering_is_scoped_and_explicit(self):
        ask=dict(type='ask',question='Show me Japanese Pikachu 236/190 from Shiny Treasure ex.')
        out=self.replay([ask])
        self.assertEqual([c['card_id'] for c in out['candidate_cards']],[self.pikachu])
        self.assertIsNone(out['target_intent'])
        interpretation=out['discovery']['release_name_interpretations'][0]
        self.assertFalse(interpretation['source_published_alias'])
        self.assertEqual(interpretation['source_title'],'シャイニートレジャーex')
        self.assertEqual(self.replay([ask,dict(type='select',card_id=self.pikachu)])['target_intent']['card_id'],self.pikachu)
        self.assertEqual(collector_release_alias.aliases(self.db,['en']),[])

    def test_release_alias_fails_closed_on_currentness_and_rights_drift(self):
        for column,value in [('name','レイジングサーフ'),('rights_reference','changed'),('provenance','changed')]:
            old=self.db.execute('SELECT '+column+" FROM catalog_set_localized WHERE language='ja' AND set_code='SV4A'").fetchone()[0]
            self.db.execute('UPDATE catalog_set_localized SET '+column+"=? WHERE language='ja' AND set_code='SV4A'",(value,))
            self.assertEqual(collector_release_alias.aliases(self.db,['ja']),[])
            self.db.execute('UPDATE catalog_set_localized SET '+column+"=? WHERE language='ja' AND set_code='SV4A'",(old,))
        row=self.db.execute("SELECT evidence_json FROM catalog_release_evidence WHERE language='ja' AND set_code='SV4A'").fetchone()[0]
        changed=json.loads(row);changed['official_page_sha256']='0'*64
        self.db.execute("UPDATE catalog_release_evidence SET evidence_json=? WHERE language='ja' AND set_code='SV4A'",(json.dumps(changed),))
        self.assertEqual(collector_release_alias.aliases(self.db,['ja']),[])

    def test_icu28_shared_comparison_scope_never_selects_implicitly(self):
        ask=dict(type='ask',question='Compare Japanese SV4A Mew ex 327/190 and 347/190.')
        out=self.replay([ask]);self.assertEqual(out['discovery']['task'],'two_card_comparison')
        self.assertEqual(out['candidate_cards'],[]);self.assertIsNone(out['target_intent'])
        with self.assertRaises(ValueError):self.replay([ask,dict(type='select',card_id=self.other_mew)])
        choose=dict(type='choose_comparison',side='right',card_id=self.other_mew)
        focused=self.replay([ask,choose]);self.assertEqual([c['card_id'] for c in focused['candidate_cards']],[self.other_mew])
        self.assertIsNone(focused['target_intent'])
        selected=self.replay([ask,choose,dict(type='select',card_id=self.other_mew)])
        self.assertEqual(selected['target_intent']['card_id'],self.other_mew)
        self.assertFalse(selected['target_intent']['transaction_ready'])
        with self.assertRaises(ValueError):
            self.replay([ask,dict(type='preferences',preferences={'collecting':{'preferred_dex_ids':[25]}}),choose])

    def test_shared_comparison_does_not_guess_conflicting_or_negative_scope(self):
        for q in ['Compare Japanese SV4A 327/190 and SV3 347/190.',
                  'Compare Japanese SV4A 327/190 and 347/190, not from SV4A.',
                  'Compare Japanese 327/190 and 347/190.',
                  'Compare Japanese SV4A 327/190 or 347/190.',
                  'Compare Japanese SV4A 327/190 and 347/190 and 348/190.']:
            self.assertIsNone(card_comparison.from_question(self.db,q),q)
        result=card_comparison.from_question(self.db,'Compare Japanese SV4A 327/190 and English 347/190.')
        self.assertIn(result['right']['status'],{'release_confirmation_needed','not_found'})
        self.assertNotIn('set_code',result['right']['requested'])

    def test_icu04_species_ex_is_title_qualifier_not_generic_species(self):
        out=self.replay([dict(type='ask',question='Recommend Japanese Mew ex cards. I want to explore different illustrations.')])
        self.assertGreaterEqual(len(out['candidate_cards']),2)
        self.assertTrue(all(c['name'].casefold().endswith('ex') for c in out['candidate_cards']))
        self.assertEqual(out['discovery']['name_suffix_scope'],'source_catalog_title_only_not_mechanic_or_copy_verification')
        self.assertTrue(out['recommendation']['unapplied_preferences'])

    def test_icu09_only_species_artist_is_intersection_and_remains_hard(self):
        turns=[dict(type='ask',question='Only show Japanese Pikachu cards illustrated by Yuka Morii.')]
        out=self.replay(turns);self.assertEqual([c['card_id'] for c in out['candidate_cards']],[self.artist_pikachu])
        out=self.replay(turns+[dict(type='preferences',preferences={'collecting':{'preferred_dex_ids':[151]}})])
        self.assertTrue(all(c['card_id']==self.artist_pikachu for c in out['candidate_cards']))

    def test_artist_collection_check_retains_owned_inventory_prompt(self):
        result=collector_discovery.execute(self.db,'Yuka Morii cards: check off my collection')
        self.assertEqual(result['task'],'artist_cards')
        self.assertTrue(result['cards'])
        self.assertIn('owned_inventory',result['unfulfilled_constraints'])
        self.assertIn('owned-card list',result['next_question'])
        self.assertFalse(result['complete_answer_established'])

    def test_artist_species_collection_check_retains_owned_inventory_prompt(self):
        result=collector_discovery.execute(self.db,'Japanese Pikachu cards by Yuka Morii: check off my collection')
        self.assertEqual(result['task'],'artist_cards')
        self.assertEqual([card['card_id'] for card in result['cards']],[self.artist_pikachu])
        self.assertIn('owned_inventory',result['unfulfilled_constraints'])
        self.assertIn('owned-card list',result['next_question'])
        self.assertFalse(result['complete_answer_established'])

    def test_hard_artist_species_intersection_uses_current_derived_affiliation(self):
        for question in ['Recommend Japanese Mew ex cards illustrated by USGMEN',
                         'Only show Japanese Mew ex cards illustrated by USGMEN']:
            result=self.replay([dict(type='ask',question=question)])
            self.assertEqual([c['card_id'] for c in result['candidate_cards']],[self.other_mew])
        self.db.execute("UPDATE card_reference SET provenance='changed' WHERE set_code='SV4A' AND collector_number='347/190'")
        result=self.replay([dict(type='ask',question='Recommend Japanese Mew ex cards illustrated by USGMEN')])
        self.assertEqual(result['candidate_cards'],[])

    def test_icu18_aesthetic_goal_accepts_supported_artist_reply(self):
        turns=[dict(type='ask',question='I want Japanese cards with peaceful, cozy illustrations. What should I collect?')]
        first=self.replay(turns);self.assertEqual(first['candidate_cards'],[])
        self.assertIn('unverified',first['next_step']['prompt'])
        out=self.replay(turns+[dict(type='reply',text='Yuka Morii')])
        self.assertGreaterEqual(len(out['candidate_cards']),3)
        self.assertEqual(set(out['preferences']['collecting']['subjective_notes']),{'peaceful','cozy'})
        self.assertTrue(all(any(r['field']=='illustrator' and r['value']=='Yuka Morii' for r in item['reasons']) for item in out['recommendation']['items']))

    def test_artist_clarification_answer_preserves_scope_and_invalidates_old_authority(self):
        another=self.add_card('014','ピカチュウ',25,'Yuka Morii')
        ask=dict(type='ask',question='Recommend Japanese Pikachu cards by Unknown Artist')
        answer=dict(type='preferences',preferences={'collecting':{'preferred_illustrators':['Yuka Morii']}})
        turns=[ask,dict(type='refine',scope={'set_code':'TEST','variant':'normal'}),answer]
        resolved=self.replay(turns)
        self.assertEqual({c['card_id'] for c in resolved['candidate_cards']},{self.artist_pikachu,another})
        self.assertEqual(resolved['discovery']['illustrator_scope_basis'],'later_explicit_user_choice')
        selected=self.replay(turns+[dict(type='select',card_id=self.artist_pikachu),answer])
        self.assertIsNone(selected['target_intent'])
        compare=dict(type='compare',left_card_id=self.artist_pikachu,right_card_id=another)
        with self.assertRaises(ValueError):
            self.replay(turns+[compare,answer,dict(type='choose_comparison',side='right',card_id=another)])
        held=self.replay(turns+[dict(type='preferences',preferences={'collecting':{'preferred_illustrators':None}})])
        self.assertFalse(held['selection_allowed'])
        self.assertEqual(held['candidate_cards'],[])
        excluded=self.replay(turns+[dict(type='preferences',preferences={'collecting':{
            'preferred_dex_ids':[],'excluded_dex_ids':[25]}}),dict(type='reply',text='Yuka Morii')])
        self.assertEqual(excluded['candidate_cards'],[])

    def test_actual_http_node_recovers_hard_artist_clarification(self):
        script=r'''
const {createCollectorClient}=require('./integrations/pivota/collectorClient.cjs');
const client=createCollectorClient({baseUrl:process.argv[1],allowLoopback:true,retryDelayMs:0});
(async()=>{
 for(const action of [{type:'reply',text:'Yuka Morii'},
                      {type:'preferences',preferences:{collecting:{preferred_illustrators:['Yuka Morii']}}}]) {
  let call=await client.start({question:'Recommend Japanese Pikachu cards by Unknown Artist'});
  if(call.result.selection_allowed || call.result.candidate_cards.length) throw Error('missing hard hold');
  call=await client.advance({session:call.session,action});
  if(!call.result.selection_allowed || call.result.candidate_cards.length!==1 ||
     call.result.candidate_cards[0].card_id!=='ja:TEST:010/100:normal') throw Error('artist answer or character scope');
  if(call.target_intent) throw Error('answer selected implicitly');
  call=await client.advance({session:call.session,action:{type:'select',card_id:'ja:TEST:010/100:normal'}});
  if(call.target_intent.card_id!=='ja:TEST:010/100:normal' || call.target_intent.transaction_ready) throw Error('separate select');
  call=await client.advance({session:call.session,action:{type:'ask',question:'Recommend Japanese Pikachu cards by Unknown Artist'}});
  if(call.result.selection_allowed || call.target_intent) throw Error('stale answer reused');
  call=await client.advance({session:call.session,action});
  if(!call.result.selection_allowed || call.result.candidate_cards.length!==1) throw Error('same-value confirmation');
 }
 console.log(JSON.stringify({recovery_paths:2,commerce:false}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'catalog.sqlite3';self.db.commit()
            with sqlite3.connect(path) as saved:self.db.backup(saved)
            with create_server(str(path),'127.0.0.1',0,True) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    result=json.loads(subprocess.check_output(['node','-e',script,
                        f'http://127.0.0.1:{server.server_address[1]}'],text=True,timeout=30))
                finally:server.shutdown();thread.join(timeout=5)
        self.assertEqual(result,{'recovery_paths':2,'commerce':False})

    def test_actual_http_node_accepts_five_routing_paths_with_separate_selection(self):
        script=r'''
const {createCollectorClient}=require('./integrations/pivota/collectorClient.cjs');
const client=createCollectorClient({baseUrl:process.argv[1],allowLoopback:true,retryDelayMs:0});
(async()=>{
 let call=await client.start({question:'Show me Japanese Pikachu 236/190 from Shiny Treasure ex.'});
 if(call.target_intent || call.result.candidate_cards[0]?.card_id!=='ja:SV4A:236/190:holo') throw Error('exact release path');
 if(call.result.discovery.release_name_interpretations[0].source_published_alias!==false) throw Error('translation evidence');
 call=await client.advance({session:call.session,action:{type:'select',card_id:'ja:SV4A:236/190:holo'}});
 if(call.target_intent.card_id!=='ja:SV4A:236/190:holo' || call.target_intent.transaction_ready) throw Error('catalog selection');
 call=await client.start({question:'Compare Japanese SV4A Mew ex 327/190 and 347/190.'});
 if(call.result.discovery.task!=='two_card_comparison' || call.target_intent || call.result.candidate_cards.length) throw Error('comparison');
 call=await client.advance({session:call.session,action:{type:'choose_comparison',side:'right',card_id:'ja:SV4A:347/190:holo'}});
 if(call.target_intent || call.result.candidate_cards.length!==1) throw Error('focus');
 call=await client.advance({session:call.session,action:{type:'select',card_id:'ja:SV4A:347/190:holo'}});
 if(call.target_intent.card_id!=='ja:SV4A:347/190:holo' || call.target_intent.transaction_ready) throw Error('independent select');
 call=await client.start({question:'Recommend Japanese Mew ex cards. I want to explore different illustrations.',limit:50});
 if(call.result.candidate_cards.length<2 || call.result.candidate_cards.some(c=>!c.name.toLowerCase().endsWith('ex'))) throw Error('title suffix');
 call=await client.start({question:'Only show Japanese Pikachu cards illustrated by Yuka Morii.'});
 if(call.result.candidate_cards.length!==1 || call.result.candidate_cards[0].card_id!=='ja:TEST:010/100:normal') throw Error('artist intersection');
 call=await client.start({question:'I want Japanese cards with peaceful, cozy illustrations. What should I collect?'});
 call=await client.advance({session:call.session,action:{type:'reply',text:'Yuka Morii'}});
 if(call.result.candidate_cards.length<3 || !call.result.recommendation.unapplied_preferences.length) throw Error('artist continuation');
 console.log(JSON.stringify({paths:5,commerce:false}));
})().catch(error=>{console.error(error);process.exit(1)});
'''
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'catalog.sqlite3';self.db.commit()
            with sqlite3.connect(path) as saved:self.db.backup(saved)
            with create_server(str(path),'127.0.0.1',0,True) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    result=json.loads(subprocess.check_output(['node','-e',script,
                        f'http://127.0.0.1:{server.server_address[1]}'],text=True,timeout=30))
                finally:server.shutdown();thread.join(timeout=5)
        self.assertEqual(result,{'paths':5,'commerce':False})


if __name__=='__main__':unittest.main()

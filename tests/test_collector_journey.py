import hashlib,json,tempfile,threading,unittest
from pathlib import Path
from contextlib import closing
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from pokemon_index import core,collector_journey,collector_evidence,supported_catalog,discovery_graph
from pokemon_index.cli import create_server


class JourneyFixture:
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'catalog.sqlite3'
        with closing(core.connect(self.path)) as db:
            core.init_db(db)
            cards=[('ja','001/100','normal','Pikachu',25),('ja','001/100','holo','Pikachu',25),
                   ('en','001/100','normal','Pikachu',25),('ja','002/100','normal','Pikachu',25),
                   ('ja','003/100','normal','Mew',151),('ja','004/100','normal','Gengar',94)]
            for lang,n,v,name,dex in cards:
                core.import_cards(db,[dict(language=lang,set_code='FIX',collector_number=n,variant=v,
                    name=name,provenance='fixture',rights_reference='fixture',match_eligible=True)])
                db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(core.card_id(lang,'FIX',n,v),'dex_id',str(dex),'fixture','fixture'))
            self.cid='ja:FIX:001/100:normal'
            for dex,kind,status in [(151,'ai_visual','proposed'),(94,'official_description','source_supported')]:
                e=dict(kind=kind,source_url='https://www.pokemon-card.com/card-search/details.php/card/1',
                    source_page_sha256='a'*64,official_card_url='https://www.pokemon-card.com/card-search/details.php/card/1',
                    official_card_page_sha256='a'*64,image_url='https://www.pokemon-card.com/assets/images/card_images/large/fix/1.jpg',
                    image_sha256='b'*64,locator='synthetic scene',finding='synthetic depiction',
                    review=dict(identity_match='match',model='fixture',prompt_version='fixture',prompt_sha256='c'*64,response_sha256='d'*64))
                collector_evidence.import_evidence(db,[dict(schema='pokemon.collector-evidence.v1',event_id=str(dex),
                    subject_kind='card',subject_id=self.cid,claim='depicted_pokemon',value=dex,role='cameo',status=status,
                    identity_sha256=supported_catalog.digest(collector_evidence.identity(db,'card',self.cid)),evidence=e,
                    actor='fixture',recorded_at='2026-10-01T00:00:00+00:00',expected_head=None)])
            db.commit()
        self.db=core.connect(self.path,readonly=True)
    def tearDown(self):self.db.close();self.tmp.cleanup()
    def run_turns(self,turns,**kw):return collector_journey.replay(self.db,dict(turns=turns,**kw))
    def sequence(self):
        return [dict(type='ask',question='Pikachu cards'),dict(type='reply',text='Japanese'),
                dict(type='reply',text='FIX'),dict(type='reply',text='1/100'),dict(type='reply',text='non-holo')]


class CollectorJourneyTests(JourneyFixture,unittest.TestCase):
    def test_short_replies_preserve_goal_and_select_catalog_only(self):
        turns=self.sequence()+[dict(type='reply',text='Yes'),dict(type='preferences',preferences=dict(grade_company='PSA',grade_value='10',budget_minor=100000,currency='JPY',destination='HK'))]
        r=self.run_turns(turns)
        self.assertEqual(r['status'],'catalog_target_selected');self.assertEqual(r['selected_catalog_target']['card_id'],self.cid)
        self.assertEqual(r['goal_question'],'Pikachu cards');self.assertEqual(r['scope_filters']['collector_number'],'001/100')
        self.assertEqual(r['target_intent']['preferences']['grade_value'],'10')
        self.assertFalse(r['target_intent']['transaction_ready']);self.assertIsNone(r['target_intent']['priceable_unit_id'])
        for field in ['physical_copy_verified','ready_for_offer_tracking','purchase_ready','conversation_persisted','inventory_persisted','public_display_allowed','preferences_applied_to_market']:
            self.assertFalse(r[field])
    def test_changed_scope_clears_target_and_explicit_language_overrides(self):
        turns=self.sequence()+[dict(type='select',card_id=self.cid),dict(type='reply',text='English')]
        r=self.run_turns(turns);self.assertIsNone(r['selected_catalog_target']);self.assertEqual(r['target_reset_reason'],'collection_scope_changed')
        self.assertEqual([c['language'] for c in r['candidate_cards']],['en'])
        r=self.run_turns([dict(type='ask',question='English Pikachu cards'),dict(type='reply',text='Japanese')])
        self.assertTrue(r['candidate_cards']);self.assertEqual({c['language'] for c in r['candidate_cards']},{'ja'})
    def test_uncertain_inventory_blocks_selection_then_explicit_resolution_preserves_quantity(self):
        turns=[dict(type='ask',question='Japanese Pikachu cards'),dict(type='inventory',owned_items=[
            dict(item_id='uncertain',language='ja',set_code='FIX',collector_number='1/100',quantity=2)])]
        r=self.run_turns(turns);self.assertEqual(r['status'],'inventory_review_needed');self.assertFalse(r['selection_allowed'])
        with self.assertRaisesRegex(ValueError,'blockers'):self.run_turns(turns+[dict(type='select',card_id='ja:FIX:002/100:normal')])
        with self.assertRaisesRegex(ValueError,'conflicts'):self.run_turns(turns+[dict(type='resolve_owned',item_id='uncertain',card_id='ja:FIX:003/100:normal')])
        resolved=turns+[dict(type='resolve_owned',item_id='uncertain',card_id='ja:FIX:001/100:holo')]
        r=self.run_turns(resolved);self.assertEqual(r['inventory']['owned_in_scope'][0]['quantity'],2)
        self.assertEqual(r['inventory']['unresolved_items'],[])
        r=self.run_turns(resolved+[dict(type='select',card_id=self.cid)])
        self.assertEqual(r['status'],'catalog_target_selected');self.assertFalse(r['ownership_assertions_verified'])
    def test_new_goal_preserves_inventory_and_preferences_but_resets_selection(self):
        turns=self.sequence()+[dict(type='select',card_id=self.cid),dict(type='inventory',owned_items=[dict(item_id='mew',card_id='ja:FIX:003/100:normal')]),
            dict(type='preferences',preferences=dict(destination='HK')),dict(type='ask',question='Japanese Mew cards')]
        r=self.run_turns(turns);self.assertEqual(r['status'],'submitted_scope_covered');self.assertEqual(r['preferences']['destination'],'HK')
        self.assertIsNone(r['selected_catalog_target']);self.assertFalse(r['complete_collection_established'])
    def test_proposed_cameo_is_not_selectable_official_scope_is_catalog_only(self):
        ai=[dict(type='ask',question='Japanese Mew cameos in card art')]
        r=self.run_turns(ai);self.assertEqual(r['candidate_cards'],[]);self.assertTrue(r['artwork_review_leads'])
        with self.assertRaises(ValueError):self.run_turns(ai+[dict(type='select',card_id=self.cid)])
        strong=[dict(type='ask',question='Japanese Gengar cameos in card art'),dict(type='select',card_id=self.cid)]
        r=self.run_turns(strong);self.assertEqual(r['status'],'catalog_target_selected');self.assertFalse(r['target_intent']['physical_printing_verified'])
    def test_unseen_or_owned_target_cannot_be_selected(self):
        ask=[dict(type='ask',question='Japanese Pikachu cards')]
        r=self.run_turns(ask,limit=1);shown=r['candidate_cards'][0]['card_id']
        unseen=next(cid for cid in [self.cid,'ja:FIX:001/100:holo','ja:FIX:002/100:normal'] if cid!=shown)
        with self.assertRaisesRegex(ValueError,'not shown'):self.run_turns(ask+[dict(type='select',card_id=unseen)],limit=1)
        owned=self.sequence()+[dict(type='inventory',owned_items=[dict(item_id='owned',card_id=self.cid)])]
        with self.assertRaisesRegex(ValueError,'not shown'):self.run_turns(owned+[dict(type='select',card_id=self.cid)])
    def test_ambiguous_yes_or_unknown_reply_does_not_invent_a_choice(self):
        r=self.run_turns([dict(type='ask',question='Pikachu cards'),dict(type='reply',text='Yes')])
        self.assertEqual(r['status'],'followup_clarification_needed');self.assertIsNone(r['selected_catalog_target'])
        r=self.run_turns(self.sequence()+[dict(type='reply',text='maybe holo or perhaps another character')])
        self.assertEqual(r['scope_filters']['variant'],'normal');self.assertFalse(r['selection_allowed'])
        selected=self.sequence()+[dict(type='select',card_id=self.cid),dict(type='reply',text='Maybe another character'),
            dict(type='preferences',preferences=dict(destination='HK'))]
        r=self.run_turns(selected);self.assertEqual(r['status'],'followup_clarification_needed')
        self.assertIsNone(r['target_intent']);self.assertEqual(r['selected_catalog_target']['card_id'],self.cid)
    def test_stale_catalog_revision_and_forged_state_fail_closed(self):
        turns=self.sequence();r=self.run_turns(turns)
        self.assertEqual(self.run_turns(turns,expected_revision=r['catalog_revision'])['catalog_revision'],r['catalog_revision'])
        with closing(core.connect(self.path)) as writer:
            writer.execute("UPDATE card SET provenance='changed' WHERE card_id=?",(self.cid,));writer.commit()
        with self.assertRaisesRegex(ValueError,'policy changed'):self.run_turns(turns,expected_revision=r['catalog_revision'])
        with self.assertRaises(ValueError):collector_journey.replay(self.db,dict(turns=turns,selected_catalog_target=self.cid))
        with self.assertRaises(ValueError):self.run_turns(turns+[dict(type='select',card_id=self.cid,physical_printing_verified=True)])
    def test_equivalent_rebuild_bookkeeping_does_not_change_revision(self):
        with closing(core.connect(self.path)) as writer:
            writer.execute('INSERT INTO card_rarity_correction VALUES (?,?,?,?,?,?,?,?,?,?)',
                (self.cid,'Pikachu',None,'fixture','AR','fixture','https://www.pokemon-card.com/card-search/details.php/card/1','a'*64,'ic_rare_ar.gif','2026-10-01T00:00:00+00:00'))
            writer.commit()
        before=collector_journey.catalog_revision(self.db)
        with closing(core.connect(self.path)) as writer:
            writer.execute("UPDATE card_rarity_correction SET applied_at='2026-10-02T00:00:00+00:00'");writer.commit()
        self.assertEqual(collector_journey.catalog_revision(self.db),before)
        with closing(core.connect(self.path)) as writer:
            writer.execute("UPDATE card_rarity_correction SET official_page_sha256=?",('b'*64,));writer.commit()
        self.assertNotEqual(collector_journey.catalog_revision(self.db),before)
    def test_relationship_evidence_changes_invalidate_journey_but_import_time_does_not(self):
        before=collector_journey.catalog_revision(self.db)
        with closing(core.connect(self.path)) as writer:
            discovery_graph.assert_relationships(writer,[dict(assertion_id='frozen-ai',
                left_card_id=self.cid,right_card_id='en:FIX:001/100:normal',relation_type='same_artwork',
                review_status='proposed',asserted_by='ai-artwork-review-v1',reviewer='fixture-ai',
                evidence_ref='fixture:bound-images',rights_reference='fixture',asserted_at='2026-10-01T00:00:00Z')])
        current=collector_journey.catalog_revision(self.db)
        self.assertNotEqual(current,before)
        with self.assertRaisesRegex(ValueError,'policy changed'):
            self.run_turns(self.sequence(),expected_revision=before)
        with closing(core.connect(self.path)) as writer:
            writer.execute("UPDATE card_relationship_assertion SET asserted_at='2026-10-02T00:00:00Z'");writer.commit()
        self.assertEqual(collector_journey.catalog_revision(self.db),current)
        with closing(core.connect(self.path)) as writer:
            writer.execute("UPDATE card_relationship_assertion SET evidence_ref='fixture:different-images'");writer.commit()
        self.assertNotEqual(collector_journey.catalog_revision(self.db),current)
    def test_budget_is_a_preference_and_market_goal_cannot_be_bypassed(self):
        turns=[dict(type='ask',question='Cheapest Pikachu card'),dict(type='refine',scope=dict(set_code='FIX',collector_number='1/100'))]
        r=self.run_turns(turns);self.assertEqual(r['discovery']['task'],'market_evidence_needed');self.assertFalse(r['selection_allowed'])
        for value in [dict(budget_minor=True),dict(budget_minor=-1),dict(grade_company='FAKE'),dict(landed_cost=1)]:
            with self.assertRaises(ValueError):self.run_turns(self.sequence()+[dict(type='preferences',preferences=value)])
    def test_release_in_original_character_question_is_not_ignored(self):
        with closing(core.connect(self.path)) as writer:
            core.import_cards(writer,[dict(language='ja',set_code='OTHER',collector_number='001/100',variant='normal',name='Pikachu',provenance='fixture',rights_reference='fixture')])
            writer.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',('ja:OTHER:001/100:normal','dex_id','25','fixture','fixture'));writer.commit()
        r=self.run_turns([dict(type='ask',question='Japanese Pikachu cards FIX')])
        self.assertTrue(r['candidate_cards']);self.assertEqual({c['set_code'] for c in r['candidate_cards']},{'FIX'})
    def test_localized_release_name_reply_uses_current_language_scope(self):
        with closing(core.connect(self.path)) as writer:
            writer.execute("INSERT INTO catalog_set_localized(language,set_code,name,official_card_count,provenance,rights_reference,display_allowed) VALUES ('ja','FIX','テストカード',100,'fixture','fixture',0)")
            writer.commit()
        r=self.run_turns([dict(type='ask',question='Japanese Pikachu cards'),dict(type='reply',text='テストカード')])
        self.assertEqual(r['scope_filters']['set_code'],'FIX');self.assertEqual(r['status'],'candidate_clarification_needed')
    def test_release_exclusion_is_not_an_affirmative_purchase_scope(self):
        turns=[dict(type='ask',question='Japanese Pikachu cards excluding FIX')]
        r=self.run_turns(turns);self.assertEqual(r['status'],'evidence_or_scope_needed');self.assertFalse(r['selection_allowed'])
        self.assertIn('release_exclusions_need_explicit_scope',r['selection_blockers'])
        self.assertTrue(r['next_step']['prompt'])
        with self.assertRaisesRegex(ValueError,'blockers'):self.run_turns(turns+[dict(type='select',card_id=self.cid)])
    def test_bounded_requests_and_catalog_remain_immutable(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest();self.run_turns(self.sequence())
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):self.run_turns([dict(type='ask',question='Pikachu cards')]*21)
        with self.assertRaises(ValueError):self.run_turns([dict(type='select',card_id=self.cid)])
        with self.assertRaises(ValueError):self.run_turns(self.sequence(),limit=True)


class CollectorJourneyHTTPTests(JourneyFixture,unittest.TestCase):
    def test_private_route_replays_readonly_and_rejects_bad_requests(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with create_server(str(self.path),'127.0.0.1',0,True) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                url='http://127.0.0.1:'+str(server.server_address[1])+'/collector-journey'
                with urlopen(Request(url,data=json.dumps(dict(turns=self.sequence())).encode(),headers={'Content-Type':'application/json'})) as response:
                    r=json.load(response);self.assertEqual(response.status,200);self.assertEqual(r['candidate_cards'][0]['card_id'],self.cid)
                for payload in [b'not json',json.dumps(dict(turns=self.sequence(),purchase_ready=True)).encode()]:
                    with self.assertRaises(HTTPError) as error:urlopen(Request(url,data=payload,headers={'Content-Type':'application/json'}))
                    self.assertEqual(error.exception.code,400);error.exception.close()
            finally:server.shutdown();thread.join(timeout=5)
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
    def test_route_absent_without_internal_flag(self):
        with create_server(str(self.path),'127.0.0.1',0,False) as server:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request('http://127.0.0.1:'+str(server.server_address[1])+'/collector-journey',data=b'{}',headers={'Content-Type':'application/json'}))
                self.assertEqual(error.exception.code,404);error.exception.close()
            finally:server.shutdown();thread.join(timeout=5)

if __name__=='__main__':unittest.main()

"""Recommendation outcomes and authority boundaries on a frozen synthetic catalog."""
import hashlib,json,tempfile,unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from pokemon_index import core,collector_journey,collector_recommendation as rec,collector_discovery
from scripts.rehearse_collector_recommendations import SUITE,create_fixture,check_result

A='ja:FIX:001/100:normal';B='ja:FIX:002/100:normal';C='ja:FIX:003/100:normal'
HOLD='ja:FIX:006/100:normal';ALPHA='ja:FIX:143A/236:normal'


class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'catalog.sqlite3'
        self.suite=json.loads(SUITE.read_text());create_fixture(self.path,self.suite)
        self.db=core.connect(self.path,readonly=True)
    def tearDown(self):self.db.close();self.temp.cleanup()
    def replay(self,turns,**kw):return collector_journey.replay(self.db,dict(turns=turns,**kw))
    def start(self):return [dict(type='ask',question='Recommend Japanese Pikachu cards')]
    def profile(self,**values):return dict(type='preferences',preferences=dict(collecting=values))
    def test_six_frozen_families_prefix_by_prefix(self):
        families=set()
        for journey in self.suite['journeys']:
            turns=[];families.add(journey['family'])
            for step in journey['steps']:
                turns.append(step['action'])
                with self.subTest(journey=journey['id'],turn=len(turns)):
                    if 'error' in step['expect']:
                        with self.assertRaises(ValueError):self.replay(turns,limit=self.suite['limit'])
                    else:
                        r=self.replay(turns,limit=self.suite['limit'])
                        self.assertEqual(check_result(self.db,r,step['expect']),[])
        self.assertEqual(families,set('ABCDEF'))
    def test_chinese_continuation_and_chinese_species_alias_are_supported(self):
        r=self.replay([dict(type='ask',question='下一步应该收藏什么？'),dict(type='reply',text='英文'),dict(type='reply',text='梦幻')])
        self.assertEqual(r['discovery']['task'],'collector_recommendations')
        self.assertEqual({c['language'] for c in r['candidate_cards']},{'en'})
        r=self.replay([dict(type='ask',question='推荐日版皮卡丘卡片')])
        self.assertTrue(r['candidate_cards']);self.assertEqual({c['language'] for c in r['candidate_cards']},{'ja'})
    def test_number_and_existing_unfulfilled_scope_constraints_survive_recommendations(self):
        r=self.replay([dict(type='ask',question='Recommend Japanese Pikachu cards FIX 2/100')])
        self.assertEqual([c['card_id'] for c in r['candidate_cards']],[B])
        for number in ['143a/236','1/100 and 2/100']:
            r=self.replay([dict(type='ask',question='Recommend Japanese Pikachu cards '+number)])
            self.assertEqual(r['candidate_cards'],[]);self.assertFalse(r['selection_allowed'])
        for q in ['Recommend custom Pikachu cards','Recommend Korean Pikachu cards. What should I collect next?']:
            r=self.replay([dict(type='ask',question=q),self.profile(preferred_dex_ids=[25])])
            self.assertIsNone(r['recommendation']);self.assertFalse(r['selection_allowed'])
        r=self.replay([dict(type='ask',question='Every Pikachu card across every language'),self.profile(preferred_dex_ids=[25])])
        self.assertIn('all_language_coverage',r['selection_blockers'])
    def test_artist_or_release_reply_progresses_without_free_text_concatenation(self):
        for text in ['Alpha','FIX']:
            turns=[dict(type='ask',question='What should I collect next?'),dict(type='reply',text='Japanese'),dict(type='reply',text=text)]
            r=self.replay(turns)
            self.assertEqual(r['discovery']['task'],'collector_recommendations')
            self.assertTrue(r['candidate_cards']);self.assertEqual(r['goal_question'],'What should I collect next?')
            self.assertEqual(r['next_step']['field'],'recommendation_feedback_or_choice')
    def test_profile_patch_clear_remove_and_conflict(self):
        old=dict(preferred_dex_ids=[25],preferred_illustrators=['Alpha'],mode='explore')
        new=rec.merge_profile(self.db,old,dict(preferred_dex_ids=[151],preferred_illustrators=[],mode=None))
        self.assertEqual(new,dict(preferred_dex_ids=[151],preferred_illustrators=[]))
        with self.assertRaises(ValueError):rec.merge_profile(self.db,old,dict(excluded_dex_ids=[25]))
        for value in [dict(unknown=True),dict(mode=[]),dict(preferred_dex_ids=[True]),dict(preferred_dex_ids=[0]),dict(preferred_dex_ids=[1026]),
                      dict(preferred_dex_ids=list(range(1,22))),dict(preferred_dex_ids=[25,25]),dict(preferred_illustrators=['Unknown']),
                      dict(preferred_releases=[dict(language='ja',set_code='NOTREAL')]),dict(preferred_releases=[dict(language='ja',set_code='FIX',purchase_ready=True)]),
                      dict(subjective_notes=['a'*161]),dict(preferred_dex_ids=[25],excluded_dex_ids=[25])]:
            with self.subTest(value=value),self.assertRaises(ValueError):rec.validate_collecting_preferences(self.db,value)
    def test_deterministic_absolute_rank_pages_and_provenance(self):
        turns=self.start()+[self.profile(preferred_illustrators=['Alpha'])]
        r=self.replay(turns,limit=2)
        self.assertEqual(r,self.replay(turns,limit=2))
        self.assertEqual([i['rank'] for i in r['recommendation']['items']],[1,2])
        second=self.replay(turns+[dict(type='page',offset=2)],limit=2)
        self.assertEqual([i['rank'] for i in second['recommendation']['items']],[3,4])
        self.assertFalse(set(c['card_id'] for c in r['candidate_cards'])&set(c['card_id'] for c in second['candidate_cards']))
        for item in r['recommendation']['items']:
            for reason in item['reasons']:
                if reason['basis']=='catalog_facet':
                    self.assertTrue(self.db.execute('SELECT 1 FROM discovery_card_facet WHERE card_id=? AND facet_type=? AND value=? AND provenance=?',
                        (item['card_id'],reason['field'],str(reason['value']),reason['source_ref'])).fetchone())
    def test_equal_score_coordinates_diversify_without_merging_ids(self):
        r=self.replay(self.start(),limit=3)
        coords=[(c['language'],c['set_code'],c['collector_number']) for c in r['candidate_cards']]
        self.assertEqual(len(set(coords)),3)
        self.assertTrue(all(g['physical_versions_merged'] is False for g in r['recommendation']['coordinate_groups']))
        self.assertLessEqual(len(self.replay(self.start())['candidate_cards']),5)
    def test_dismiss_is_exact_not_species_and_clear_restores(self):
        turns=self.start();baseline=self.replay(turns,limit=20)
        dismissal=dict(type='feedback',card_id=A,reaction='dismiss')
        r=self.replay(turns+[dismissal],limit=20)
        ids=[c['card_id'] for c in r['candidate_cards']]
        self.assertNotIn(A,ids);self.assertIn(B,ids);self.assertIn('ja:FIX:001/100:holo',ids)
        clear=dict(type='feedback',card_id=A,reaction='clear')
        self.assertEqual(self.replay(turns+[dismissal,clear],limit=20)['candidate_cards'],baseline['candidate_cards'])
        one=self.replay(turns+[dismissal],limit=20)
        twice=self.replay(turns+[dismissal,dismissal],limit=20)
        self.assertEqual(one['recommendation'],twice['recommendation'])
    def test_feedback_scope_change_rejects_stale_page_ids(self):
        turns=self.start()+[self.profile(preferred_dex_ids=[151])]
        with self.assertRaisesRegex(ValueError,'current recommendation context'):
            self.replay(turns+[dict(type='feedback',card_id=A,reaction='like')],limit=20)
        turns=self.start()+[dict(type='ask',question='Recommend Japanese Mew cards')]
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='feedback',card_id=A,reaction='dismiss')],limit=20)
        for reaction in ['love',True,{'like':True}]:
            with self.assertRaises(ValueError):self.replay(self.start()+[dict(type='feedback',card_id=A,reaction=reaction)],limit=20)
    def test_owned_and_possible_owned_share_existing_semantics(self):
        owned=[dict(item_id='maybe',language='ja',set_code='FIX',collector_number='001/100'),dict(item_id='exact',card_id=B,quantity=2)]
        r=self.replay(self.start()+[dict(type='inventory',owned_items=owned)],limit=20)
        self.assertFalse(r['selection_allowed'])
        self.assertIn('owned_inventory_resolution',r['selection_blockers'])
        self.assertNotIn(A,[c['card_id'] for c in r['candidate_cards']]);self.assertNotIn(B,[c['card_id'] for c in r['candidate_cards']])
        self.assertEqual(r['inventory']['owned_in_scope'][0]['quantity'],2)
        resolved=self.start()+[dict(type='inventory',owned_items=owned),dict(type='resolve_owned',item_id='maybe',card_id=A)]
        r=self.replay(resolved,limit=20);self.assertTrue(r['selection_allowed'])
        self.assertIn('ja:FIX:001/100:holo',[c['card_id'] for c in r['candidate_cards']])
    def test_scope_cap_before_pagination_no_silent_truncation(self):
        with patch.object(rec.inventory,'MAX_SCOPE',2):
            r=self.replay(self.start(),limit=1)
        self.assertEqual(r['discovery']['status'],'scope_too_broad');self.assertEqual(r['candidate_cards'],[])
        self.assertFalse(r['recommendation']['candidate_pool_complete']);self.assertFalse(r['selection_allowed'])
    def test_no_positive_signal_and_no_match_do_not_widen(self):
        r=self.replay([dict(type='ask',question='What should I collect next?')])
        self.assertEqual(r['candidate_cards'],[]);self.assertEqual(r['discovery']['task'],'collection_preferences_needed')
        r=self.replay(self.start()+[dict(type='refine',scope={'collector_number':'999/100'})])
        self.assertEqual(r['candidate_cards'],[]);self.assertEqual(r['discovery']['status'],'no_match')
        self.assertTrue(r['recommendation']['candidate_pool_complete'])
    def test_profile_arrays_empty_and_null_reset_goal(self):
        r=self.replay(self.start()+[self.profile(preferred_dex_ids=[])])
        self.assertEqual(r['candidate_cards'],[])
        r=self.replay(self.start()+[dict(type='preferences',preferences=dict(collecting=None))])
        self.assertEqual(r['candidate_cards'],[]);self.assertNotIn('collecting',r['preferences'])
    def test_target_and_pagination_reset_on_preferences_feedback_goal(self):
        chosen=self.start()+[dict(type='select',card_id=B)]
        for change in [self.profile(preferred_dex_ids=[151]),dict(type='feedback',card_id=B,reaction='dismiss'),dict(type='ask',question='Recommend English Mew cards')]:
            r=self.replay(chosen+[change],limit=20)
            self.assertIsNone(r['target_intent']);self.assertIsNone(r['selected_catalog_target']);self.assertEqual(r['discovery']['coverage']['offset'],0)
        paged=self.start()+[dict(type='page',offset=2),self.profile(preferred_dex_ids=[151])]
        self.assertEqual(self.replay(paged)['discovery']['coverage']['offset'],0)
    def test_compare_focus_select_is_separate_and_catalog_only(self):
        turns=self.start()+[dict(type='compare',left_card_id=A,right_card_id=B)]
        compared=self.replay(turns,limit=20)
        self.assertEqual(compared['candidate_cards'],[]);self.assertIsNone(compared['recommendation'])
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=B)],limit=20)
        focus=turns+[dict(type='choose_comparison',side='right',card_id=B)]
        r=self.replay(focus,limit=20)
        self.assertEqual([c['card_id'] for c in r['candidate_cards']],[B]);self.assertIsNone(r['target_intent'])
        selected=self.replay(focus+[dict(type='select',card_id=B)],limit=20)
        self.assertEqual(selected['target_intent']['card_id'],B)
        self.assertFalse(selected['target_intent']['transaction_ready']);self.assertIsNone(selected['target_intent']['product_url'])
    def test_focus_requires_exact_membership_resolved_side(self):
        turns=self.start()+[dict(type='compare',left_card_id=A,right_card_id=B)]
        for side,cid in [('right',A),('third',B),('right','invented')]:
            with self.assertRaises(ValueError):self.replay(turns+[dict(type='choose_comparison',side=side,card_id=cid)],limit=20)
        for status,truncated in [('not_found',False),('refinement_needed',True),('release_confirmation_needed',False)]:
            from pokemon_index import card_comparison
            real=card_comparison.compare(self.db,dict(left={'card_id':A},right={'card_id':B}))
            real['right'].update(status=status,records_truncated=truncated)
            with patch.object(collector_journey.card_comparison,'compare',return_value=real):
                with self.assertRaises(ValueError):self.replay(turns+[dict(type='choose_comparison',side='right',card_id=B)],limit=20)
    def test_raw_coordinate_variants_focus_explicit_member_only(self):
        turns=[dict(type='ask',question='Compare Japanese FIX 1/100 and Japanese FIX 2/100')]
        r=self.replay(turns);self.assertEqual(r['discovery']['comparison']['left']['status'],'coordinate_variants')
        r=self.replay(turns+[dict(type='choose_comparison',side='left',card_id=A)])
        self.assertEqual([c['card_id'] for c in r['candidate_cards']],[A])
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='choose_comparison',side='left',card_id=B)])
    def test_alphanumeric_focus_never_uses_fraction_scope_parser(self):
        turns=self.start()+[dict(type='compare',left_card_id=A,right_card_id=ALPHA),dict(type='choose_comparison',side='right',card_id=ALPHA)]
        r=self.replay(turns,limit=20)
        self.assertEqual([c['collector_number'] for c in r['candidate_cards']],['143A/236'])
    def test_match_disabled_record_cannot_be_selected_directly_or_after_comparison(self):
        turns=[dict(type='ask',question='Recommend Japanese cards by Alpha'),dict(type='compare',left_card_id=A,right_card_id=HOLD),dict(type='choose_comparison',side='right',card_id=HOLD)]
        r=self.replay(turns,limit=20)
        self.assertIn('catalog_identity_review_needed',r['selection_blockers']);self.assertFalse(r['selection_allowed'])
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=HOLD)],limit=20)
        direct=[dict(type='ask',question=HOLD)]
        with self.assertRaises(ValueError):self.replay(direct+[dict(type='select',card_id=HOLD)])
    def test_focus_rehydrates_all_copy_and_identity_guards(self):
        turns=self.start()+[dict(type='compare',left_card_id=A,right_card_id=B),dict(type='choose_comparison',side='right',card_id=B)]
        materialize=collector_discovery._card_result
        for guard in ['coordinate','parts','source_family','number_conflict']:
            def guarded(db,row):
                card=materialize(db,row)
                if row['card_id']==B:
                    if guard=='coordinate':card['official_coordinate_family']={'copy_evidence_needed':True}
                    if guard=='parts':card['official_metadata']={'official':{'page_kind':'numbered_parts'}}
                return card
            from pokemon_index import source_corrections
            with patch.object(collector_discovery,'_card_result',side_effect=guarded), \
                 patch.object(source_corrections,'family_scope_only',side_effect=lambda db,cid:guard=='source_family' and cid==B), \
                 patch.object(collector_journey.discovery_graph,'endpoint_identity_blockers',side_effect=lambda db,cid:['source_image_number_coordinate_conflict'] if guard=='number_conflict' and cid==B else []):
                with self.subTest(guard=guard):
                    r=self.replay(turns,limit=20);self.assertFalse(r['selection_allowed'])
                    with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=B)],limit=20)
    def test_comparison_stale_context_and_owned_focus_cannot_bypass(self):
        base=self.start()+[dict(type='compare',left_card_id=A,right_card_id=B)]
        changed=base+[self.profile(preferred_dex_ids=[151])]
        with self.assertRaises(ValueError):self.replay(changed+[dict(type='choose_comparison',side='right',card_id=B)],limit=20)
        with self.assertRaises(ValueError):self.replay(self.start()+[dict(type='compare',left_card_id=A,right_card_id=C)],limit=20)
        question='Compare ja:FIX:001/100:normal and ja:FIX:002/100:normal'
        raw=[dict(type='ask',question=question),dict(type='inventory',owned_items=[dict(item_id='owned',card_id=B)])]
        with self.assertRaisesRegex(ValueError,'active comparison'):
            self.replay(raw+[dict(type='choose_comparison',side='right',card_id=B)])
        # A newly requested comparison may be focused, but cannot revive an
        # already owned record as a missing catalog target.
        refreshed=raw+[dict(type='ask',question=question),dict(type='choose_comparison',side='right',card_id=B)]
        self.assertEqual(self.replay(refreshed)['candidate_cards'],[])
        with self.assertRaises(ValueError):self.replay(refreshed+[dict(type='select',card_id=B)])
    def test_pure_market_and_unsupported_product_goals_cannot_use_profile_to_bypass(self):
        for q in ['Cheapest Pikachu card','Where can I buy Pikachu?','Recommend Pikachu sleeves','Recommend Korean Pikachu cards']:
            r=self.replay([dict(type='ask',question=q),self.profile(preferred_dex_ids=[25])])
            self.assertIsNone(r['recommendation']);self.assertFalse(r['selection_allowed'])
    def test_unrecognized_taste_is_retained_and_ambiguous_names_do_not_pick_one(self):
        for reply in ['invented Pokemon','Pikachu or Mew','maybe some vintage vibes']:
            r=self.replay([dict(type='ask',question='What should I collect next?'),dict(type='reply',text=reply)])
            self.assertEqual(r['status'],'followup_clarification_needed');self.assertFalse(r['selection_allowed'])
            self.assertIn(reply,r['preferences']['collecting']['subjective_notes'])
    def test_budget_and_style_are_honest_without_feed(self):
        r=self.replay([dict(type='ask',question='Recommend Japanese Pikachu cards under $50; I like cute art')])
        self.assertEqual(r['preferences']['budget_minor'],5000);self.assertEqual(r['preferences']['currency'],'USD')
        self.assertEqual(r['recommendation']['budget_fit'],'unknown_no_live_price')
        self.assertTrue(r['recommendation']['unapplied_preferences']);self.assertFalse(r['preferences_applied_to_market'])
        self.assertEqual(r['prices'],[])
    def test_stale_revision_extra_fields_21_turns_and_immutability(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        r=self.replay(self.start())
        with self.assertRaises(ValueError):self.replay(self.start(),expected_revision='a'*64)
        with self.assertRaises(ValueError):self.replay(self.start()*21)
        for action in [dict(type='feedback',card_id=A,reaction='like',purchase_ready=True),dict(type='compare',left_card_id=A,right_card_id=B,quote={}),dict(type='preferences',preferences={'collecting':{'public_display_allowed':True}})]:
            with self.assertRaises(ValueError):self.replay(self.start()+[action])
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertIsNone(r['target_intent'])

if __name__=='__main__':unittest.main()

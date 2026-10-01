"""Collector goals discovered in fresh public scenarios must not change intent."""
import unittest
from pokemon_index import collector_discovery
from test_collector_journey import JourneyFixture


class GoalBoundaryTests(JourneyFixture,unittest.TestCase):
    def test_non_card_accessories_cannot_turn_into_artist_card_targets(self):
        for question in ['I want sleeves and playmats with Pikachu artwork, anything other than Pokemon cards.',
                         'A list of Tomokazu Komiya sleeves and playmats', 'ピカチュウのスリーブ一覧']:
            r=self.run_turns([dict(type='ask',question=question),dict(type='reply',text='Japanese')])
            self.assertEqual(r['discovery']['task'],'other_product_evidence_needed')
            self.assertFalse(r['selection_allowed']);self.assertIsNone(r['target_intent'])
        r=collector_discovery.execute(self.db,'Japanese Pikachu cards for my binder')
        self.assertEqual(r['task'],'character_cards');self.assertTrue(r['cards'])
    def test_every_language_needs_scope_and_explicit_language_removes_that_constraint(self):
        turns=[dict(type='ask',question='Every Pikachu card across every language')]
        r=self.run_turns(turns);self.assertIn('all_language_coverage',r['selection_blockers'])
        r=self.run_turns(turns+[dict(type='reply',text='Japanese')])
        self.assertNotIn('all_language_coverage',r['selection_blockers']);self.assertTrue(r['selection_allowed'])
        self.assertEqual({c['language'] for c in r['candidate_cards']},{'ja'})
        self.assertFalse(r['complete_collection_established'])
        r=self.run_turns([dict(type='ask',question='Pikachu cards in any language')])
        self.assertNotIn('all_language_coverage',r['selection_blockers'])
    def test_next_collection_is_new_goal_clarification_not_retrieval_of_completed_scope(self):
        for question in ['I completed my Pikachu collection. What should I collect next?', 'ピカチュウは揃った。次に何を集める？']:
            r=self.run_turns([dict(type='ask',question=question),dict(type='reply',text='English')])
            self.assertEqual(r['discovery']['task'],'collection_preferences_needed')
            self.assertEqual(r['candidate_cards'],[]);self.assertFalse(r['selection_allowed'])
        r=self.run_turns([dict(type='ask',question='I completed my Pikachu collection. Show Japanese Pikachu cards.')])
        self.assertTrue(r['candidate_cards'])
    def test_purchase_availability_remains_market_goal_after_coordinate_refinement(self):
        turns=[dict(type='ask',question='Where can I purchase the last Pikachu cards?'),
               dict(type='refine',scope=dict(language='ja',set_code='FIX',collector_number='1/100'))]
        r=self.run_turns(turns);self.assertEqual(r['discovery']['task'],'market_evidence_needed')
        self.assertFalse(r['selection_allowed']);self.assertEqual(r['prices'],[])
        r=self.run_turns([dict(type='ask',question='Where can I find a list of Japanese Pikachu cards?')])
        self.assertEqual(r['discovery']['task'],'character_cards');self.assertTrue(r['candidate_cards'])
    def test_natural_counterpart_request_is_not_replaced_with_base_card_purchase(self):
        turns=[dict(type='ask',question='Does Pikachu 1/100 have an English version?'),
               dict(type='refine',scope=dict(language='ja',set_code='FIX',collector_number='1/100',variant='normal'))]
        r=self.run_turns(turns);self.assertEqual(r['discovery']['task'],'cross_language_relation')
        self.assertFalse(r['selection_allowed']);self.assertEqual(r['candidate_cards'],[])
        r=self.run_turns(turns+[dict(type='ask',question='Japanese Pikachu FIX 1/100 non-holo')])
        self.assertTrue(r['selection_allowed']);self.assertEqual(r['candidate_cards'][0]['card_id'],self.cid)

if __name__=='__main__':unittest.main()

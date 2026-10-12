"""Bounded fixes for exposed ICU03/09/16/26 diagnostics; synthetic source data."""
import unittest

from pokemon_index import core,collector_discovery as discovery,collector_recommendation as recommendation,collector_runtime
import test_independent_recommendation_review as fixture


class BoundedNegativeScopeTests(unittest.TestCase):
    setUp=fixture.IndependentRecommendationReview.setUp
    tearDown=fixture.IndependentRecommendationReview.tearDown
    replay=fixture.IndependentRecommendationReview.replay

    def add(self,number,name,dex):
        cid=core.card_id('ja','NAMES',number+'/100','normal')
        core.import_cards(self.db,[dict(language='ja',set_code='NAMES',collector_number=number+'/100',
            variant='normal',name=name,match_eligible=True,provenance='test:names',rights_reference='test:names')])
        core.import_card_facets(self.db,[dict(card_id=cid,facet_type='dex_id',value=dex,
            provenance='test:names',rights_reference='test:names')])
        return cid

    def test_maximal_name_matching_is_per_occurrence_and_keeps_conflicting_ids(self):
        for number,name,dex in [('001','リザード',5),('002','リザードン',6),('003','ミュウ',151),('004','ミュウツー',150)]:
            self.add(number,name,dex)
        for text,expected in [('リザードン',[6]),('ミュウツー',[150]),('リザード and リザードン',[5,6]),
                              ('ミュウ and ミュウツー',[150,151])]:
            self.assertEqual(discovery._character_ids(self.db,text),expected)
        self.add('005','リザードン',5)
        self.assertEqual(discovery._character_ids(self.db,'リザードン'),[5,6])

    def test_exact_exclusion_is_hard_and_keeps_release_scope(self):
        turns=[dict(type='ask',question='Recommend Japanese cards from AAA, but exclude Mew.')]
        out=self.replay(turns)
        self.assertTrue(out['selection_allowed'])
        self.assertNotIn(fixture.MEW,[c['card_id'] for c in out['candidate_cards']])
        self.assertTrue(all(c['language']=='ja' and c['set_code']=='AAA' for c in out['candidate_cards']))
        self.assertEqual(out['preferences']['collecting']['excluded_dex_ids'],[151])
        self.assertNotIn(151,out['preferences']['collecting'].get('preferred_dex_ids',[]))
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=fixture.MEW)])

    def test_current_exclusion_alias_reuse_withdraws_on_mutation_and_recovers_after_rollback(self):
        self.add('020','Currentname',151);self.db.commit()
        queries=[];self.db.set_trace_callback(queries.append)
        @collector_runtime.catalog_request
        def check(db):
            self.assertIsNotNone(recommendation.bounded_negative_intent(db,'exclude Currentname'))
            self.assertIsNotNone(recommendation.bounded_negative_intent(db,'exclude Currentname'))
            self.assertEqual(sum('SELECT DISTINCT name,dex_id,current_evidence' in q for q in queries),1)
            db.execute("UPDATE card SET provenance='changed' WHERE name='Currentname'")
            self.assertIsNone(recommendation.bounded_negative_intent(db,'exclude Currentname'))
            db.rollback()
            self.assertIsNotNone(recommendation.bounded_negative_intent(db,'exclude Currentname'))
        try:check(self.db)
        finally:self.db.set_trace_callback(None)

    def test_later_exclusion_replaces_older_soft_species_and_invalidates_authority(self):
        start=[dict(type='ask',question='Recommend Japanese Mew cards'),dict(type='select',card_id=fixture.MEW)]
        turns=start+[dict(type='reply',text='exclude Mew')]
        out=self.replay(turns)
        self.assertIsNone(out['target_intent'])
        self.assertEqual(out['preferences']['collecting']['preferred_dex_ids'],[])
        self.assertEqual(out['preferences']['collecting']['excluded_dex_ids'],[151])
        turns += [dict(type='preferences',preferences={'collecting':{'preferred_illustrators':['Yuka Morii']}}),
                  dict(type='refine',scope={'language':'ja'})]
        self.assertNotIn(fixture.MEW,[c['card_id'] for c in self.replay(turns)['candidate_cards']])
        with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=fixture.MEW)])
        compared=[dict(type='ask',question='Recommend Japanese cards from AAA'),
                  dict(type='compare',left_card_id=fixture.A,right_card_id=fixture.MEW),
                  dict(type='reply',text='exclude Mew')]
        with self.assertRaises(ValueError):
            self.replay(compared+[dict(type='choose_comparison',side='right',card_id=fixture.MEW)])

    def test_unrecognized_or_contradictory_negative_grammar_remains_held(self):
        for clause in ['do not exclude Mew','not exclude Mew','exclude Unknown',
                       'exclude Mew and Pikachu','exclude Mew cameos','exclude Mew ex',
                       'recommend Mew but exclude Mew','exclude Mew, but not Pikachu']:
            with self.subTest(clause=clause):
                turns=[dict(type='ask',question='Recommend Japanese cards from AAA; '+clause),
                       dict(type='refine',scope={'language':'ja'}),dict(type='page',offset=0)]
                out=self.replay(turns)
                self.assertFalse(out['selection_allowed'])
                with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=fixture.MEW)])

    def test_ownership_phrase_requires_inventory_and_preserves_sibling_versions(self):
        turns=[dict(type='ask',question="Recommend Japanese Pikachu cards I don't already own.")]
        before=self.replay(turns)
        self.assertIn('owned_inventory_not_supplied',before['selection_blockers'])
        self.assertIn('owned-card list',before['next_step']['prompt'])
        with self.assertRaises(ValueError):
            self.replay(turns+[dict(type='refine',scope={'set_code':'AAA'}),dict(type='select',card_id=fixture.A)])
        turns += [dict(type='inventory',owned_items=[dict(item_id='mine',card_id=fixture.A,quantity=1)])]
        out=self.replay(turns)
        self.assertTrue(out['selection_allowed'])
        self.assertNotIn(fixture.A,[c['card_id'] for c in out['candidate_cards']])
        self.assertIn('ja:AAA:001/100:holo',[c['card_id'] for c in out['candidate_cards']])
        self.assertIn('supplied inventory records',out['next_step']['prompt'])

    def test_unknown_inventory_and_nonownership_negation_do_not_authorize_selection(self):
        for question in ["Recommend Japanese Pikachu cards I don't already own.",
                         "Recommend Japanese Pikachu cards I don't like."]:
            with self.subTest(question=question):
                turns=[dict(type='ask',question=question),dict(type='inventory',owned_items=[
                    dict(item_id='unknown',card_id='ja:AAA:999/100:normal',quantity=1)]),
                    dict(type='refine',scope={'language':'ja'}),dict(type='page',offset=0)]
                self.assertFalse(self.replay(turns)['selection_allowed'])
                with self.assertRaises(ValueError):self.replay(turns+[dict(type='select',card_id=fixture.A)])

    def test_empty_artist_intersection_offers_relaxation_not_a_fake_coordinate(self):
        result=discovery.execute(self.db,'Only show Japanese Mew cards illustrated by Tomokazu Komiya')
        self.assertEqual(result['cards'],[])
        self.assertIn('relax either constraint',result['next_question'])
        self.assertNotIn('exact coordinate',result['next_question'])


if __name__=='__main__':unittest.main()

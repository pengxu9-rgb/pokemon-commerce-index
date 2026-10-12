"""Recommendation use of bounded affiliation evidence and request-local caches."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pokemon_index import collector_character_affiliation as affiliation, collector_journey, core
from pokemon_index import collector_recommendation as recommendation, supported_catalog
import test_collector_character_affiliation as fixture


class RecommendationAffiliationIntegration(unittest.TestCase):
    setUp=fixture.CharacterAffiliationTests.setUp
    tearDown=fixture.CharacterAffiliationTests.tearDown
    add_anchor=fixture.CharacterAffiliationTests.add_anchor

    def evidence(self):
        return patch.object(supported_catalog,'support_for_card',return_value={
            'status':'supported_for_internal_review','evidence':self.support})

    def recommend(self, profile=None, feedback=None, **kwargs):
        return recommendation.recommend(self.db,'What should I collect next?',
            profile or {},feedback or {},limit=50,**kwargs)

    def test_union_ranking_hard_scope_exclusion_and_inventory(self):
        with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence():
            result=self.recommend({'preferred_dex_ids':[151],
                'preferred_releases':[{'language':'ja','set_code':'SV4A'}]})
            self.assertEqual(result['cards'][0]['card_id'],self.cid)
            item=result['recommendation']['items'][0]
            self.assertEqual(set(item['explicit_match_axes']),{'character','release'})
            reason=next(r for r in item['reasons'] if r['field']=='character_name_affiliation')
            self.assertEqual(reason['basis'],'source_name_character_affiliation')
            self.assertFalse(reason['source_asserted_dex_id'])
            self.assertEqual(reason['affiliated_card_id'],self.cid)
            self.assertEqual(reason['affiliation_role'],'candidate')
            self.assertFalse(result['scope']['coverage']['missing_character_facets_excluded'])
            self.assertEqual(self.recommend({'preferred_dex_ids':[151]},scope={'language':'en'})['cards'],[])
            excluded=self.recommend({'preferred_releases':[{'language':'ja','set_code':'SV4A'}],
                                      'excluded_dex_ids':[151]})
            self.assertEqual(excluded['cards'],[])
            owned=self.recommend({'preferred_dex_ids':[151]},owned=[{'item_id':'owned','card_id':self.cid}])
            self.assertNotIn(self.cid,[c['card_id'] for c in owned['cards']])
            dismissed=self.recommend({'preferred_dex_ids':[151]},{self.cid:'dismiss'})
            self.assertNotIn(self.cid,[c['card_id'] for c in dismissed['cards']])
        self.assertFalse(self.db.execute("SELECT 1 FROM card_facet WHERE card_id=? AND facet_type='dex_id'",(self.cid,)).fetchone())

    def test_liking_affiliate_expands_character_with_separate_source_proof(self):
        with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence():
            result=self.recommend(feedback={self.cid:'like'})
        self.assertIn(self.anchor,[c['card_id'] for c in result['cards']])
        item=next(i for i in result['recommendation']['items'] if i['card_id']==self.anchor)
        self.assertEqual(item['liked_example_match_axes'],['character'])
        self.assertTrue(any(r['basis']=='liked_example_catalog_facet' for r in item['reasons']))
        origin=next(r for r in item['reasons'] if r.get('affiliation_role')=='liked_example')
        self.assertEqual(origin['affiliated_card_id'],self.cid)
        self.assertEqual(origin['preference_origin'],'liked_example')
        self.assertFalse(origin['source_asserted_dex_id'])

    def test_affiliation_memo_is_replay_local_and_invalidates_on_mutation(self):
        cache={'revision':'a'*64}
        queries=[];self.db.set_trace_callback(queries.append)
        with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence(),\
             patch.object(affiliation,'affiliations',wraps=affiliation.affiliations) as checked:
            for offset in range(20):
                self.recommend({'preferred_dex_ids':[151]},pool_cache=cache,offset=offset)
            self.assertEqual(checked.call_count,1)
            self.assertEqual(sum('SELECT c.card_id,c.name,c.provenance card_provenance' in q for q in queries),1)
            self.db.execute('UPDATE card_classification SET provenance=? WHERE card_id=?',('stale',self.cid))
            result=self.recommend({'preferred_dex_ids':[151]},pool_cache=cache)
            self.assertEqual(checked.call_count,2)
            self.assertNotIn(self.cid,[c['card_id'] for c in result['cards']])
            cache['revision']='b'*64
            self.recommend({'preferred_dex_ids':[151]},pool_cache=cache)
            self.assertEqual(checked.call_count,3)

    def test_unknown_exclusion_coverage_and_classification_cache_invalidation(self):
        cid='ja:SV4A:050/190:normal';cache={'revision':'a'*64}
        core.import_cards(self.db,[dict(language='ja',set_code='SV4A',collector_number='050/190',
            variant='normal',name='Synthetic Trainer',provenance='synthetic:trainer',rights_reference='synthetic:rights')])
        core.import_card_classifications(self.db,[dict(card_id=cid,category='Trainer',
            provenance='synthetic:trainer',rights_reference='synthetic:rights')])
        profile={'preferred_releases':[{'language':'ja','set_code':'SV4A'}],'excluded_dex_ids':[151]}
        with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence():
            first=self.recommend(profile,pool_cache=cache)
            self.assertIn(cid,[c['card_id'] for c in first['cards']])
            self.db.execute('UPDATE card_classification SET provenance=? WHERE card_id=?',('stale',cid))
            second=self.recommend(profile,pool_cache=cache)
            self.assertNotIn(cid,[c['card_id'] for c in second['cards']])
            self.assertEqual(second['scope']['coverage']['exclusion_unknown_membership_withheld'],1)
            self.assertIn('withheld',second['scope']['next_question'])

    def test_other_connection_changes_invalidate_affiliation_memo(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'catalog.sqlite3';disk=core.connect(path)
            self.db.backup(disk);other=core.connect(path);cache={'revision':'a'*64}
            try:
                with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence(),\
                     patch.object(affiliation,'affiliations',wraps=affiliation.affiliations) as checked:
                    self.assertIn(self.cid,recommendation._current_affiliations(disk,cache))
                    other.execute('UPDATE card_classification SET provenance=? WHERE card_id=?',('stale',self.cid));other.commit()
                    self.assertNotIn(self.cid,recommendation._current_affiliations(disk,cache))
                    self.assertEqual(checked.call_count,2)
            finally:other.close();disk.close()

    def test_reason_mutation_does_not_corrupt_cached_proof(self):
        cache={'revision':'a'*64}
        with patch.object(affiliation,'_bindings',return_value=[self.binding]),self.evidence():
            first=self.recommend({'preferred_dex_ids':[151]},pool_cache=cache)
            reason=next(r for i in first['recommendation']['items'] for r in i['reasons'] if r['field']=='character_name_affiliation')
            reason['anchor_evidence'][0]['name']='forged'
            second=self.recommend({'preferred_dex_ids':[151]},pool_cache=cache)
            reason=next(r for i in second['recommendation']['items'] for r in i['reasons'] if r['field']=='character_name_affiliation')
            self.assertEqual(reason['anchor_evidence'][0]['name'],'ミュウ')


if __name__=='__main__':unittest.main()

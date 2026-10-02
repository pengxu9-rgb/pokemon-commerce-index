import json,unittest
from pokemon_index import core,collector_discovery,discovery_graph
from tests import test_discovery_graph as graph_fixture

class CollectorRelationLanguageTests(unittest.TestCase):
    assertion=graph_fixture.DiscoveryGraphTests.assertion
    def setUp(self):
        graph_fixture.DiscoveryGraphTests.setUp(self);self.db.execute('UPDATE card SET match_eligible=1 WHERE card_id=?',(self.en,));self.db.commit()
        row=self.assertion('verified','synthetic-reviewer');row['relation_type']='same_artwork';proof=json.loads(row['evidence_ref'])
        for key in ['first_review','second_review']:proof[key]['decision']='same_artwork'
        proof['finish']=dict(outcome='not_comparable',note='Synthetic artwork-only test; no finish approval');row['evidence_ref']=json.dumps(proof,sort_keys=True);discovery_graph.assert_relationships(self.db,[row])
    def tearDown(self):self.db.close()
    def test_canonical_source_language_is_not_a_requested_output_language(self):
        r=collector_discovery.execute(self.db,'same artwork as '+self.en)
        self.assertEqual(r['languages'],['ja','en']);self.assertEqual(r['verified_links'][0]['other_card_id'],self.ja);self.assertFalse(r['price_comparable'])
    def test_explicit_english_scope_still_filters_japanese_counterpart(self):
        for kwargs,q in [({},'English only same artwork as '+self.en),({'scope':{'language':'en'}},'same artwork as '+self.en)]:
            r=collector_discovery.execute(self.db,q,**kwargs);self.assertEqual(r['languages'],['en']);self.assertEqual(r['verified_links'],[])
    def test_ordinary_canonical_english_identity_lookup_retains_exact_identity(self):
        r=collector_discovery.execute(self.db,self.en);self.assertEqual([c['card_id'] for c in r['cards']],[self.en])

if __name__=='__main__':unittest.main()

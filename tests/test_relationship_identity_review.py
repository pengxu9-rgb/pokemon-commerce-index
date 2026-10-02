import hashlib
import json
import sqlite3
import unittest

from pokemon_index import core, discovery_graph
from scripts.freeze_relationship_identity_review import FIELDS, check_current, digest
from scripts.compile_relationship_identity_reviews import compile_reviews


class RelationshipIdentityReviewTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;core.init_db(self.db)
        core.import_cards(self.db,[dict(language=lang,set_code=code,collector_number='001/010',variant='normal',name=name,
            provenance='fixture',rights_reference='internal fixture',match_eligible=True,display_allowed=False)
            for lang,code,name in [('ja','JA','名前'),('en','EN','Name')]])
        self.ids=['en:EN:001/010:normal','ja:JA:001/010:normal']
        self.cid=hashlib.sha256(('relationship-pilot-v1\0'+'\0'.join(self.ids)).encode()).hexdigest()[:20]
        prior=dict(assertion_id='old-proposal',left_card_id=self.ids[0],right_card_id=self.ids[1],relation_type='same_artwork',
                   review_status='proposed',evidence_ref='fixture old source',rights_reference='fixture',asserted_by='fixture')
        discovery_graph.assert_relationships(self.db,[prior])
        endpoints=[]
        for card in self.db.execute('SELECT * FROM card ORDER BY card_id'):
            endpoints.append({**{field:card[field] for field in FIELDS},'identity_blockers':[],
                              'image_ref':f'https://fixture.invalid/{card["language"]}.webp','image_sha256':'a'*64})
        r=dict(candidate_id=self.cid,endpoints=endpoints,status='awaiting_independent_artwork_reviews',
               relation_type='same_artwork',expected_pair_head='old-proposal',
               source_evidence_sha256=hashlib.sha256(b'fixture old source').hexdigest())
        r['cohort_snapshot_sha256']=digest(r);self.frozen=r
        self.a=self.review('first','2026-10-02T00:00:00Z');self.b=self.review('second','2026-10-02T00:01:00Z')

    def tearDown(self):self.db.close()

    def review(self,who,when):
        return dict(candidate_id=self.cid,source_snapshot_sha256=self.frozen['cohort_snapshot_sha256'],
                    reviewer=who,reviewed_at=when,decision='same_artwork',artwork={'outcome':'same','note':'Synthetic visual fixture.'},
                    finish={'outcome':'not_comparable','note':'Coordinate stock image only.'},
                    endpoint_coordinate_identity_checked=True,first_review_verdicts_visible=False,
                    physical_printing_verified=False,price_comparable=False,
                    image_evidence=[dict(side=c['language'],source_ref=c['image_ref'],image_sha256=c['image_sha256']) for c in self.frozen['endpoints']])

    def compile(self,a=None,b=None):
        return compile_reviews(self.db,{self.cid:self.frozen},{self.cid:a or self.a},{self.cid:b or self.b})

    def test_qualified_artwork_import_is_atomic_head_bound_and_retry_safe(self):
        rows=self.compile();self.assertEqual(discovery_graph.assert_relationships(self.db,rows),1)
        self.assertEqual(discovery_graph.assert_relationships(self.db,rows),0)
        edge=discovery_graph.card_neighborhood(self.db,self.ids[0])['relationships'][0]
        self.assertEqual(edge['review_status'],'verified');self.assertFalse(edge['price_comparable'])
        self.assertFalse(json.loads(edge['evidence_ref'])['physical_printing_verified'])
        with self.assertRaisesRegex(ValueError,'pair head drifted'):check_current(self.db,self.frozen)

    def test_compiled_verified_artwork_is_withheld_if_source_snapshot_later_changes(self):
        discovery_graph.assert_relationships(self.db,self.compile())
        self.db.execute("UPDATE card SET provenance='new-source' WHERE card_id=?",(self.ids[0],))
        view=discovery_graph.card_neighborhood(self.db,self.ids[1])
        self.assertEqual(view['relationships'],[])
        self.assertEqual(view['held_relationships'][0]['endpoint_identity_blockers'],
                         {self.ids[0]:['reviewed_endpoint_snapshot_drift']})
        from pokemon_index import number_graph
        self.assertNotEqual(number_graph.explain_number_pair(self.db,*self.ids)['evidence_status'],'reviewed_relationship')

    def test_endpoint_mutation_and_pair_head_replacement_require_new_review(self):
        self.db.execute('UPDATE card SET name=? WHERE card_id=?',('Changed',self.ids[0]))
        with self.assertRaisesRegex(ValueError,'endpoint identity drifted'):self.compile()
        self.db.execute('UPDATE card SET name=? WHERE card_id=?',('Name',self.ids[0]))
        self.db.execute("UPDATE card_relationship_assertion SET evidence_ref='changed'")
        with self.assertRaisesRegex(ValueError,'pair head drifted'):self.compile()

    def test_duplicate_reviewer_visibility_and_image_substitution_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'distinct reviewers'):self.compile(b={**self.b,'reviewer':'FIRST'})
        with self.assertRaisesRegex(ValueError,'verdict separation'):self.compile(b={**self.b,'first_review_verdicts_visible':True})
        substituted=json.loads(json.dumps(self.b));substituted['image_evidence'][0]['image_sha256']='b'*64
        with self.assertRaisesRegex(ValueError,'image evidence drifted'):self.compile(b=substituted)
        with self.assertRaisesRegex(ValueError,'cannot verify finish'):self.compile(b={**self.b,'finish':{'outcome':'same','note':'Claim'}})

    def test_held_identity_cannot_be_promoted_and_forged_cohort_is_detected(self):
        self.frozen['status']='identity_hold';self.frozen['cohort_snapshot_sha256']=digest({k:v for k,v in self.frozen.items() if k!='cohort_snapshot_sha256'})
        with self.assertRaisesRegex(ValueError,'held endpoint'):self.compile()
        self.frozen['status']='awaiting_independent_artwork_reviews'
        with self.assertRaisesRegex(ValueError,'snapshot hash differs'):self.compile()


if __name__=='__main__':unittest.main()

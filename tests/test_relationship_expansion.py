import unittest

from scripts.adjudicate_relationship_expansion import adjudicate
from tests import test_relationship_identity_review as review_fixtures


class RelationshipExpansionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=review_fixtures.RelationshipIdentityReviewTests();self.fixture.setUp()
        self.assets=[dict(candidate_id=self.fixture.cid,side=c['language'],status='source_hash_verified',
                          source_ref=c['image_ref'],image_sha256=c['image_sha256']) for c in self.fixture.frozen['endpoints']]

    def tearDown(self):self.fixture.tearDown()

    def result(self,second=None,assets=None):
        f=self.fixture
        return adjudicate(f.db,{f.cid:f.frozen},{f.cid:f.a},{f.cid:second or f.b},assets or self.assets)

    def test_disagreement_and_uncertainty_preserve_hold_without_graph_writes(self):
        for decision in ('uncertain','different_artwork'):
            rows,holds=self.result(second={**self.fixture.b,'decision':decision})
            self.assertEqual(rows,[]);self.assertEqual(len(holds),1)
            self.assertEqual(holds[0]['reason'],'independent_review_disagreement')
        self.assertEqual(self.fixture.db.execute('SELECT COUNT(*) FROM card_relationship_assertion').fetchone()[0],1)

    def test_missing_membership_and_source_substitution_cannot_create_edge(self):
        f=self.fixture
        with self.assertRaisesRegex(ValueError,'every frozen candidate'):
            adjudicate(f.db,{f.cid:f.frozen},{f.cid:f.a},{},self.assets)
        replaced=[dict(r) for r in self.assets];replaced[0]['image_sha256']='b'*64
        rows,holds=self.result(assets=replaced)
        self.assertEqual(rows,[]);self.assertEqual(holds[0]['reason'],'source_asset_hash_or_identity_mismatch')

    def test_positive_subset_uses_existing_current_head_and_copy_permission_guards(self):
        rows,holds=self.result();self.assertEqual(len(rows),1);self.assertEqual(holds,[])
        self.assertEqual(rows[0]['review_status'],'verified')
        import json
        evidence=json.loads(rows[0]['evidence_ref']);self.assertEqual(evidence['finish']['outcome'],'not_comparable')
        self.assertFalse(evidence['physical_printing_verified']);self.assertFalse(evidence['price_comparable'])


if __name__=='__main__':unittest.main()

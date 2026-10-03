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

    def test_exact_record_binding_separates_same_language_images(self):
        from scripts.compile_relationship_identity_reviews import bind_source_images
        import copy
        endpoints=copy.deepcopy(self.fixture.frozen['endpoints'])
        for c in endpoints:c['language']='en'
        images=[dict(side='en',card_id=c['card_id'],source_ref=c['image_ref'],image_sha256=c['image_sha256']) for c in endpoints]
        self.assertEqual(bind_source_images(list(reversed(images)),endpoints),images)
        for mutate in [lambda x:x[0].update(card_id=x[1]['card_id']),lambda x:x[0].update(image_sha256='f'*64),lambda x:[r.pop('card_id') for r in x]]:
            changed=copy.deepcopy(images);mutate(changed)
            with self.assertRaises(ValueError):bind_source_images(changed,endpoints)

    def test_opaque_review_labels_compile_to_canonical_endpoint_event_id(self):
        import copy
        from scripts.freeze_relationship_identity_review import digest
        from pokemon_index import discovery_graph
        f=self.fixture;label='blind-pair-1';frozen=copy.deepcopy(f.frozen);frozen['candidate_id']=label;frozen.pop('cohort_snapshot_sha256');frozen['cohort_snapshot_sha256']=digest(frozen)
        a=copy.deepcopy(f.a);b=copy.deepcopy(f.b)
        for r in [a,b]:r.update(candidate_id=label,cohort_snapshot_sha256=frozen['cohort_snapshot_sha256'])
        assets=[dict(x,candidate_id=label) for x in self.assets]
        events,holds=adjudicate(f.db,{label:frozen},{label:a},{label:b},assets)
        self.assertFalse(holds);self.assertIn(f.cid,events[0]['assertion_id']);discovery_graph.assert_relationships(f.db,events)


if __name__=='__main__':unittest.main()

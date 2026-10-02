import copy
import json
import unittest
from pokemon_index import card_comparison,discovery_graph
from scripts import adjudicate_artwork_controls
from scripts.freeze_relationship_identity_review import check_current,digest
from tests import test_relationship_identity_review as fixtures

class ArtworkControlTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RelationshipIdentityReviewTests();self.fixture.setUp()
        self.db=self.fixture.db;self.ids=self.fixture.ids;self.cid=self.fixture.cid
        self.db.execute('DELETE FROM card_relationship_assertion');self.db.commit()
        self.frozen=copy.deepcopy(self.fixture.frozen)
        self.frozen.update(pair_scope='new_source_qualified_control',expected_pair_head=None,source_evidence_sha256=None)
        self.frozen['cohort_snapshot_sha256']=digest({k:v for k,v in self.frozen.items() if k!='cohort_snapshot_sha256'})
        self.fixture.frozen=self.frozen
        self.a=self.fixture.review('first','2026-10-02T00:00:00Z');self.b=self.fixture.review('second','2026-10-02T00:01:00Z')
        for r,family in [(self.a,'openai'),(self.b,'google')]:
            r.update(cohort_snapshot_sha256=self.frozen['cohort_snapshot_sha256'],status='reviewed',model_family=family,
                decision='different_artwork',artwork=dict(outcome='different',note='Synthetic distinct scenes fixture.'))
        self.assets=[dict(candidate_id=self.cid,side=c['language'],status='source_hash_verified',source_ref=c['image_ref'],image_sha256=c['image_sha256']) for c in self.frozen['endpoints']]
        self.payload=dict(left=dict(card_id=self.ids[0]),right=dict(card_id=self.ids[1]))

    def tearDown(self):self.fixture.tearDown()
    def adjudicate(self,a=None,b=None,assets=None):
        return adjudicate_artwork_controls.adjudicate(self.db,{self.cid:self.frozen},{self.cid:a or self.a},{self.cid:b or self.b},assets or self.assets)
    def test_qualified_difference_is_scoped_idempotent_and_never_commerce_approval(self):
        rows,result=self.adjudicate();self.assertEqual(result[0]['status'],'qualified_artwork_difference')
        self.assertEqual(discovery_graph.assert_relationships(self.db,rows),1)
        self.assertEqual(discovery_graph.assert_relationships(self.db,rows),0)
        view=card_comparison.compare(self.db,self.payload)
        self.assertEqual(view['artwork']['status'],'reviewed_endpoint_differences_only')
        self.assertEqual(len(view['artwork']['reviewed_difference_links']),1)
        self.assertEqual(view['artwork']['reviewed_links'],[])
        self.assertEqual(view['artwork']['uncovered_record_ids'],[])
        self.assertFalse(view['price_comparable']);self.assertFalse(view['same_physical_printing_established'])
    def test_missing_or_withdrawn_link_is_not_a_difference_fact(self):
        self.assertEqual(card_comparison.compare(self.db,self.payload)['artwork']['status'],'unestablished')
        row=dict(left_card_id=self.ids[0],right_card_id=self.ids[1],relation_type='same_artwork',review_status='rejected',reviewer='curator',asserted_by='fixture',evidence_ref=json.dumps(dict(reason='withdrawn')),rights_reference='fixture')
        discovery_graph.assert_relationships(self.db,[row])
        self.assertEqual(card_comparison.compare(self.db,self.payload)['artwork']['reviewed_difference_links'],[])
    def test_source_drift_withholds_difference_without_erasing_history(self):
        rows,_=self.adjudicate();discovery_graph.assert_relationships(self.db,rows)
        self.db.execute("UPDATE card SET provenance='changed' WHERE card_id=?",(self.ids[0],))
        view=card_comparison.compare(self.db,self.payload)
        self.assertEqual(view['artwork']['reviewed_difference_links'],[])
        self.assertEqual(view['artwork']['status'],'unestablished')
        self.assertIn('reviewed_endpoint_snapshot_drift',view['artwork']['other_pair_states'][0]['endpoint_identity_blockers'][self.ids[0]])
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],1)
    def test_approval_never_transfers_to_a_sibling_variant(self):
        from pokemon_index import core
        rows,_=self.adjudicate();discovery_graph.assert_relationships(self.db,rows)
        card=dict(self.db.execute('SELECT * FROM card WHERE card_id=?',(self.ids[1],)).fetchone());card.update(variant='reverse',match_eligible=True,display_allowed=False)
        core.import_cards(self.db,[card]);sibling=self.ids[1].replace(':normal',':reverse')
        result=card_comparison.compare(self.db,dict(left=dict(card_id=self.ids[0]),right=dict(card_id=sibling)))
        self.assertEqual(result['artwork']['reviewed_difference_links'],[])
    def test_uncertain_identity_model_failure_disagreement_and_asset_gap_are_holds(self):
        cases=[(dict(self.b,endpoint_coordinate_identity_checked=False),'printed_coordinate_identity_unconfirmed'),
               (dict(self.b,status='review_failed'),'model_review_incomplete'),
               (dict(self.b,decision='same_artwork'),'review_disagreement')]
        for b,reason in cases:
            rows,results=self.adjudicate(b=b);self.assertEqual(rows,[]);self.assertEqual(results[0]['reason'],reason)
        rows,results=self.adjudicate(assets=[self.assets[0]])
        self.assertEqual(rows,[]);self.assertEqual(results[0]['reason'],'source_asset_unavailable')
    def test_image_substitution_is_a_hold(self):
        assets=copy.deepcopy(self.assets);assets[0]['image_sha256']='b'*64
        rows,result=self.adjudicate(assets=assets);self.assertEqual(rows,[]);self.assertEqual(result[0]['reason'],'source_asset_substitution')
    def test_no_head_guard_rejects_graph_changed_after_freeze(self):
        check_current(self.db,self.frozen)
        discovery_graph.assert_relationships(self.db,[dict(assertion_id='new',left_card_id=self.ids[0],right_card_id=self.ids[1],relation_type='same_artwork',review_status='proposed',evidence_ref='{}',rights_reference='fixture',asserted_by='fixture')])
        with self.assertRaisesRegex(ValueError,'pair head drifted'):self.adjudicate()
    def test_positive_control_rechecks_without_creating_another_approval(self):
        self.frozen['pair_scope']='existing_pair_control';self.frozen['cohort_snapshot_sha256']=digest({k:v for k,v in self.frozen.items() if k!='cohort_snapshot_sha256'})
        # An existing control must keep its head; construct that synthetic head.
        discovery_graph.assert_relationships(self.db,[dict(assertion_id='old',left_card_id=self.ids[0],right_card_id=self.ids[1],relation_type='same_artwork',review_status='proposed',evidence_ref='{}',rights_reference='fixture',asserted_by='fixture')])
        import hashlib
        self.frozen.update(expected_pair_head='old',source_evidence_sha256=hashlib.sha256(b'{}').hexdigest())
        self.frozen['cohort_snapshot_sha256']=digest({k:v for k,v in self.frozen.items() if k!='cohort_snapshot_sha256'})
        for r in (self.a,self.b):r.update(cohort_snapshot_sha256=self.frozen['cohort_snapshot_sha256'],decision='same_artwork',artwork=dict(outcome='same',note='Synthetic same scene.'))
        events,results=self.adjudicate();self.assertEqual(events,[]);self.assertEqual(results[0]['status'],'positive_control_agreement')
    def test_import_rejects_missing_snapshot_single_review_or_physical_overclaim(self):
        rows,_=self.adjudicate()
        for mutate in ['snapshot','review','overclaim']:
            row=copy.deepcopy(rows[0]);e=json.loads(row['evidence_ref'])
            if mutate=='snapshot':del e['cards'][0]['identity_snapshot']
            if mutate=='review':e['second_review']['reviewer']=e['first_review']['reviewer']
            if mutate=='overclaim':e['price_comparable']=True
            row['evidence_ref']=json.dumps(e)
            with self.assertRaises(ValueError):discovery_graph.assert_relationships(self.db,[row])
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0],0)
    def test_latest_pair_state_supersedes_difference(self):
        rows,_=self.adjudicate();discovery_graph.assert_relationships(self.db,rows)
        row=copy.deepcopy(rows[0]);row.update(assertion_id='replacement',asserted_by='fixture',review_status='verified')
        e=json.loads(row['evidence_ref']);e.pop('review_kind');e['review_event_id']='replacement';e['artwork']['outcome']='same'
        for r in [e['first_review'],e['second_review']]:r['decision']='same_artwork'
        row['evidence_ref']=json.dumps(e);discovery_graph.assert_relationships(self.db,[row])
        view=card_comparison.compare(self.db,self.payload)
        self.assertEqual(view['artwork']['reviewed_difference_links'],[]);self.assertEqual(len(view['artwork']['reviewed_links']),1)

if __name__=='__main__':unittest.main()

"""Synthetic guard tests, not marketplace accuracy measurements."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from pokemon_index import core, card_comparison, collector_discovery, collector_journey
from pokemon_index.cli import create_server


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)/'catalog.sqlite3'
        self.db = core.connect(self.path)
        core.init_db(self.db)
        for lang, release, number, variant in [('ja','SM1M','018/060','normal'),
                ('ja','SM1M','018/060','holo'), ('en','SM1','050/149','normal'),
                ('en','SM1','050/149','reverse'), ('en','OTHER','050/149','normal')]:
            core.import_cards(self.db, [dict(language=lang, set_code=release, collector_number=number,
                variant=variant, name='Synthetic Lanturn', provenance='fixture', rights_reference='fixture',
                match_eligible=True)])
        self.left = 'ja:SM1M:018/060:normal'
        self.right = 'en:SM1:050/149:normal'
        self.payload = dict(left=dict(card_id=self.left), right=dict(card_id=self.right))
        self.db.execute('INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
                        ('en','SM1','Sun & Moon',None,149,'fixture','fixture',0))
        self.db.execute('INSERT INTO catalog_set_localized VALUES (?,?,?,?,?,?,?,?)',
                        ('ja','SM1M','Synthetic release',None,60,'fixture','fixture',0))
        self.db.commit()

    def tearDown(self):
        self.db.close(); self.tmp.cleanup()

    def edge(self, status='verified', event='fixture:1', kind='same_artwork'):
        # Seed guard states directly; this tests readers, not approval imports.
        snapshots = [dict(self.db.execute('SELECT * FROM card WHERE card_id=?',(cid,)).fetchone())
                     for cid in (self.left, self.right)]
        evidence = dict(cards=[dict(card_id=c['card_id'], identity_snapshot=c,
                                   source_ref='fixture:'+c['card_id']) for c in snapshots],
                        artwork=dict(outcome='same'), rationale='Synthetic reader guard')
        a,b=sorted((self.left,self.right))
        self.db.execute('INSERT INTO card_relationship_assertion VALUES (?,?,?,?,?,?,?,?,?,?)',
            (event,a,b,kind,status,json.dumps(evidence),'fixture','fixture','fixture','2026-10-02T00:00:00+00:00'))
        self.db.commit()

    def test_numbers_are_current_scoped_coordinates_not_price_or_quantity(self):
        result=card_comparison.compare(self.db,self.payload)
        self.assertEqual(result['numbering']['number_alignment'],'different_or_unparsed')
        self.assertFalse(result['numbering']['print_run_quantity_established'])
        for key in ['price_comparable','price_series_merge_allowed','physical_finish_verified',
                    'copy_condition_verified','purchase_ready','public_display_allowed']:
            self.assertFalse(result[key])
        self.assertEqual(result['prices'],[])
        self.db.execute('UPDATE card SET collector_number=? WHERE card_id=?',('050/149',self.left))
        result=card_comparison.compare(self.db,self.payload)
        self.assertEqual(result['numbering']['number_alignment'],'same_number_different_scope')

    def test_review_is_exact_endpoint_only_and_preserves_sibling_uncertainty(self):
        self.edge()
        result=card_comparison.compare(self.db,dict(
            left=dict(language='ja',set_code='SM1M',collector_number='18/60'),
            right=dict(language='en',set_code='SM1',collector_number='50/149')))
        self.assertEqual(len(result['artwork']['reviewed_links']),1)
        self.assertEqual(len(result['artwork']['uncovered_record_ids']),2)
        self.assertFalse(result['artwork']['all_coordinate_variants_verified'])
        specific=card_comparison.compare(self.db,dict(left=dict(card_id=self.left),
            right=dict(card_id='en:SM1:050/149:reverse')))
        self.assertEqual(specific['artwork']['status'],'unestablished')

    def test_rejection_supersedes_verification_and_proposals_do_not_approve(self):
        self.edge(); self.edge('rejected','fixture:2')
        result=card_comparison.compare(self.db,self.payload)
        self.assertEqual(result['artwork']['reviewed_links'],[])
        self.assertEqual(result['artwork']['other_pair_states'][0]['review_status'],'rejected')
        self.edge('proposed','fixture:3')
        self.assertEqual(card_comparison.compare(self.db,self.payload)['artwork']['reviewed_links'],[])

    def test_localization_type_is_not_stock_artwork_approval(self):
        self.edge(kind='localization_counterpart')
        self.assertEqual(card_comparison.compare(self.db,self.payload)['artwork']['reviewed_links'],[])

    def test_drift_and_disabled_endpoint_fail_closed(self):
        self.edge()
        self.db.execute('UPDATE card SET name=? WHERE card_id=?',('Changed name',self.left))
        result=card_comparison.compare(self.db,self.payload)
        self.assertEqual(result['artwork']['reviewed_links'],[])
        self.assertIn('reviewed_endpoint_snapshot_drift',
            result['artwork']['other_pair_states'][0]['endpoint_identity_blockers'][self.left])
        self.db.execute('UPDATE card SET match_eligible=0 WHERE card_id=?',(self.right,))
        result=card_comparison.compare(self.db,self.payload)
        self.assertIn('match_disabled_identity',
            result['artwork']['other_pair_states'][0]['endpoint_identity_blockers'][self.right])

    def test_injected_evidence_incomplete_scopes_and_duplicate_ids_rejected(self):
        for payload in [dict(self.payload,price_comparable=True),
                dict(left=dict(self.payload['left'],verified=True),right=self.payload['right']),
                dict(left=dict(language='ja',collector_number='18/60'),right=self.payload['right']),
                dict(left=self.payload['left'],right=self.payload['left'])]:
            with self.assertRaises(ValueError):card_comparison.compare(self.db,payload)

    def test_missing_release_is_not_inferred_from_artwork(self):
        self.edge()
        result=card_comparison.from_question(self.db,
            'Is Japanese SM1M 18/60 the same picture as English 50/149?')
        self.assertEqual(result['status'],'scope_confirmation_needed')
        self.assertEqual(result['unresolved_sides'],['right'])
        self.assertIsNone(result['numbering'])
        self.assertNotIn('set_code',result['right']['requested'])
        self.assertEqual(len(result['artwork']['reviewed_links']),1)

    def test_explicit_wrong_release_is_preserved_and_does_not_borrow_edge(self):
        self.edge()
        result=card_comparison.from_question(self.db,
            'Compare Japanese SM1M 18/60 and English SM999 50/149 same picture.')
        self.assertEqual(result['right']['requested']['set_code'],'SM999')
        self.assertEqual(result['right']['status'],'not_found')
        self.assertEqual(result['artwork']['reviewed_links'],[])

    def test_market_question_keeps_partial_catalog_facts_but_no_prices(self):
        result=collector_discovery.execute(self.db,
            'Compare Japanese SM1M 18/60 and English Sun & Moon 50/149. Which is cheaper today?')
        self.assertEqual(result['task'],'two_card_comparison')
        self.assertIsNotNone(result['comparison']['numbering'])
        self.assertEqual(result['prices'],[])
        self.assertFalse(result['complete_answer_established'])

    def test_single_card_and_three_card_questions_do_not_enter_comparison(self):
        for q in ['Compare Japanese SM1M 18/60',
                  'Compare Japanese SM1M 18/60 English SM1 50/149 English SM1 51/149']:
            self.assertIsNone(card_comparison.from_question(self.db,q))

    def test_bounded_ambiguous_release_does_not_use_truncated_candidates(self):
        self.edge()
        for index in range(33):
            core.import_cards(self.db,[dict(language='en',set_code='EXTRA'+str(index),collector_number='050/149',
                variant='normal',name='Synthetic',provenance='fixture',rights_reference='fixture',match_eligible=True)])
        result=card_comparison.from_question(self.db,'Same picture Japanese SM1M 18/60 and English 50/149?')
        self.assertTrue(result['right']['records_truncated'])
        self.assertEqual(result['right']['status'],'refinement_needed')
        self.assertEqual(result['artwork']['reviewed_links'],[])

    def test_comparison_cannot_select_purchase_target_in_journey(self):
        q='Compare Japanese SM1M 18/60 and English SM1 50/149'
        result=collector_journey.replay(self.db,dict(turns=[dict(type='ask',question=q)]))
        self.assertFalse(result['selection_allowed']);self.assertIsNone(result['target_intent'])
        self.assertEqual(result['discovery']['task'],'two_card_comparison')
        with self.assertRaises(ValueError):
            collector_journey.replay(self.db,dict(turns=[dict(type='ask',question=q),dict(type='select',card_id=self.left)]))

    def test_http_internal_only_and_read_only(self):
        self.db.commit(); before=self.path.read_bytes()
        for internal in [False,True]:
            server=create_server(str(self.path),'127.0.0.1',0,internal)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                request=Request('http://127.0.0.1:'+str(server.server_address[1])+'/card-comparison',
                    data=json.dumps(self.payload).encode(),headers={'Content-Type':'application/json'})
                if internal:
                    with urlopen(request) as response:
                        self.assertEqual(json.load(response)['schema'],card_comparison.SCHEMA)
                else:
                    with self.assertRaises(HTTPError) as error:urlopen(request)
                    self.assertEqual(error.exception.code,404)
            finally:server.shutdown();thread.join();server.server_close()
        self.assertEqual(self.path.read_bytes(),before)

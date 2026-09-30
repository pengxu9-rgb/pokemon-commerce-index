import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from pokemon_index import core,collector_discovery,supported_catalog
from scripts.build_catalog_snapshot import build

ROOT=Path(__file__).resolve().parents[1]


class EligibilityTests(unittest.TestCase):
    def test_omitted_eligibility_and_missing_variant_do_not_enable_matching(self):
        with closing(core.connect(':memory:')) as db:
            core.init_db(db)
            seed=dict(language='ja',set_code='FIX',collector_number='001/100',variant='normal',
                      name='Synthetic',provenance='fixture',rights_reference='fixture')
            core.import_cards(db,[seed])
            self.assertEqual(db.execute('SELECT match_eligible FROM card').fetchone()[0],0)
            core.import_cards(db,[dict(seed,match_eligible=True)])
            self.assertEqual(db.execute('SELECT match_eligible FROM card').fetchone()[0],1)
            core.import_cards(db,[seed])
            self.assertEqual(db.execute('SELECT match_eligible FROM card').fetchone()[0],0)
            with self.assertRaisesRegex(ValueError,'explicit boolean'):
                core.import_cards(db,[dict(seed,match_eligible='false')])
            missing=dict(seed,match_eligible=True);missing.pop('variant')
            core.import_cards(db,[missing])
            self.assertEqual(db.execute("SELECT match_eligible FROM card WHERE variant='standard'").fetchone()[0],0)

    def test_old_default_migrates_without_losing_existing_foreign_keys(self):
        with closing(core.connect(':memory:')) as db:
            sql=(ROOT/'pokemon_index/schema.sql').read_text().replace(
                'match_eligible INTEGER NOT NULL DEFAULT 0','match_eligible INTEGER NOT NULL DEFAULT 1')
            db.executescript(sql)
            db.execute("INSERT INTO card(card_id,language,set_code,collector_number,name,provenance,rights_reference,display_allowed) VALUES ('old','ja','FIX','001/100','Old','fixture','fixture',0)")
            db.execute("INSERT INTO card_facet VALUES ('old','dex_id','25','fixture','fixture')")
            db.commit();core.init_db(db)
            self.assertEqual(db.execute('SELECT match_eligible FROM card WHERE card_id=\'old\'').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM card_facet').fetchone()[0],1)
            self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
            db.execute("INSERT INTO card(card_id,language,set_code,collector_number,name,provenance,rights_reference,display_allowed) VALUES ('new','ja','FIX','002/100','New','fixture','fixture',0)")
            self.assertEqual(db.execute('SELECT match_eligible FROM card WHERE card_id=\'new\'').fetchone()[0],0)
            self.assertEqual(db.execute('PRAGMA foreign_keys').fetchone()[0],1)


class SupportedCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.path=Path(cls.temp.name)/'catalog.sqlite3'
        cls.build_result=build(ROOT/'catalog-build-manifest-discovery-v1.json',cls.path)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def setUp(self):self.db=core.connect(self.path,readonly=True)
    def tearDown(self):self.db.close()

    def writable_copy(self):
        db=core.connect(':memory:');self.db.backup(db);return db

    def test_manifest_deploys_alias_evidence_without_verifying_artwork(self):
        status=supported_catalog.status(self.db)
        self.assertEqual((status['current_supported_targets'],status['bilingual_alias_revisions'],
                          status['concept_review_events'],status['automatic_offer_join_ready']),
                         (100,122,460,0))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM card_relationship_assertion WHERE review_status='verified'").fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT name FROM catalog_set_localized WHERE language='ja' AND set_code='SV4A'").fetchone()[0],'シャイニートレジャーex')

    def test_stale_identity_reference_and_release_each_invalidate_support(self):
        cid='ja:SV4A:347/190:holo'
        for sql in ["UPDATE card SET name='Wrong' WHERE card_id=?",
                    "UPDATE card_reference SET provenance='Wrong' WHERE set_code='SV4A' AND collector_number='347/190' AND ? IS NOT NULL",
                    "UPDATE catalog_set_localized SET name='Wrong' WHERE language='ja' AND set_code='SV4A' AND ? IS NOT NULL"]:
            with self.subTest(sql=sql),closing(self.writable_copy()) as db:
                self.assertEqual(supported_catalog.support_for_card(db,cid)['status'],'supported_for_internal_review')
                db.execute(sql,(cid,))
                self.assertEqual(supported_catalog.support_for_card(db,cid)['status'],'stale_support_evidence')

    def test_source_reimport_keeps_official_release_and_rarity_overlay(self):
        with closing(self.writable_copy()) as db:
            seed=next(json.loads(l) for l in (ROOT/'catalog/ja-all-sets.jsonl').read_text().splitlines() if json.loads(l)['set_code'].upper()=='SV4A')
            core.import_sets(db,[seed])
            self.assertEqual(db.execute("SELECT name FROM catalog_set_localized WHERE set_code='SV4A'").fetchone()[0],'シャイニートレジャーex')
            with self.assertRaisesRegex(ValueError,'differs from its official overlay'):
                core.import_sets(db,[dict(seed,provenance='unreviewed changed source')])

    def test_positive_record_cannot_claim_automatic_offer_approval(self):
        row=json.loads((ROOT/'catalog/supported-discovery-v1/supported-cards.jsonl').read_text().splitlines()[0])
        row['automatic_offer_join_allowed']=True
        with closing(self.writable_copy()) as db,self.assertRaisesRegex(ValueError,'cannot authorize'):
            supported_catalog.import_supported(db,[row])

    def test_family_branching_paradox_and_cameo_limits(self):
        result=collector_discovery.execute(self.db,'Ralts family checklist including Iron Valiant and artwork cameos')
        self.assertEqual(result['task'],'family_checklist')
        self.assertEqual({m['dex_id'] for m in result['family']['members']},{280,281,282,475})
        self.assertIn('artwork_cameos',result['unsupported_requested_dimensions'])
        self.assertIn('paradox_relationships',result['unsupported_requested_dimensions'])
        self.assertFalse(result['coverage']['global_printing_completeness_established'])

    def test_language_pagination_and_unknown_dates_remain_explicit(self):
        page=collector_discovery.execute(self.db,'Eevee evolution family in English',limit=3)
        later=collector_discovery.execute(self.db,'Eevee evolution family in English',limit=3,offset=3)
        self.assertEqual(page['languages'],['en']);self.assertTrue(page['coverage']['has_more'])
        self.assertTrue(all(c['language']=='en' for c in page['cards']))
        self.assertFalse({c['card_id'] for c in page['cards']} & {c['card_id'] for c in later['cards']})
        self.assertEqual(page['coverage']['matched_catalog_records'],later['coverage']['matched_catalog_records'])

    def test_exact_number_alias_and_conflicting_name(self):
        good=collector_discovery.execute(self.db,'ミュウex シャイニートレジャーex 347/190')
        self.assertEqual([c['card_id'] for c in good['cards']],['ja:SV4A:347/190:holo'])
        self.assertEqual(good['cards'][0]['rarity'],'SAR')
        wrong=collector_discovery.execute(self.db,'Pikachu SV4A 347/190 Japanese')
        self.assertEqual(wrong['cards'],[])
        ambiguous=collector_discovery.execute(self.db,'Japanese 347/190')
        self.assertEqual(ambiguous['task'],'need_release_scope')
        with closing(self.writable_copy()) as db:
            unit,method=core.resolve(db,{'title':'ミュウex シャイニートレジャーex 347/190'})
        self.assertEqual(method,'exact');self.assertTrue(unit.startswith('ja:SV4A:347/190:holo|'))

    def test_requested_finish_is_not_silently_replaced(self):
        wrong=collector_discovery.execute(self.db,'Japanese SV4A 347/190 master ball')
        self.assertEqual(wrong['cards'],[])
        self.assertEqual(wrong['status'],'no_match')
        for question in ['Japanese SV4A 347/190 first edition',
                         'Japanese SV4A 347/190 PSA 10']:
            result=collector_discovery.execute(self.db,question)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(result['cards'],[])

    def test_explicit_language_is_not_replaced_by_coordinates(self):
        result=collector_discovery.execute(self.db,'Show English versions of ja:SV4A:347/190:holo')
        self.assertEqual(result['cards'],[])
        self.assertEqual(result['status'],'no_match')
        unsupported=collector_discovery.execute(self.db,'Show Korean Pikachu cards')
        self.assertEqual(unsupported['task'],'unsupported_language')
        self.assertEqual(unsupported['cards'],[])

    def test_cross_region_artwork_lead_never_claims_counterpart_or_price(self):
        result=collector_discovery.execute(self.db,'Which English counterpart matches ja:M-P:046/M-P:normal?')
        self.assertEqual(result['status'],'relationship_review_needed')
        self.assertEqual(result['verified_links'],[]);self.assertTrue(result['proposed_artwork_leads'])
        self.assertFalse(result['price_comparable']);self.assertEqual(result['prices'],[])

    def test_market_and_unsupported_tasks_do_not_execute_catalog_as_an_answer(self):
        for question,task in [('Cheapest Pikachu card','market_evidence_needed'),
                              ('Build a Pokemon deck','gameplay_evidence_needed'),
                              ('Show YuGiOh cards','unsupported_game')]:
            result=collector_discovery.execute(self.db,question)
            self.assertEqual(result['task'],task);self.assertEqual(result['cards'],[])
            self.assertEqual(result['prices'],[])

    def test_import_family_cycle_is_rejected(self):
        row=json.loads((ROOT/'catalog/supported-discovery-v1/families.jsonl').read_text().splitlines()[0])
        row=copy.deepcopy(row);row['members'][1]['parent_dex_id']=row['members'][1]['dex_id']
        with closing(self.writable_copy()) as db,self.assertRaisesRegex(ValueError,'cycle'):
            supported_catalog.import_families(db,[row])

if __name__=='__main__':unittest.main()

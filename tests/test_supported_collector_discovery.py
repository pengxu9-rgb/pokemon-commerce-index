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

    def test_artist_credits_support_names_without_inventing_owned_inventory(self):
        result=collector_discovery.execute(self.db,'Yuka Morii cards: check off my collection')
        self.assertEqual(result['task'],'artist_cards');self.assertTrue(result['cards'])
        self.assertIn('owned_inventory',result['unfulfilled_constraints'])
        self.assertIn('owned-card list',result['next_question'])
        self.assertFalse(result['complete_answer_established'])
        japanese=collector_discovery.execute(self.db,'イラストレーターのtakeさんのカード')
        self.assertEqual(japanese['task'],'artist_cards');self.assertEqual(japanese['illustrator'],'take')
        generic=collector_discovery.execute(self.db,'Can you take a look at Pikachu cards?')
        self.assertEqual(generic['task'],'character_cards')

    def test_species_checklist_does_not_expand_into_evolutions(self):
        for q in ['Mew chronological checklist','Pikachu checklist in release order']:
            result=collector_discovery.execute(self.db,q)
            self.assertEqual(result['task'],'character_cards')
            self.assertNotIn('family_id',result)
        family=collector_discovery.execute(self.db,'Pikachu evolution family checklist')
        self.assertEqual(family['task'],'family_checklist')

    def test_artwork_appearances_and_exclusivity_require_specific_evidence(self):
        for q in ["Farfetch'd appears in Pokémon Trader art; what other cameos are there?",
                  'レッドが映っているピカチュウのカードも知りたい']:
            result=collector_discovery.execute(self.db,q)
            self.assertEqual(result['task'],'artwork_evidence_needed')
            self.assertEqual(result['cards'],[]);self.assertTrue(result['required_evidence'])
        result=collector_discovery.execute(self.db,'Japanese exclusive cards such as Pikachu Illustrator')
        self.assertEqual(result['task'],'regional_evidence_needed')
        self.assertEqual(result['cards'],[])

    def test_collection_edition_scope_can_return_artist_partial_without_copy_claim(self):
        result=collector_discovery.execute(self.db,'All English Yuka Morii and JP exclusive cards, base, reverse holos, 1st editions, unlimited and unique prints')
        expected=self.db.execute("SELECT COUNT(*) FROM card c WHERE c.language IN ('ja','en') AND EXISTS(SELECT 1 FROM card_facet f WHERE f.card_id=c.card_id AND f.facet_type='illustrator' AND f.value='Yuka Morii')").fetchone()[0]
        self.assertEqual(result['task'],'artist_cards')
        self.assertEqual(result['coverage']['matched_catalog_records'],expected)
        self.assertIn('edition_variants',result['unfulfilled_constraints'])
        self.assertIn('regional_exclusivity',result['unfulfilled_constraints'])
        self.assertFalse(result['coverage']['global_printing_completeness_established'])
        single=collector_discovery.execute(self.db,'Yuka Morii reverse holo cards')
        self.assertTrue(all(c['variant'].startswith('reverse') for c in single['cards']))

    def test_set_comparison_preserves_all_variants_and_language_scope(self):
        q='Japanese 151 cards: does every card have Pokeball and Masterball holo?'
        result=collector_discovery.execute(self.db,q)
        self.assertEqual(result['task'],'set_cards')
        self.assertTrue(all(c['set_code']=='SV2A' and c['language']=='ja' for c in result['cards']))
        count=self.db.execute("SELECT COUNT(*) FROM card WHERE set_code='SV2A' AND language='ja'").fetchone()[0]
        self.assertEqual(result['coverage']['matched_catalog_records'],count)
        self.assertEqual(sum(r['records'] for r in result['variant_summary']),count)
        self.assertIn('physical_variant_completeness',result['unfulfilled_constraints'])
        unknown=collector_discovery.execute(self.db,'151')
        self.assertNotEqual(unknown['task'],'set_cards')

    def test_price_indifference_is_not_a_request_for_market_data(self):
        result=collector_discovery.execute(self.db,'Every Mew including custom cards; price does not matter')
        self.assertEqual(result['task'],'collection_scope_needed')
        market=collector_discovery.execute(self.db,'Mew price does not matter, but which is cheapest?')
        self.assertEqual(market['task'],'market_evidence_needed')

    def test_numeric_release_title_cannot_be_inferred_from_card_number(self):
        for q in ['Japanese card 151/165','English card 151/165']:
            result=collector_discovery.execute(self.db,q)
            self.assertEqual(result['task'],'need_release_scope')
            self.assertEqual(result['cards'],[])
        scoped=collector_discovery.execute(self.db,'Japanese 151 cards 151/165')
        self.assertEqual(scoped['task'],'exact_coordinates')

    def test_shiny_pokemon_query_is_not_a_foil_or_single_release_filter(self):
        result=collector_discovery.execute(self.db,'List all shiny Pokemon for a dex, including Radiant and Shining cards from Hidden Fates and other sets')
        self.assertEqual(result['task'],'classification_evidence_needed')
        self.assertEqual(result['cards'],[])
        self.assertIn('source_bound_shiny_depiction_and_card_type_annotations',result['required_evidence'])

    def test_unsupported_product_and_unavailable_reference_do_not_select_a_species(self):
        for q,task in [('Is the Chinese Eevee figure collection official?','other_product_evidence_needed'),
                       ('Give me the exact master list Danny Phantump uses in this video','collection_scope_needed')]:
            result=collector_discovery.execute(self.db,q)
            self.assertEqual(result['task'],task);self.assertEqual(result['cards'],[])
        ordinary=collector_discovery.execute(self.db,'Help me figure out my Japanese Pikachu checklist')
        self.assertEqual(ordinary['task'],'character_cards')
        self.assertTrue(ordinary['cards'])

    def test_grader_form_question_and_sealed_contents_are_separate_from_cards(self):
        cases=[('PSAのアイテム検索でアルセウスURを入力しても出てきません','grading_policy_evidence_needed'),
               ('同じタイトルのスターターデッキは同じカードが入りますか？','sealed_contents_evidence_needed'),
               ('ポケカ公式のカードリストでサポートSRを検索する機能は？','official_search_evidence_needed')]
        for q,task in cases:
            result=collector_discovery.execute(self.db,q)
            self.assertEqual(result['task'],task);self.assertTrue(result['required_evidence'])

    def test_examples_and_future_languages_do_not_replace_current_collection_scope(self):
        result=collector_discovery.execute(self.db,'A full Yuka Morii list: my Japanese Aipom is missing from another catalog')
        self.assertEqual(result['languages'],['ja','en'])
        explicit=collector_discovery.execute(self.db,'Only Japanese Yuka Morii cards: my Japanese Aipom is missing')
        self.assertEqual(explicit['languages'],['ja'])
        future=collector_discovery.execute(self.db,'Gengar EN/JP cards, maybe KR in the future, compare my linked list')
        self.assertEqual(future['task'],'character_cards')
        self.assertIn('future_language_scope',future['unfulfilled_constraints'])
        self.assertIn('external_checklist',future['unfulfilled_constraints'])

    def test_source_market_request_blocks_without_treating_negated_slabs_as_a_target(self):
        result=collector_discovery.execute(self.db,'Kanako Eo: where can I find raw cards? I am not interested in graded slabs')
        self.assertEqual(result['task'],'market_evidence_needed')
        self.assertEqual(result['live_offers'],[])

    def test_release_star_difference_does_not_return_every_gengar_printing(self):
        result=collector_discovery.execute(self.db,'Perfect Order Gengar: one black star and one white; are these all versions?')
        self.assertEqual(result['task'],'release_variant_evidence_needed')
        self.assertEqual(result['cards'],[])

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

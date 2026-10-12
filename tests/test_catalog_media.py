"""Synthetic evidence tests; no real scan, reviewer or artwork is created."""
import copy,unittest
from pokemon_index import core,number_evidence,source_image_facts,catalog_media,collector_discovery,collector_recommendation
from pokemon_index.cli import source_scan_filter
from tests import test_number_evidence as number_fixtures


class CatalogMediaTests(unittest.TestCase):
    def setUp(self):
        number_fixtures.NumberEvidenceTests.setUp(self);self.addCleanup(self.db.close)
        self.db.execute("UPDATE card SET provenance=?",('tcgdex:'+('a'*40)+':data/test.ts:sha256:'+('b'*64),));self.db.commit()
        self.row['endpoint_snapshot']=number_evidence.snapshot(self.db,self.cid)
        self.row['identity_sha256']=number_evidence.supported_catalog.digest(self.row['endpoint_snapshot'])
        self.sign(self.row)

    sign=number_fixtures.NumberEvidenceTests.sign

    def fact(self):
        reading=dict(title_text_parts=['Cleffa'],title_symbols=[],title_furigana=None,observed_number_text='037',hp=None,hp_status='absent',notes='Synthetic test-only')
        reviews=[dict(actor=r['actor'],model_family=r['model_family'],model_version=None,reviewed_at=r['reviewed_at'],
            review_record_sha256=r['review_record_sha256'],source_ref=r['source_ref'],image_sha256=r['image_sha256'],
            prior_verdicts_visible=False,expected_catalog_context_visible=False,reading=reading)
            for r in self.row['review_groups'][0]['reviews']]
        row=dict(schema=source_image_facts.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=number_evidence.snapshot(self.db,self.cid),
            source_ref=self.row['source_ref'],image_sha256=self.row['image_sha256'],source_file_sha256='b'*64,pinned_source_hp=None,
            cohort_snapshot_sha256='f'*64,reviews=reviews,recorded_at='2026-10-02T00:01:00Z',**{k:False for k in source_image_facts.FALSE_CLAIMS})
        row['identity_sha256']=number_evidence.supported_catalog.digest(row['endpoint_snapshot']);row['event_id']=source_image_facts.event_id(row)
        return row

    def test_number_only_scan_preserves_observed_namespace_and_no_sibling_transfer(self):
        number_evidence.import_evidence(self.db,[self.row]);a=catalog_media.availability(self.db,self.cid)
        self.assertEqual(a['evidence_basis'],'number_reading');self.assertTrue(a['with_source_scans_eligible'])
        self.assertTrue(a['source_scan_event_id'].startswith('number-reading:'))
        self.assertFalse(a['physical_printing_verified']);self.assertFalse(a['display_allowed']);self.assertFalse(a['live_fetch_verified'])
        self.assertFalse(number_evidence.context(self.db,self.cid)['printed_denominator_observed'])
        self.assertEqual(catalog_media.availability(self.db,'en:SVP:037/225:normal')['status'],'missing_source_scan_evidence')

    def test_held_number_scan_is_not_eligible(self):
        row=copy.deepcopy(self.row);row['review_groups'][0]['reviews'][0]['observed_number_text']=None;row['status']='reading_hold';self.sign(row)
        number_evidence.import_evidence(self.db,[row])
        self.assertEqual(catalog_media.availability(self.db,self.cid)['status'],'held_source_scan_evidence')
        self.assertNotIn(self.cid,catalog_media.current_ids(self.db))

    def test_agreed_conflicting_number_is_held_and_not_boosted(self):
        row=copy.deepcopy(self.row)
        for reviewer in row['review_groups'][0]['reviews']:reviewer['observed_number_text']='038/225'
        row['status']='different_text_observed';self.sign(row);number_evidence.import_evidence(self.db,[row])
        a=catalog_media.availability(self.db,self.cid)
        self.assertEqual(a['status'],'held_source_scan_evidence');self.assertFalse(a['with_source_scans_eligible'])
        self.assertIn('source_number_coordinate_conflict',a['warnings'])
        self.assertNotIn(self.cid,catalog_media.current_ids(self.db))
        self.assertEqual(number_evidence.context(self.db,self.cid)['observed_number_texts'],['038/225'])

    def test_stale_primary_never_falls_through_to_new_current_number_record(self):
        source_image_facts.import_evidence(self.db,[self.fact()])
        self.db.execute("UPDATE card SET name='Cleffa updated' WHERE card_id=?",(self.cid,));self.db.commit()
        row=copy.deepcopy(self.row);row['endpoint_snapshot']=number_evidence.snapshot(self.db,self.cid)
        row['identity_sha256']=number_evidence.supported_catalog.digest(row['endpoint_snapshot'])
        for r in row['review_groups'][0]['reviews']:r['observed_name']='Cleffa updated'
        self.sign(row);number_evidence.import_evidence(self.db,[row])
        self.assertTrue(number_evidence.context(self.db,self.cid)['current_endpoint'])
        a=catalog_media.availability(self.db,self.cid)
        self.assertEqual((a['status'],a['evidence_basis']),('stale_source_scan_evidence','source_image_facts'))
        self.assertFalse(a['with_source_scans_eligible'])

    def test_filter_evaluates_full_pool_before_count_and_offset(self):
        number_evidence.import_evidence(self.db,[self.row])
        for number in ('001/225','038/225'):
            core.import_cards(self.db,[dict(language='en',set_code='SVP',collector_number=number,variant='normal',name='Cleffa',provenance='synthetic',rights_reference='synthetic',match_eligible=True)])
        second=copy.deepcopy(self.row);second['card_id']='en:SVP:038/225:normal';second['endpoint_snapshot']=number_evidence.snapshot(self.db,second['card_id'])
        second['identity_sha256']=number_evidence.supported_catalog.digest(second['endpoint_snapshot']);second['source_ref']='https://assets.tcgdex.net/en/sv/svp/038/high.webp';second['image_sha256']='e'*64
        for r in second['review_groups'][0]['reviews']:r.update(source_ref=second['source_ref'],image_sha256=second['image_sha256'],observed_number_text='038')
        self.sign(second);number_evidence.import_evidence(self.db,[second])
        r=core.catalog_search_internal(self.db,'Cleffa',with_source_scans=True,limit=1,offset=1)
        self.assertEqual((r['total_before_source_scan_filter'],r['total']),(4,2))
        self.assertEqual(r['cards'][0]['card_id'],second['card_id'])
        counts=catalog_media.status(self.db)
        self.assertEqual(sum(counts['by_status'].values()),4)
        self.assertEqual(counts['current_source_scan_subjects'],2)

    def test_generic_scan_tiebreak_preserves_stronger_relevance_and_hard_scope(self):
        number_evidence.import_evidence(self.db,[self.row]);normal='en:SVP:037/225:normal'
        for cid in (normal,self.cid):self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(cid,'dex_id','35','synthetic','synthetic'))
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(normal,'illustrator','Synthetic Artist','synthetic','synthetic'));self.db.commit()
        q='help me find some Cleffa cards';self.assertTrue(collector_recommendation.is_goal(q))
        out=collector_recommendation.recommend(self.db,q,dict(preferred_dex_ids=[35]),{})
        self.assertEqual(out['cards'][0]['card_id'],self.cid)
        strong=collector_recommendation.recommend(self.db,q,dict(preferred_dex_ids=[35],preferred_illustrators=['Synthetic Artist']),{})
        self.assertEqual(strong['cards'][0]['card_id'],normal)
        exact=collector_recommendation.recommend(self.db,q,dict(preferred_dex_ids=[35]),{},scope=dict(language='en',set_code='SVP',collector_number='037/225',variant='normal'))
        self.assertEqual([r['card_id'] for r in exact['cards']],[normal])
        lookup=collector_discovery.execute(self.db,normal)
        self.assertEqual([r['card_id'] for r in lookup['cards']],[normal])
        self.assertFalse(lookup['cards'][0]['media_availability']['with_source_scans_eligible'])

    def test_only_explicit_boolean_filter_is_accepted(self):
        self.assertTrue(source_scan_filter('true'));self.assertFalse(source_scan_filter('false'))
        for value in ('yes','1','TRUE',None):
            with self.assertRaises(ValueError):source_scan_filter(value)
        with self.assertRaises(ValueError):core.catalog_search_internal(self.db,'Cleffa',with_source_scans=1)
        with self.assertRaises(ValueError):collector_discovery.execute(self.db,'Cleffa',with_source_scans='true')

    def test_exact_edition_ids_are_metadata_and_extra_copy_requests_still_block(self):
        for variant in ('normal_unlimited','normal_1st_edition'):
            core.import_cards(self.db,[dict(language='en',set_code='SVP',collector_number='037/225',variant=variant,name='Cleffa',provenance='synthetic',rights_reference='synthetic',match_eligible=True)])
            cid=core.card_id('en','SVP','037/225',variant)
            result=collector_discovery.execute(self.db,cid)
            self.assertEqual([r['card_id'] for r in result['cards']],[cid])
            self.assertEqual(result['requested_exact_card_id'],cid)
            extra=collector_discovery.execute(self.db,cid+' first edition graded copy')
            self.assertEqual(extra['task'],'copy_evidence_needed');self.assertEqual(extra['status'],'blocked')


if __name__=='__main__':unittest.main()

import copy,json,unittest
from pokemon_index import core,coordinate_family,collector_discovery,collector_journey


class CoordinateFamilyTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        for variant in ['normal','reverse']:
            core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',variant=variant,
                name='ピカチュウ',provenance='fixture',rights_reference='fixture',match_eligible=True)])
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='123',set_code='FIX',collector_number='001/100',name='ピカチュウ',provenance='fixture',rights_reference='fixture')])
        entry=dict(set_code='FIX',collector_number='001/100',part_role=None,rarity=None,rarity_icons=[],rarity_status='no_rarity_icon')
        page=dict(url='https://www.pokemon-card.com/card-search/details.php/card/123',page_sha256='a'*64,fetched_at='2026-10-02T00:00:00Z',name='ピカチュウ',
            page_kind='single_number',numbered_entries=[entry],illustrators=['Fixture'],dex_id=25,**entry)
        self.row=dict(schema='pokemon.coordinate-family-evidence.v1',revision=1,language='ja',set_code='FIX',collector_number='001/100',
            snapshot=coordinate_family.snapshot(self.db,'ja','FIX','001/100'),pages=[page],status='source_supported',hold_reason=None,name_status='exact_name',
            queue_sha256='a'*64,audit_sha256='b'*64,**{k:False for k in coordinate_family.FALSE_CLAIMS})
        self.sign(self.row)
    def sign(self,row):row['evidence_id']=coordinate_family.event_id(row);return row
    def tearDown(self):self.db.close()

    def test_family_does_not_assign_finish_or_upgrade_facets_and_selection(self):
        coordinate_family.import_evidence(self.db,[self.row])
        result=collector_discovery.execute(self.db,'Japanese FIX 001/100 non-holo')
        self.assertEqual(len(result['cards']),1)
        self.assertIn('coordinate_family_copy_evidence',result['unfulfilled_constraints'])
        self.assertFalse(result['cards'][0]['official_coordinate_family']['page_to_variant_mapping_verified'])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM discovery_card_facet').fetchone()[0],0)
        journey=collector_journey.replay(self.db,dict(turns=[dict(type='ask',question='Japanese FIX 001/100 non-holo')]))
        self.assertFalse(journey['selection_allowed']);self.assertIsNone(journey['target_intent'])
        self.assertEqual(self.db.execute('SELECT SUM(match_eligible) FROM card').fetchone()[0],2)

    def test_complete_membership_or_reference_drift_stales_proof_and_revision(self):
        coordinate_family.import_evidence(self.db,[self.row]);before=collector_journey.catalog_revision(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',variant='holo',name='ピカチュウ',provenance='new',rights_reference='fixture')])
        context=coordinate_family.context(self.db,'ja:FIX:001/100:normal')
        self.assertEqual(context['status'],'stale_coordinate_family_evidence');self.assertTrue(context['copy_evidence_needed'])
        self.assertNotEqual(before,collector_journey.catalog_revision(self.db))
        self.assertEqual(coordinate_family.status(self.db)['stale_coordinate_families'],1)

    def test_broad_set_discovery_cannot_bypass_copy_evidence_by_selecting(self):
        coordinate_family.import_evidence(self.db,[self.row])
        with self.assertRaisesRegex(ValueError,'physical-copy evidence'):
            collector_journey.replay(self.db,dict(turns=[dict(type='ask',question='Japanese FIX cards'),
                dict(type='select',card_id='ja:FIX:001/100:normal')]))

    def test_wrong_number_is_explicit_hold_only_never_supported_evidence(self):
        wrong=copy.deepcopy(self.row);wrong['pages'][0]['numbered_entries'][0]['collector_number']='002/100';wrong['pages'][0]['collector_number']='002/100';self.sign(wrong)
        with self.assertRaisesRegex(ValueError,'coordinates differ'):coordinate_family.import_evidence(self.db,[wrong])
        wrong.update(status='evidence_hold',hold_reason='source reference points to a different number',name_status='unresolved');self.sign(wrong)
        coordinate_family.import_evidence(self.db,[wrong])
        context=coordinate_family.context(self.db,'ja:FIX:001/100:normal')
        self.assertEqual(context['status'],'coordinate_family_evidence_hold');self.assertTrue(context['copy_evidence_needed'])

    def test_forged_variant_approval_and_partial_page_set_rollback(self):
        for mutate in [lambda r:r.update(page_to_variant_mapping_verified=True),lambda r:r.update(pages=[])]:
            bad=copy.deepcopy(self.row);mutate(bad);self.sign(bad)
            with self.assertRaises(ValueError):coordinate_family.import_evidence(self.db,[self.row,bad])
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM coordinate_family_evidence').fetchone()[0],0)

    def test_idempotent_import_and_consecutive_revision_binding(self):
        coordinate_family.import_evidence(self.db,[self.row,self.row]);before=collector_journey.catalog_revision(self.db)
        second=copy.deepcopy(self.row);second['revision']=2;second['pages'][0]['page_sha256']='c'*64;self.sign(second)
        coordinate_family.import_evidence(self.db,[second]);self.assertNotEqual(before,collector_journey.catalog_revision(self.db))
        self.assertEqual(coordinate_family.status(self.db)['coordinate_family_events'],2)

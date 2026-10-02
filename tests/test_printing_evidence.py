import copy,unittest
from pokemon_index import core,printing_evidence,supported_catalog


class PrintingEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',variant='normal',name='ピカチュウ',
            provenance='fixture',rights_reference='fixture',match_eligible=True)])
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='123',set_code='FIX',collector_number='001/100',name='ピカチュウ',provenance='fixture',rights_reference='fixture')])
        self.cid='ja:FIX:001/100:normal'
        source=dict(url='https://www.pokemon-card.com/card-search/details.php/card/123',page_sha256='a'*64,fetched_at='2026-10-02T00:00:00Z',
            image_url='https://www.pokemon-card.com/assets/images/card_images/large/FIX/000123_P_PIKACHU.jpg',image_sha256='b'*64)
        obs=dict(claim='printed_artist',value='Printed Artist',source_url=source['url'],locator='printed bottom credit',
            coordinate=dict(language='ja',set_code='FIX',collector_number='001/100'),scope='publisher_asset_only')
        self.row=dict(schema='pokemon.printing-source-evidence.v1',revision=1,subject_kind='coordinate',subject_id='ja:FIX:001/100',
            identity_sha256=supported_catalog.digest(printing_evidence.identity(self.db,'coordinate','ja:FIX:001/100')),status='source_observed',
            hold_reason=None,sources=[source],observations=[obs],recorded_at='2026-10-02T00:00:00Z',
            reviewers=[dict(actor=a,method='direct_image_reading',reviewed_at='2026-10-02T00:00:00Z',source_image_sha256s=['b'*64],observations_sha256=supported_catalog.digest([obs])) for a in ['agent','root']],
            **{k:False for k in printing_evidence.FALSE_CLAIMS})
        self.sign(self.row)
    def sign(self,row):row['event_id']=printing_evidence.event_id(row);return row
    def tearDown(self):self.db.close()

    def test_two_source_readings_overlay_without_copy_or_seed_permissions(self):
        printing_evidence.import_evidence(self.db,[self.row])
        self.assertEqual(printing_evidence.supported_artist(self.db,self.cid)['value'],'Printed Artist')
        ctx=printing_evidence.context(self.db,self.cid)
        self.assertTrue(ctx['copy_evidence_needed'])
        for flag in printing_evidence.FALSE_CLAIMS:self.assertIs(ctx[flag],False)
        self.assertEqual(self.db.execute('SELECT name,match_eligible,display_allowed FROM card').fetchone()[0],'ピカチュウ')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM card_facet').fetchone()[0],0)

    def test_single_or_held_review_does_not_support_artist(self):
        for mutation in [lambda r:r.update(reviewers=r['reviewers'][:1]),lambda r:r.update(status='evidence_hold',hold_reason='uncertain')]:
            row=copy.deepcopy(self.row);mutation(row);self.sign(row)
            printing_evidence.import_evidence(self.db,[row]);self.assertIsNone(printing_evidence.supported_artist(self.db,self.cid))
            self.db.execute('DELETE FROM printing_source_evidence');self.db.commit()

    def test_reading_image_mismatch_and_permission_forgery_rejected(self):
        mutations=[lambda r:r['reviewers'][1].update(observations_sha256='c'*64),
            lambda r:r['reviewers'][1].update(source_image_sha256s=['c'*64]),
            lambda r:r['reviewers'][1].update(actor='agent'),
            lambda r:r['sources'][0].update(image_url=r['sources'][0]['image_url'].replace('000123','000124')),
            lambda r:r.update(physical_finish_verified=True)]
        for mutate in mutations:
            bad=copy.deepcopy(self.row);mutate(bad);self.sign(bad)
            with self.assertRaises(ValueError):printing_evidence.import_evidence(self.db,[bad])

    def test_wrong_printed_number_is_preserved_only_as_hold(self):
        bad=copy.deepcopy(self.row);bad['observations'][0]['coordinate']['collector_number']='002/100'
        for reviewer in bad['reviewers']:reviewer['observations_sha256']=supported_catalog.digest(bad['observations'])
        self.sign(bad)
        with self.assertRaisesRegex(ValueError,'different printed coordinate'):printing_evidence.import_evidence(self.db,[bad])
        bad.update(status='evidence_hold',hold_reason='wrong reference number');self.sign(bad)
        printing_evidence.import_evidence(self.db,[bad]);self.assertIsNone(printing_evidence.supported_artist(self.db,self.cid))

    def test_source_reference_or_membership_drift_stales_artist(self):
        printing_evidence.import_evidence(self.db,[self.row])
        core.import_cards(self.db,[dict(language='ja',set_code='FIX',collector_number='001/100',variant='holo',name='ピカチュウ',provenance='new',rights_reference='fixture')])
        self.assertIsNone(printing_evidence.supported_artist(self.db,self.cid))
        self.assertEqual(printing_evidence.context(self.db,self.cid)['stale_findings'],1)

    def test_partial_multireference_credit_is_not_canonical_artist(self):
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='124',set_code='FIX',collector_number='001/100',name='ピカチュウ',provenance='fixture',rights_reference='fixture')])
        self.row['identity_sha256']=supported_catalog.digest(printing_evidence.identity(self.db,'coordinate','ja:FIX:001/100'));self.sign(self.row)
        printing_evidence.import_evidence(self.db,[self.row]);self.assertIsNone(printing_evidence.supported_artist(self.db,self.cid))

    def test_deleted_subject_is_stale_in_inventory_audit(self):
        printing_evidence.import_evidence(self.db,[self.row]);self.db.execute('DELETE FROM card_number_context');self.db.execute('DELETE FROM card');self.db.commit()
        self.assertEqual(printing_evidence.status(self.db)['stale_printing_sources'],1)

    def test_release_declaration_does_not_assign_individual_finish(self):
        row=copy.deepcopy(self.row);row.update(subject_kind='release',subject_id='ja:FIX',identity_sha256=supported_catalog.digest(printing_evidence.identity(self.db,'release','ja:FIX')))
        row['sources'][0].update(url='https://www.pokemon-card.com/ex/fix/index.html',image_url=None,image_sha256=None)
        row['observations']=[dict(claim='manufacturer_finish_declaration',value='mirror',source_url=row['sources'][0]['url'],locator='release mirror section',coordinate=None,scope='release_only')]
        for r in row['reviewers']:r.update(method='official_release_text',source_image_sha256s=[],observations_sha256=supported_catalog.digest(row['observations']))
        self.sign(row);printing_evidence.import_evidence(self.db,[row])
        self.assertFalse(printing_evidence.context(self.db,self.cid)['physical_finish_verified'])
        self.assertIsNone(printing_evidence.supported_artist(self.db,self.cid))

    def test_idempotence_and_consecutive_revisions(self):
        printing_evidence.import_evidence(self.db,[self.row,self.row])
        second=copy.deepcopy(self.row);second['revision']=2;second['recorded_at']='2026-10-02T00:01:00Z';self.sign(second)
        printing_evidence.import_evidence(self.db,[second]);self.assertEqual(printing_evidence.status(self.db)['printing_source_events'],2)
        self.assertEqual(printing_evidence.status(self.db)['current_printing_source_observations'],1)

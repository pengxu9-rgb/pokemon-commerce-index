"""Synthetic-only source-dimension holds and adversarial reimport/commerce gates."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from pokemon_index import core,catalog_locale,variant_dimension_hold as holds,catalog_media


class VariantDimensionHoldTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db);self.addCleanup(self.db.close)
        self.seed=dict(language='en',set_code='FIX',collector_number='001/100',variant='normal',name='Synthetic target',
            rarity=None,match_eligible=True,rights_reference='synthetic metadata only')
        text='const card: Card = {name:{en:"Synthetic target"},variants:[{type:"normal",size:"jumbo"},{type:"normal",subtype:"unlimited"}]} '
        raw=text.encode();revision='a'*40;sha=hashlib.sha256(raw).hexdigest();path='data/FIX/1.ts'
        self.seed['provenance']=f'tcgdex:{revision}:{path}:sha256:{sha}'
        core.import_cards(self.db,[self.seed]);self.cid=core.card_id('en','FIX','001/100','normal')
        self.row=dict(schema=holds.SCHEMA,revision=1,identity=catalog_locale.snapshot(self.db,self.cid),legacy_variant='normal',declared_size='jumbo',
            prior_structural_match_eligible=True,recorded_at='2026-10-12T00:00:00Z',parent_audit_sha256='c'*64,
            reason='Synthetic source size omitted; no physical or canonical identity approval',confidence=dict(pinned_source_bytes=1.0,physical_size=None,canonical_identity=None),
            source=dict(provider='tcgdex',language='en',region='ZZ',native_id=path,revision=revision,
                git_blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),sha256=sha,text=text,
                rights_reference=self.seed['rights_reference'],rights_status='metadata_internal_reviewed',license_sha256='b'*64,
                retrieved_at=None,retrieval_status='historical_snapshot_time_not_recorded',inspected_at='2026-10-12T00:00:00Z',physical_distribution_region=None),
            **{k:False for k in catalog_locale.FALSE_CLAIMS})
        self.row['unresolved_conflicts']=[self.row['reason']];self.sign(self.row)

    def sign(self,row):row['event_id']=holds.event_id(row);return row

    def test_hold_keeps_exact_identity_and_reimports_idempotently(self):
        original=catalog_locale.snapshot(self.db,self.cid)
        self.assertEqual(holds.import_evidence(self.db,[self.row]),dict(inserted=1,unchanged=0,eligibility_withdrawn=1))
        self.assertEqual(catalog_locale.snapshot(self.db,self.cid),original)
        before=[tuple(r) for r in self.db.execute('SELECT * FROM catalog_identity_quarantine')]
        self.assertEqual(holds.import_evidence(self.db,[self.row]),dict(inserted=0,unchanged=1,eligibility_withdrawn=0))
        self.assertEqual([tuple(r) for r in self.db.execute('SELECT * FROM catalog_identity_quarantine')],before)
        ctx=holds.context(self.db,self.cid);self.assertEqual(ctx['declared_source_size'],'jumbo');self.assertIsNone(ctx['canonical_replacement_card_id'])
        self.assertEqual(ctx['status'],'held_legacy_variant_dimensions')

    def test_seed_and_direct_flag_updates_cannot_restore_eligibility(self):
        holds.import_evidence(self.db,[self.row]);seed={**self.seed,'display_allowed':True}
        core.import_cards(self.db,[seed])
        self.db.execute('UPDATE card SET match_eligible=1,display_allowed=1 WHERE card_id=?',(self.cid,));self.db.commit()
        self.assertEqual(tuple(self.db.execute('SELECT match_eligible,display_allowed FROM card').fetchone()),(0,0))
        self.assertEqual(core.catalog_card_internal(self.db,self.cid)['card']['media_availability']['status'],'identity_hold')

    def test_source_drift_and_rehashed_evidence_cannot_lift_hold(self):
        holds.import_evidence(self.db,[self.row])
        for key,value in [('provenance','changed'),('name','Changed'),('rarity','Changed'),('rights_reference','changed')]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'immutable'):core.import_cards(self.db,[{**self.seed,key:value}])
        self.db.execute("UPDATE card SET provenance='changed'");self.db.commit()
        self.assertEqual(holds.context(self.db,self.cid)['status'],'stale_hold_source_changed')
        self.assertTrue(holds.held(self.db,self.cid))
        with self.assertRaisesRegex(ValueError,'hold'):core._unit(self.db,self.cid,'RAW','raw','unknown')

    def test_forged_size_source_collision_and_approvals_abort_atomically(self):
        for mutate in [lambda r:r.update(declared_size='standard'),lambda r:r['source'].update(text=r['source']['text'].replace('jumbo','standard')),
                       lambda r:r['identity'].update(language='ja'),lambda r:r['source'].update(native_id='data/OTHER/1.ts'),
                       lambda r:r.update(purchase_allowed=True),lambda r:r['source'].update(region='JP'),lambda r:r.update(prior_structural_match_eligible=False)]:
            bad=copy.deepcopy(self.row);mutate(bad);self.sign(bad)
            with self.assertRaises(ValueError):holds.import_evidence(self.db,[bad])
            self.assertFalse(holds.held(self.db,self.cid));self.assertEqual(self.db.execute('SELECT match_eligible FROM card').fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'duplicate'):holds.import_evidence(self.db,[self.row,self.row])

    def test_prebound_and_human_commerce_paths_reject_without_destroying_history(self):
        core.register_source(self.db,dict(source='fixture',rights_reference='synthetic',ingest_allowed=True,display_allowed=True,price_statistics_allowed=True,seller_analytics_allowed=True,retention_days=365,listing_ttl_hours=24))
        unit=core._unit(self.db,self.cid,'RAW','raw','unknown')
        self.db.execute('INSERT INTO listing VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',('fixture','old','Synthetic target FIX 001/100','https://example.invalid/old',None,unit,'human','2026-10-12T00:00:00+00:00','2026-10-12T00:00:00+00:00','on_sale',100,'USD'));self.db.commit()
        holds.import_evidence(self.db,[self.row])
        actions=[lambda:core._unit(self.db,self.cid,'RAW','raw','new'),lambda:core.units_for_card(self.db,self.cid),
            lambda:core.offers(self.db,self.cid),lambda:core.recommend(self.db,unit,'US'),lambda:core.index_for_unit(self.db,unit,'2026-10-12'),
            lambda:core.seller_overlap(self.db,'fixture',[unit]),lambda:core.override_resolution(self.db,'fixture','old',unit,'synthetic reviewer','test'),
            lambda:core.import_observations(self.db,[dict(source='fixture',native_id='old',title='Synthetic target FIX 001/100',url='https://example.invalid/old',observed_at='2026-10-12T01:00:00Z',status='on_sale',currency='USD',price_minor=100,evidence_ref='synthetic')]),
            lambda:core.import_quotes(self.db,[dict(source='fixture',native_id='old',destination='US',currency='USD',components={k:0 for k in core.COMPONENTS},quoted_at='2026-10-12T01:00:00Z',expires_at='2026-10-12T02:00:00Z',evidence_ref='synthetic')]),
            lambda:core.import_verified_sales(self.db,[dict(source='fixture',native_id='old',settled_at='2026-10-12T01:00:00Z',paid_minor=100,currency='USD',evidence_ref='synthetic')])]
        for action in actions:
            with self.assertRaisesRegex(ValueError,'hold'):action()
        self.assertEqual(self.db.execute('SELECT unit_id FROM listing').fetchone()[0],unit)
        self.assertEqual(self.db.execute('SELECT count(*) FROM priceable_unit').fetchone()[0],1)

    def test_old_readonly_snapshot_without_additive_ledger_keeps_behavior(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'old.sqlite3'
            old=core.connect(path);self.db.backup(old);old.execute('DROP TABLE catalog_identity_quarantine');old.commit();old.close()
            with core.connect(path,readonly=True) as db:
                self.assertFalse(holds.held(db,self.cid));self.assertIsNone(holds.context(db,self.cid))
                self.assertEqual(catalog_media.availability(db,self.cid)['status'],'missing_source_scan_evidence')
                self.assertEqual(core.catalog_card_internal(db,self.cid)['card']['card_id'],self.cid)

    def test_new_image_and_number_evidence_cannot_bind_held_identity(self):
        from tests import test_source_image_facts as image_fixtures,test_number_evidence as number_fixtures
        from pokemon_index import source_image_facts,number_evidence,supported_catalog
        holds.import_evidence(self.db,[self.row])
        snapshot=number_evidence.snapshot(self.db,self.cid)
        fixture=image_fixtures.SourceImageFactTests();fixture.setUp()
        try:image=copy.deepcopy(fixture.row)
        finally:fixture.tearDown()
        image.update(card_id=self.cid,endpoint_snapshot=snapshot,identity_sha256=supported_catalog.digest(snapshot),source_file_sha256=self.row['source']['sha256'])
        image['event_id']=source_image_facts.event_id(image)
        with self.assertRaisesRegex(ValueError,'dimension-held'):source_image_facts.import_evidence(self.db,[image])
        fixture=number_fixtures.NumberEvidenceTests();fixture.setUp()
        try:number=copy.deepcopy(fixture.row)
        finally:fixture.tearDown()
        number.update(card_id=self.cid,endpoint_snapshot=snapshot,identity_sha256=supported_catalog.digest(snapshot),status='catalog_text_observed')
        for reviewer in number['review_groups'][0]['reviews']:reviewer.update(observed_number_text='001/100',observed_name='Synthetic target')
        number['event_id']=number_evidence.event_id(number)
        with self.assertRaisesRegex(ValueError,'dimension-held'):number_evidence.import_evidence(self.db,[number])
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_image_fact_evidence').fetchone()[0],0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_number_reading_evidence').fetchone()[0],0)

    def test_audit_rejects_missing_guards_and_wrong_sql_bindings(self):
        from scripts.audit_variant_dimension_holds import installed
        holds.import_evidence(self.db,[self.row]);self.assertTrue(installed(self.db,[self.row]))
        for statement in ['DROP TRIGGER variant_dimension_hold_card_update','DROP TRIGGER variant_dimension_hold_card_insert','DROP INDEX variant_dimension_hold_card_id']:
            scratch=core.connect(':memory:');self.db.backup(scratch)
            try:
                scratch.execute(statement);scratch.commit()
                with self.assertRaisesRegex(ValueError,'retention guards'):installed(scratch,[self.row])
            finally:scratch.close()
        for statement in ["UPDATE catalog_identity_quarantine SET reason='changed'", "UPDATE catalog_identity_quarantine SET quarantine_id='variant-dimension-hold:wrong'"]:
            scratch=core.connect(':memory:');self.db.backup(scratch)
            try:
                scratch.execute(statement);scratch.commit()
                with self.assertRaisesRegex(ValueError,'SQL binding'):installed(scratch,[self.row])
            finally:scratch.close()


if __name__=='__main__':unittest.main()

import copy,json,unittest
from pokemon_index import core,source_corrections,printing_evidence,supported_catalog,collector_discovery
from tests import test_printing_evidence as fixture_module

class SourceCorrectionTests(unittest.TestCase):
    sign=fixture_module.PrintingEvidenceTests.sign
    def tearDown(self):self.db.close()
    # Use the existing explicitly synthetic publisher-reading fixture only.
    def setUp(self):
        fixture_module.PrintingEvidenceTests.setUp(self)
        self.db.execute('INSERT INTO card_facet VALUES (?,?,?,?,?)',(self.cid,'illustrator','Bad Seed Artist','fixture','fixture'));self.db.commit()
        printing_evidence.import_evidence(self.db,[self.row]);encoded=self.db.execute('SELECT record_json FROM printing_source_evidence').fetchone()[0]
        self.correction=dict(schema='pokemon.source-correction.v1',revision=1,kind='printed_artist',language='ja',set_code='FIX',collector_number='001/100',correction_key='printed_artist:ja:FIX:001/100',snapshot=source_corrections.snapshot(self.db,'ja','FIX','001/100'),parent_event_id=self.row['event_id'],parent_record_json=encoded,parent_record_sha256=supported_catalog.digest(self.row),value='Printed Artist',reference_exclusion=None,new_card=None,new_reference=None,official_page=None,recorded_at='2026-10-02T00:01:00Z',**{k:False for k in source_corrections.FALSE_CLAIMS})
        self.correction['event_id']=source_corrections.event_id(self.correction)
    def sign_correction(self,r):r['event_id']=source_corrections.event_id(r);return r
    def test_generic_professor_inquiries_do_not_invent_named_person_constraints(self):
        for tail in ['which professor is printed beside the title?', 'what professor appears on this card?']:
            response=collector_discovery.execute(self.db,'Japanese FIX 001/100: '+tail)
            self.assertEqual(response['cards'][0]['card_id'],self.cid)
        self.assertEqual(collector_discovery._unsupported_professors(self.db,'professor turo'),['professor turo'])
    def test_effective_artist_is_sql_source_fact_and_raw_facet_unchanged(self):
        source_corrections.import_evidence(self.db,[self.correction,self.correction]);self.assertEqual(self.db.execute('SELECT value FROM discovery_card_facet').fetchone()[0],'Printed Artist');self.assertEqual(self.db.execute('SELECT value FROM card_facet').fetchone()[0],'Bad Seed Artist')
        self.assertEqual(source_corrections.status(self.db)['active_source_corrections'],1);self.assertEqual(self.db.execute('SELECT match_eligible FROM card').fetchone()[0],1)
    def test_card_reference_and_facet_drift_remove_sql_correction_and_all_credit(self):
        source_corrections.import_evidence(self.db,[self.correction])
        for sql in ["UPDATE card SET name='Changed'","UPDATE card SET attributes_json='{\"modified\":true}'","UPDATE card_reference SET name='Changed'","UPDATE card_reference SET attributes_json='{\"modified\":true}'","UPDATE card_facet SET value='Changed'","INSERT INTO card_facet VALUES ('ja:FIX:001/100:normal','illustrator','Another','fixture','fixture')"]:
            with self.subTest(sql=sql):
                db=core.connect(':memory:');self.db.backup(db);db.execute(sql);db.commit()
                self.assertEqual(db.execute('SELECT COUNT(*) FROM active_source_correction_evidence').fetchone()[0],0)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM discovery_card_facet WHERE facet_type='illustrator'").fetchone()[0],0)
                self.assertIsNone(source_corrections.printed_artist(db,self.cid));db.close()
    def test_parent_supersession_and_parent_content_drift_remove_sql_fact(self):
        source_corrections.import_evidence(self.db,[self.correction]);second=copy.deepcopy(self.row);second['revision']=2;second['recorded_at']='2026-10-02T00:02:00Z';self.sign(second);printing_evidence.import_evidence(self.db,[second]);self.assertEqual(self.db.execute('SELECT COUNT(*) FROM active_source_correction_evidence').fetchone()[0],0)
    def test_forged_value_snapshot_parent_and_permissions_reject_atomically(self):
        for mutate in [lambda r:r.update(value='Fabricated'),lambda r:r.update(physical_finish_verified=True),lambda r:r['snapshot']['cards'][0].update(name='Other'),lambda r:r.update(parent_record_sha256='d'*64),lambda r:r.update(parent_record_json='{}')]:
            bad=copy.deepcopy(self.correction);mutate(bad);self.sign_correction(bad)
            with self.assertRaises(ValueError):source_corrections.import_evidence(self.db,[self.correction,bad])
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM source_correction_evidence').fetchone()[0],0)
    def test_correction_creation_cannot_predate_actual_source_reviews(self):
        bad=copy.deepcopy(self.correction);bad['recorded_at']='2026-10-01T23:59:59Z';self.sign_correction(bad)
        with self.assertRaisesRegex(ValueError,'predate'):source_corrections.import_evidence(self.db,[bad])
    def test_exact_coordinates_respect_recognized_and_unknown_artist_constraints(self):
        source_corrections.import_evidence(self.db,[self.correction])
        for artist in ['Bad Seed Artist','Nonexistent Artist']:
            r=collector_discovery.execute(self.db,'Japanese FIX 001/100 by artist '+artist);self.assertEqual(r['cards'],[]);self.assertEqual(r['status'],'no_match')
        r=collector_discovery.execute(self.db,'Japanese FIX 001/100 by artist Printed Artist');self.assertEqual(r['cards'][0]['card_id'],self.cid)
        for question in ['Japanese FIX 001/100 by Bad Seed Artist','Japanese FIX 001/100 by Unrecognized Person']:
            self.assertEqual(collector_discovery.execute(self.db,question)['cards'],[])
    def test_illustrator_inquiry_is_not_a_named_artist_constraint(self):
        source_corrections.import_evidence(self.db,[self.correction])
        r=collector_discovery.execute(self.db,'Who is credited as the illustrator on Japanese FIX 001/100?')
        self.assertEqual(r['cards'][0]['printed_artist_credit']['value'],'Printed Artist')
    def test_single_token_by_credit_requests_use_current_artist_values(self):
        for artist in ['HACCAN','YOSHIROTTEN','0313']:
            db=core.connect(':memory:');self.db.backup(db);parent=copy.deepcopy(self.row);parent['revision']=2;parent['observations'][0]['value']=artist
            for reviewer in parent['reviewers']:reviewer['observations_sha256']=supported_catalog.digest(parent['observations'])
            self.sign(parent);printing_evidence.import_evidence(db,[parent]);corr=copy.deepcopy(self.correction);corr.update(value=artist,parent_event_id=parent['event_id'],parent_record_json=db.execute('SELECT record_json FROM printing_source_evidence WHERE event_id=?',(parent['event_id'],)).fetchone()[0],parent_record_sha256=supported_catalog.digest(parent));self.sign_correction(corr);source_corrections.import_evidence(db,[corr])
            r=collector_discovery.execute(db,'Japanese FIX 001/100 by '+artist);self.assertEqual(r['cards'][0]['printed_artist_credit']['value'],artist);db.close()
    def test_qualifier_constraint_preserves_language_and_exact_number(self):
        self.db.execute('DELETE FROM printing_source_evidence');self.db.commit()
        row=copy.deepcopy(self.row);row['observations'][0].update(claim='printed_qualifier',value='オーリム博士')
        for reviewer in row['reviewers']:reviewer['observations_sha256']=supported_catalog.digest(row['observations'])
        self.sign(row);printing_evidence.import_evidence(self.db,[row]);encoded=self.db.execute('SELECT record_json FROM printing_source_evidence').fetchone()[0]
        corr=copy.deepcopy(self.correction);corr.update(kind='printed_qualifier',correction_key='printed_qualifier:ja:FIX:001/100',parent_event_id=row['event_id'],parent_record_json=encoded,parent_record_sha256=supported_catalog.digest(row),value='オーリム博士');self.sign_correction(corr);source_corrections.import_evidence(self.db,[corr])
        core.import_cards(self.db,[dict(language='en',set_code='FIX',collector_number='001/100',variant='normal',name='English target',provenance='fixture',rights_reference='fixture')])
        self.assertEqual(collector_discovery.execute(self.db,'English FIX 001/100 オーリム博士')['cards'],[])
        self.assertEqual(collector_discovery.execute(self.db,'Japanese FIX 001/100 オーリム博士')['cards'][0]['card_id'],self.cid)
        self.assertEqual(collector_discovery.execute(self.db,'Japanese FIX 001/100 オダマキ博士')['cards'],[])
        self.assertEqual(collector_discovery.execute(self.db,'Japanese FIX 001/100 Professor Turo')['cards'],[])
        self.assertEqual(collector_discovery.execute(self.db,'Japanese FIX 001/100 オーリム博士 オダマキ博士')['cards'],[])
        second=copy.deepcopy(corr);second.update(correction_key='printed_qualifier:ja:FIX:002/100',collector_number='002/100',value='フトゥー博士')
        self.db.execute("INSERT INTO source_correction_evidence VALUES ('synthetic-other','printed_qualifier:ja:FIX:002/100',1,'printed_qualifier','ja','FIX','002/100',?)",(json.dumps(second,ensure_ascii=False),));self.db.commit()
        self.assertEqual(collector_discovery.execute(self.db,'Japanese FIX 001/100 オーリム博士 フトゥー博士')['cards'],[])

class ReferenceBoundaryCorrectionTests(unittest.TestCase):
    sign=fixture_module.PrintingEvidenceTests.sign
    def tearDown(self):self.db.close()
    def setUp(self):
        fixture_module.PrintingEvidenceTests.setUp(self)
        core.import_card_references(self.db,[dict(source='ptcg-database',source_jp_id='124',set_code='FIX',collector_number='001/100',name='ピカチュウ',provenance='wrong-fixture',rights_reference='fixture')])
        parent=copy.deepcopy(self.row);parent.update(status='evidence_hold',hold_reason='wrong source number',identity_sha256=supported_catalog.digest(printing_evidence.identity(self.db,'coordinate','ja:FIX:001/100')))
        second=copy.deepcopy(parent['sources'][0]);second.update(url=second['url'].replace('/123','/124'),image_url=second['image_url'].replace('000123','000124'));parent['sources'].append(second)
        parent['observations']=[dict(claim='printed_number',value=num,source_url=src['url'],locator='printed bottom number',coordinate=dict(language='ja',set_code='FIX',collector_number=num),scope='publisher_asset_only') for src,num in zip(parent['sources'],['001/100','002/100'])]
        for actor in parent['reviewers']:actor.update(source_image_sha256s=['b'*64,'b'*64],observations_sha256=supported_catalog.digest(parent['observations']))
        self.sign(parent);printing_evidence.import_evidence(self.db,[parent]);encoded=self.db.execute('SELECT record_json FROM printing_source_evidence').fetchone()[0]
        attrs=json.dumps(dict(family_scope_only=True,parent_printing_event=parent['event_id'],source_namespace='official-printed-coordinate',physical_finish_verified=False,listing_copy_verified=False),sort_keys=True)
        provenance='official-printed-coordinate:124:page-sha256:'+'a'*64+':image-sha256:'+'b'*64+':parent:'+parent['event_id'];variant='official_coordinate_family_only_124';url=second['url']
        card=dict(card_id=core.card_id('ja','FIX','002/100',variant),language='ja',set_code='FIX',collector_number='002/100',variant=variant,name='ピカチュウ',rarity=None,provenance=provenance,rights_reference=url,display_allowed=0,match_eligible=0,attributes_json=attrs)
        ref=dict(source='official-printed-coordinate',native_id='124',set_code='FIX',collector_number='002/100',name='ピカチュウ',rarity=None,attributes_json=attrs,provenance=provenance,rights_reference=url,display_allowed=0)
        self.correction=dict(schema='pokemon.source-correction.v1',revision=1,kind='reference_boundary',language='ja',set_code='FIX',collector_number='001/100',correction_key='reference_boundary:ja:FIX:001/100',snapshot=source_corrections.snapshot(self.db,'ja','FIX','001/100'),parent_event_id=parent['event_id'],parent_record_json=encoded,parent_record_sha256=supported_catalog.digest(parent),value=None,reference_exclusion=dict(source='ptcg-database',native_id='124',set_code='FIX',collector_number='001/100'),new_card=card,new_reference=ref,official_page=dict(url=url,page_sha256='a'*64,name='ピカチュウ',numbered_entries=[dict(set_code='FIX',collector_number='002/100')]),recorded_at='2026-10-02T00:01:00Z',**{k:False for k in source_corrections.FALSE_CLAIMS})
        self.correction['event_id']=source_corrections.event_id(self.correction)
    def test_split_effective_reference_preserves_wrong_seed_and_family_only_permissions(self):
        source_corrections.import_evidence(self.db,[self.correction]);source_corrections.import_evidence(self.db,[self.correction])
        self.assertEqual(self.db.execute("SELECT collector_number FROM card_reference WHERE source='ptcg-database' AND native_id='124'").fetchone()[0],'001/100')
        self.assertEqual([r[0] for r in self.db.execute("SELECT native_id FROM effective_card_reference WHERE collector_number='001/100'")],['123'])
        self.assertEqual([r[0] for r in self.db.execute("SELECT native_id FROM effective_card_reference WHERE collector_number='002/100'")],['124'])
        c=self.db.execute('SELECT * FROM card WHERE card_id=?',(self.correction['new_card']['card_id'],)).fetchone();self.assertEqual((c['match_eligible'],c['display_allowed']),(0,0))
        result=collector_discovery.execute(self.db,'Japanese FIX 002/100');self.assertIn('source_family_copy_evidence',result['unfulfilled_constraints'])
    def test_forged_new_title_provenance_or_eligibility_rejects_without_new_identity(self):
        for mutation in [lambda r:r['new_card'].update(match_eligible=1),lambda r:r['new_card'].update(name='Forged'),lambda r:r['new_card'].update(provenance=r['new_card']['provenance']+'spoof'),lambda r:r['new_reference'].update(extra='hidden'),lambda r:r['new_reference'].update(rarity='UR')]:
            bad=copy.deepcopy(self.correction);mutation(bad);bad['event_id']=source_corrections.event_id(bad)
            with self.assertRaises(ValueError):source_corrections.import_evidence(self.db,[bad])
            self.assertEqual(self.db.execute('SELECT COUNT(*) FROM card').fetchone()[0],1)
    def test_historical_family_guard_survives_removed_flag_variant_and_provenance(self):
        source_corrections.import_evidence(self.db,[self.correction]);cid=self.correction['new_card']['card_id']
        self.db.execute("UPDATE card SET attributes_json='{}',variant='rewritten',provenance='rewritten' WHERE card_id=?",(cid,));self.db.commit()
        self.assertTrue(source_corrections.family_scope_only(self.db,cid))
        r=collector_discovery.execute(self.db,'Japanese FIX 002/100');self.assertIn('source_family_copy_evidence',r['unfulfilled_constraints'])
    def test_new_family_drift_withholds_effective_reference_and_keeps_wrong_reference_excluded(self):
        source_corrections.import_evidence(self.db,[self.correction]);self.db.execute("UPDATE card SET name='Changed' WHERE collector_number='002/100'");self.db.commit()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM active_source_correction_evidence').fetchone()[0],0)
        self.assertEqual([r[0] for r in self.db.execute('SELECT native_id FROM effective_card_reference')],['123'])
        self.assertEqual(source_corrections.context(self.db,self.correction['new_card']['card_id'])['findings'][0]['status'],'stale_source_correction')

# Only synthetic correction fixtures are exercised here.
if __name__=='__main__':unittest.main()

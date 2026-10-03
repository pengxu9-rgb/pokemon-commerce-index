import copy, hashlib, io, json, tarfile, tempfile, unittest
from pathlib import Path
from pokemon_index import core, number_evidence as numbers, source_image_facts as facts
from scripts.compile_source_fact_escalation import freeze_heads, compile_reviews
from scripts.freeze_relationship_identity_review import digest, source_bytes


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.image=Path(self.tmp.name)/'opaque.webp';self.image.write_bytes(b'fixture pixel binding')
        self.sha=hashlib.sha256(self.image.read_bytes()).hexdigest();body=b'const card = {\n hp: 50,\n}\n';self.source_sha=hashlib.sha256(body).hexdigest()
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as ar:
            info=tarfile.TarInfo('cards-database-'+('a'*40)+'/data/test.ts');info.size=len(body);ar.addfile(info,io.BytesIO(body))
        stream.seek(0);self.archive=tarfile.open(fileobj=stream)
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='TEST',collector_number='001/010',variant='normal',name='ナゾノクサ',provenance='tcgdex:'+('a'*40)+':data/test.ts:sha256:'+self.source_sha,rights_reference='fixture',match_eligible=True)])
        self.cid='ja:TEST:001/010:normal';snap=numbers.snapshot(self.db,self.cid);src='https://assets.tcgdex.net/ja/SV/SV2a/001/high.webp'
        reading=dict(title_text_parts=['ナゾノクサ'],title_symbols=[],title_furigana=None,observed_number_text='001/010',hp=50,hp_status='visible',notes='fixture')
        self.raw=[dict(target_id='opaque-1',actor=a,model_family=f,model_version='fixture',reviewed_at='2026-10-03T00:00:00Z',source_ref=src,image_sha256=self.sha,prior_verdicts_visible=False,expected_catalog_context_visible=False,reading=copy.deepcopy(reading),status='reviewed') for a,f in [('astra','openai'),('gemini','google')]]
        old_reviews=copy.deepcopy([{k:r[k] for k in facts.REVIEW_FIELDS if k!='review_record_sha256'}|dict(review_record_sha256=digest(r)) for r in self.raw]);old_reviews[0]['model_family']='apple-vision-ocr';old_reviews[0]['reading']['observed_number_text']=None
        nr_reviews=[{k:r[k] for k in ['actor','model_family','model_version','reviewed_at','source_ref','image_sha256','prior_verdicts_visible','review_record_sha256']}|dict(observed_name='ナゾノクサ',observed_number_text=r['reading']['observed_number_text']) for r in old_reviews]
        self.nr=dict(schema=numbers.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=snap,identity_sha256=digest(snap),source_ref=src,image_sha256=self.sha,review_groups=[dict(candidate_id='old',cohort_snapshot_sha256='b'*64,reviews=nr_reviews)],status='reading_hold',recorded_at='2026-10-03T00:01:00Z',**{k:False for k in numbers.FALSE_CLAIMS});self.nr['event_id']=numbers.event_id(self.nr);numbers.import_evidence(self.db,[self.nr])
        self.fr=dict(schema=facts.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=snap,identity_sha256=digest(snap),source_ref=src,image_sha256=self.sha,source_file_sha256=self.source_sha,pinned_source_hp=50,cohort_snapshot_sha256='c'*64,reviews=old_reviews,recorded_at='2026-10-03T00:01:00Z',**{k:False for k in facts.FALSE_CLAIMS});self.fr['event_id']=facts.event_id(self.fr);facts.import_evidence(self.db,[self.fr])
        c=dict(target_id='opaque-1',endpoint_snapshot=snap,identity_sha256=digest(snap),source_ref=src,image_sha256=self.sha,image_path=str(self.image),source_audit=source_bytes(snap['provenance'],self.archive),pinned_source_hp=50,prior_number_event_id=self.nr['event_id']);c['snapshot_sha256']=digest(c)
        self.cohort={c['target_id']:freeze_heads(self.db,{c['target_id']:c})[0]}
    def tearDown(self):self.db.close();self.archive.close();self.tmp.cleanup()
    def compile(self,raw=None):
        a,b=raw or self.raw
        return compile_reviews(self.db,self.archive,self.cohort,{'opaque-1':a},{'opaque-1':b})
    def test_appends_revision_two_without_erasing_ocr_history(self):
        nr,fr,outcomes=self.compile();self.assertEqual(nr[0]['revision'],2);self.assertEqual(fr[0]['revision'],2);self.assertEqual(nr[0]['status'],'catalog_text_observed')
        numbers.import_evidence(self.db,nr);facts.import_evidence(self.db,fr)
        self.assertEqual(numbers.context(self.db,self.cid)['inspection_tier'],'two_image_model_families')
        self.assertEqual(self.db.execute('SELECT record_json FROM card_number_reading_evidence WHERE event_id=?',(self.nr['event_id'],)).fetchone()[0],json.dumps(self.nr,ensure_ascii=False,sort_keys=True))
        self.assertEqual(self.db.execute('SELECT count(*) FROM source_image_fact_evidence').fetchone()[0],2)
        self.assertTrue(all(nr[0][k] is False for k in numbers.FALSE_CLAIMS))
    def test_either_stale_head_prevents_compilation(self):
        for row,importer,eventid in [(self.nr,numbers.import_evidence,numbers.event_id),(self.fr,facts.import_evidence,facts.event_id)]:
            newer=copy.deepcopy(row);newer['revision']=2;newer['event_id']=eventid(newer);importer(self.db,[newer])
            with self.assertRaisesRegex(ValueError,'stale'):self.compile()
            table='card_number_reading_evidence' if row is self.nr else 'source_image_fact_evidence';self.db.execute('DELETE FROM '+table+' WHERE revision=2');self.db.commit()
    def test_image_source_hp_and_endpoint_drift_are_rejected(self):
        self.image.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'image bytes'):self.compile()
        self.image.write_bytes(b'fixture pixel binding');self.db.execute('UPDATE card SET name=? WHERE card_id=?',('wrong',self.cid))
        with self.assertRaisesRegex(ValueError,'endpoint drift'):self.compile()
    def test_ocr_context_exposure_and_asset_substitution_cannot_upgrade(self):
        for changes in [dict(model_family='apple-vision-ocr'),dict(prior_verdicts_visible=True),dict(expected_catalog_context_visible=True),dict(image_sha256='a'*64)]:
            raw=copy.deepcopy(self.raw);raw[0].update(changes)
            with self.assertRaises(ValueError):self.compile(raw)
    def test_incomplete_review_keeps_prior_heads_and_disagreement_remains_held(self):
        raw=copy.deepcopy(self.raw);raw[1]['status']='review_failed';nr,fr,outcomes=self.compile(raw);self.assertFalse(nr or fr);self.assertTrue(outcomes[0]['previous_heads_preserved'])
        raw=copy.deepcopy(self.raw);raw[1]['reading']['observed_number_text']='002/010';nr,fr,outcomes=self.compile(raw);self.assertEqual(nr[0]['status'],'reading_hold')
    def test_snapshot_tampering_and_membership_mismatch_fail(self):
        self.cohort['opaque-1']['prior_source_fact_revision']=9
        with self.assertRaisesRegex(ValueError,'cohort changed'):self.compile()
        with self.assertRaisesRegex(ValueError,'membership'):compile_reviews(self.db,self.archive,self.cohort,{}, {})

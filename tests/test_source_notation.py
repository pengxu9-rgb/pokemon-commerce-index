import copy,unittest
from pokemon_index import core,number_evidence as n,source_image_facts as f


class VersionedNumberRuleTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='SV4A',collector_number='191/190',variant='holo',name='ナゾノクサ',provenance='fixture',rights_reference='fixture',match_eligible=True)])
        cid='ja:SV4A:191/190:holo';snap=n.snapshot(self.db,cid);src='https://assets.tcgdex.net/ja/SV/SV4a/191/high.webp'
        reviews=[dict(actor=a,model_family=family,model_version='fixture',reviewed_at='2026-10-03T00:00:00Z',review_record_sha256=letter*64,source_ref=src,image_sha256='a'*64,observed_number_text=text,observed_name='ナゾノクサ',prior_verdicts_visible=False) for a,family,letter,text in [('first','openai','b','191/190'),('second','google','c','191/190 S')]]
        self.old=dict(schema=n.SCHEMA,revision=1,card_id=cid,endpoint_snapshot=snap,identity_sha256=n.supported_catalog.digest(snap),source_ref=src,image_sha256='a'*64,review_groups=[dict(candidate_id='fixture',cohort_snapshot_sha256='d'*64,reviews=reviews)],status='reading_hold',recorded_at='2026-10-03T00:01:00Z',**{k:False for k in n.FALSE_CLAIMS});self.old['event_id']=n.event_id(self.old);n.import_evidence(self.db,[self.old])
    def tearDown(self):self.db.close()
    def derived(self):
        r=copy.deepcopy(self.old);r.update(schema=n.SCHEMA_V2,reading_rule=n.SK_RULE,prior_event_id=self.old['event_id'],prior_event_sha256=n.supported_catalog.digest(self.old),revision=2,status='catalog_text_observed',recorded_at='2026-10-03T00:02:00Z');r['event_id']=n.event_id(r);return r
    def test_versioned_rule_reuses_raw_readings_and_preserves_historical_hold(self):
        r=self.derived();n.import_evidence(self.db,[r,r]);ctx=n.context(self.db,r['card_id']);self.assertTrue(ctx['review_reuse_disclosed']);self.assertEqual(ctx['reading_rule'],n.SK_RULE);self.assertEqual(ctx['observed_number_texts'],['191/190','191/190 S'])
        self.assertNotEqual(n.reading_key('191/190 S'),'191/190');n.validate(self.old)
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_number_reading_evidence').fetchone()[0],2)
        self.assertFalse(ctx['catalog_identity_confirmed']);self.assertFalse(ctx['price_comparable'])
    def test_only_complete_numeric_fraction_and_exact_sk_tokens_are_separated(self):
        for text in ['191/190 S','191 / 190 K']:self.assertEqual(n.reading_key(text,rule=n.SK_RULE),'191/190')
        for text in ['191 S','TG01/TG30 S','191/190 SK','191/190 S K','191/190 UNKNOWN','191/190 S extra','017/103 01/30']:
            self.assertIsNone(n.reading_key(text,rule=n.SK_RULE))
        self.assertEqual(n.classify('191/190',['191/191 S','191/191'],reading_rule=n.SK_RULE),'different_text_observed')
    def test_prior_head_hash_and_original_inspection_are_required(self):
        for mutate in [lambda r:r.update(prior_event_sha256='f'*64),lambda r:r.update(prior_event_id='unknown'),lambda r:r['review_groups'][0]['reviews'][0].update(observed_name='wrong')]:
            r=self.derived();mutate(r)
            if r['review_groups'][0]['reviews'][0]['observed_name']=='wrong':r['status']='reading_hold'
            r['event_id']=n.event_id(r)
            with self.assertRaises(ValueError):n.import_evidence(self.db,[r])
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_number_reading_evidence').fetchone()[0],1)
    def test_unknown_rule_english_scope_and_backdated_interpretation_rejected(self):
        for mutate in [lambda r:r.update(reading_rule='anything'),lambda r:r['endpoint_snapshot'].update(language='en'),lambda r:r.update(recorded_at='2026-10-03T00:00:00Z')]:
            r=self.derived();mutate(r);r['identity_sha256']=n.supported_catalog.digest(r['endpoint_snapshot']);r['event_id']=n.event_id(r)
            with self.assertRaises(ValueError):n.import_evidence(self.db,[r])


def reading(text=None,parts=None,symbols=None):
    return dict(title_text_parts=parts or ['シェイミ'],title_symbols=symbols if symbols is not None else [dict(kind='prism_star',after_text_part=0)],title_furigana=None,observed_number_text=text,hp=80,hp_status='visible',notes='fixture')


class SourceNotationTests(unittest.TestCase):
    def row(self,a,b):return dict(endpoint_snapshot=dict(name='シェイミ'),reviews=[dict(reading=a),dict(reading=b)])
    def test_prism_mechanic_is_retained_without_promoting_plain_catalog_name(self):
        a=reading('006/150');r=self.row(a,copy.deepcopy(a));ctx=f.notation_context(r)
        self.assertEqual(ctx['title_mechanic'],'prism_star_observed_by_both');self.assertTrue(ctx['base_title_catalog_correspondence']);self.assertFalse(ctx['catalog_mechanic_binding_established']);self.assertIsNone(f.title_interpretation(a)['canonical_candidate'])
        for k in ['identity_qualification_changed','physical_printing_verified','price_comparable']:self.assertFalse(ctx[k])
    def test_unknown_symbol_or_changed_anchor_is_not_prism_agreement(self):
        a=reading('006/150');b=reading('006/150',symbols=[dict(kind='unknown',after_text_part=0)])
        self.assertEqual(f.notation_context(self.row(a,b))['title_mechanic'],'unconfirmed_or_other')
        b=reading('006/150',parts=['シェイ','ミ'],symbols=[dict(kind='prism_star',after_text_part=0)])
        self.assertFalse(f.notation_context(self.row(a,b))['title_symbol_anchors_agree'])
    def test_multiple_fraction_candidates_never_assign_namespaces_or_print_runs(self):
        a=reading('017/103 01/30');b=reading('017/103');ctx=f.notation_context(self.row(a,b));self.assertEqual(ctx['number_scope_candidates'][0]['complete_fraction_candidates'],['017/103','01/30']);self.assertEqual(ctx['number_scope_candidates'][1]['complete_fraction_candidates'],[])
        self.assertEqual(ctx['number_layout'],'multiple_complete_fractions_observed');self.assertFalse(ctx['number_namespace_assignment_established']);self.assertFalse(ctx['print_run_quantity_established'])
        ctx=f.notation_context(self.row(reading('056/184; 057/184; 058/184; 059/184'),reading('056/184, 057/184, 058/184, 059/184')));self.assertEqual(len(ctx['number_scope_candidates'][0]['complete_fraction_candidates']),4)
    def test_incomplete_or_unrelated_number_text_is_never_completed(self):
        for text in ['017/103 01','017/103 price 01/30','017/103 01/30 extra',None]:
            ctx=f.notation_context(self.row(reading(text),reading(text)));self.assertEqual(ctx['number_layout'],'single_or_unparsed')

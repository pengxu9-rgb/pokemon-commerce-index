import copy,unittest
from pokemon_index import core,number_evidence,source_image_facts as facts,collector_journey,card_comparison

def reading(**kw):
    r=dict(title_text_parts=['基本','エネルギー'],title_symbols=[dict(kind='grass',after_text_part=0)],
        title_furigana='き ほん くさ',observed_number_text='009/M-P',hp=None,hp_status='absent',notes='source image only')
    r.update(kw);return r

class SourceImageFactTests(unittest.TestCase):
    def setUp(self):
        self.db=core.connect(':memory:');core.init_db(self.db)
        core.import_cards(self.db,[dict(language='ja',set_code='M-P',collector_number='009/M-P',variant=v,
            name='基本草エネルギー',provenance='tcgdex:'+('a'*40)+':data/test.ts:sha256:'+('b'*64),rights_reference='fixture',match_eligible=True) for v in ['normal','reverse']])
        self.cid='ja:M-P:009/M-P:normal';snap=number_evidence.snapshot(self.db,self.cid)
        src='https://www.pokemon-card.com/card-search/details.php/card/48332'
        reviews=[dict(actor=a,model_family=f,model_version=None,reviewed_at='2026-10-03T00:00:00Z',review_record_sha256=h*64,
            source_ref=src,image_sha256='c'*64,prior_verdicts_visible=seen,expected_catalog_context_visible=seen,reading=reading()) for a,f,h,seen in [('first','openai','d',True),('second','google','e',False)]]
        self.row=dict(schema=facts.SCHEMA,revision=1,card_id=self.cid,endpoint_snapshot=snap,identity_sha256=facts.supported_catalog.digest(snap),source_ref=src,image_sha256='c'*64,source_file_sha256='b'*64,pinned_source_hp=None,cohort_snapshot_sha256='f'*64,reviews=reviews,recorded_at='2026-10-03T00:01:00Z',**{k:False for k in facts.FALSE_CLAIMS})
        self.sign(self.row)
    def sign(self,r):r['event_id']=facts.event_id(r);return r
    def tearDown(self):self.db.close()

    def test_symbol_name_preserves_literal_text_and_context_flags_without_upgrading_numbers(self):
        facts.import_evidence(self.db,[self.row]);ctx=core.catalog_card_internal(self.db,self.cid)['source_image_facts']
        self.assertEqual(ctx['name_status'],'symbol_correspondence_advisory')
        self.assertEqual(ctx['title_interpretations'][0]['literal_text'],'基本エネルギー')
        self.assertEqual(ctx['title_interpretations'][0]['canonical_candidate'],'基本草エネルギー')
        self.assertTrue(ctx['reviews'][0]['prior_verdicts_visible'])
        for k in facts.FALSE_CLAIMS:self.assertIs(ctx[k],False)
        self.assertEqual(number_evidence.status(self.db)['number_reading_events'],0)
        self.assertIsNone(facts.context(self.db,'ja:M-P:009/M-P:reverse'))

    def test_wrong_missing_or_unknown_symbol_pronunciation_does_not_expand_catalog_name(self):
        for mutate in [dict(title_furigana=None),dict(title_furigana='きほんほのお'),dict(title_symbols=[dict(kind='unknown',after_text_part=0)])]:
            r=reading(**mutate);self.assertIsNone(facts.title_interpretation(r)['canonical_candidate'])
        self.assertIsNone(facts.title_interpretation(reading(title_text_parts=['別名','エネルギー']))['canonical_candidate'])

    def test_expanded_kanji_is_not_agreement_with_literal_symbol_title(self):
        r=copy.deepcopy(self.row);r['reviews'][1]['reading']=reading(title_text_parts=['基本草エネルギー'],title_symbols=[],title_furigana=None)
        self.sign(r);facts.import_evidence(self.db,[r]);self.assertEqual(facts.context(self.db,self.cid)['name_status'],'unconfirmed')

    def test_hp_conflict_is_reported_without_rewriting_source_or_creating_price_approval(self):
        r=copy.deepcopy(self.row);r['pinned_source_hp']=80
        for review in r['reviews']:review['reading']=reading(hp=100,hp_status='visible')
        self.sign(r);facts.import_evidence(self.db,[r]);ctx=facts.context(self.db,self.cid)
        self.assertEqual(ctx['observed_hp'],100);self.assertEqual(ctx['pinned_source_hp'],80)
        self.assertEqual(ctx['warnings'],['source_hp_conflict'])
        comp=card_comparison.compare(self.db,dict(left=dict(card_id=self.cid),right=dict(card_id='ja:M-P:009/M-P:reverse')))
        self.assertIn('source_image_metadata_resolution',comp['required_evidence']);self.assertFalse(comp['price_comparable'])
        self.assertEqual(number_evidence.snapshot(self.db,self.cid),r['endpoint_snapshot'])

    def test_missing_hp_disagreement_and_source_unknown_are_distinct(self):
        r=copy.deepcopy(self.row)
        self.assertEqual(facts.outcomes(r)['hp_status'],'no_hp_observed')
        r['reviews'][0]['reading']=reading(hp_status='unreadable')
        self.assertEqual(facts.outcomes(r)['hp_status'],'hp_unconfirmed')
        for review in r['reviews']:review['reading']=reading(hp=70,hp_status='visible')
        self.assertEqual(facts.outcomes(r)['hp_status'],'source_hp_unknown')

    def test_source_drift_hides_normalization_and_hp_interpretations(self):
        facts.import_evidence(self.db,[self.row]);self.db.execute('UPDATE card SET name=? WHERE card_id=?',('changed',self.cid))
        ctx=facts.context(self.db,self.cid);self.assertFalse(ctx['current_endpoint']);self.assertEqual(ctx['title_interpretations'],[])
        self.assertEqual(facts.status(self.db)['stale_source_image_facts'],1)

    def test_substitution_overclaims_and_future_review_are_rejected(self):
        mutations=[lambda r:r['reviews'][1].update(image_sha256='a'*64),lambda r:r.update(source_file_sha256='a'*64),lambda r:r.update(independent_review_agreement_established=True),lambda r:r['reviews'][1].update(reviewed_at='2027-01-01T00:00:00Z'),lambda r:r['reviews'][1].update(model_family='openai')]
        for mutate in mutations:
            r=copy.deepcopy(self.row);mutate(r);self.sign(r)
            with self.assertRaises(ValueError):facts.import_evidence(self.db,[r])

    def test_null_boolean_hp_and_title_symbol_positions_are_checked(self):
        for r in [reading(hp=True,hp_status='visible'),reading(hp=100),reading(title_symbols=[dict(kind='grass',after_text_part=2)]),reading(title_symbols=[dict(kind='grass',after_text_part=0)]*2)]:
            with self.assertRaises(ValueError):facts.validate_reading(r)

    def test_append_only_idempotent_heads_and_atomic_revision_gate(self):
        before=collector_journey.catalog_revision(self.db)
        bad=copy.deepcopy(self.row);bad['revision']=3;self.sign(bad)
        with self.assertRaises(ValueError):facts.import_evidence(self.db,[self.row,bad])
        self.assertEqual(facts.status(self.db)['source_image_fact_events'],0)
        facts.import_evidence(self.db,[self.row,self.row]);self.assertEqual(facts.status(self.db)['source_image_fact_events'],1)
        self.assertNotEqual(collector_journey.catalog_revision(self.db),before)

    def test_model_response_extra_claims_and_wrong_version_are_rejected(self):
        from scripts.review_source_image_facts import parse,MODEL
        import json
        response=dict(modelVersion=MODEL,candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(reading()))]))])
        self.assertEqual(parse(response)[0]['hp_status'],'absent')
        response['modelVersion']='wrong'
        with self.assertRaises(ValueError):parse(response)
        with self.assertRaises(ValueError):facts.validate_reading(reading(price_comparable=True))

    def test_typographic_fragments_preserve_correspondence_without_removing_symbols(self):
        r=copy.deepcopy(self.row);r['endpoint_snapshot']['name']='Rowlet & Alolan Exeggutor GX'
        r['reviews'][0]['reading']=reading(title_text_parts=['Rowlet & Alolan Exeggutor GX'],title_symbols=[])
        r['reviews'][1]['reading']=reading(title_text_parts=['Rowlet &','Alolan Exeggutor','GX'],title_symbols=[])
        self.assertEqual(facts.outcomes(r)['name_status'],'literal_correspondence_advisory')
        split=reading(title_text_parts=['基','本','エネルギー'],title_symbols=[dict(kind='grass',after_text_part=1)])
        self.assertEqual(facts.title_structure(split),facts.title_structure(reading()))
        wrong=reading(title_text_parts=['基本','エネルギー'],title_symbols=[dict(kind='grass',after_text_part=1)])
        self.assertNotEqual(facts.title_structure(wrong),facts.title_structure(reading()))

    def test_trailing_prism_symbol_is_retained_without_canonical_name_approval(self):
        r=reading(title_text_parts=['シェイミ'],title_symbols=[dict(kind='prism_star',after_text_part=0)])
        facts.validate_reading(r)
        self.assertIsNone(facts.title_interpretation(r)['canonical_candidate'])
        self.assertEqual(facts.title_structure(r),[('text','シェイミ'),('symbol','prism_star')])

    def test_typographic_apostrophes_do_not_merge_different_owners_or_mechanics(self):
        a=reading(title_text_parts=['Erika’s Vileplume ex'],title_symbols=[])
        b=reading(title_text_parts=["Erika's Vileplume",'ex'],title_symbols=[])
        self.assertEqual(facts.title_structure(a),facts.title_structure(b))
        self.assertNotEqual(facts.title_structure(a),facts.title_structure(reading(title_text_parts=["Ethan's Vileplume ex"],title_symbols=[])))
        self.assertNotEqual(facts.title_structure(a),facts.title_structure(reading(title_text_parts=["Erika's Vileplume GX"],title_symbols=[])))
        self.assertEqual(a['title_text_parts'],['Erika’s Vileplume ex'])

    def test_mixed_case_ex_ocr_suffix_preserves_legacy_ex_and_other_mechanics(self):
        a=reading(title_text_parts=['Mega Meganium eX'],title_symbols=[])
        b=reading(title_text_parts=['Mega Meganium','ex'],title_symbols=[])
        self.assertEqual(facts.title_structure(a),facts.title_structure(b))
        for title in ['Mega Meganium EX','Mega Meganium GX','Mega Meganium V','Mega Meganium','Other Meganium ex']:
            self.assertNotEqual(facts.title_structure(a),facts.title_structure(reading(title_text_parts=[title],title_symbols=[])))
        self.assertEqual(a['title_text_parts'],['Mega Meganium eX'])

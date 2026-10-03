import copy
import unittest
from pokemon_index import core, number_evidence, number_graph, card_comparison, collector_journey


class NumberEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.db = core.connect(':memory:'); core.init_db(self.db)
        core.import_cards(self.db, [dict(language='en', set_code='SVP', collector_number='037/225',
            variant=v, name='Cleffa', provenance='fixture', rights_reference='fixture', match_eligible=True)
            for v in ['normal', 'holo_set_logo']])
        self.cid = 'en:SVP:037/225:holo_set_logo'
        snap = number_evidence.snapshot(self.db, self.cid)
        source = 'https://assets.tcgdex.net/en/sv/svp/037/high.webp'
        reviews = [dict(actor=actor, model_family=family, model_version=None,
            reviewed_at='2026-10-02T00:00:00Z', review_record_sha256=sha*64,
            source_ref=source, image_sha256='a'*64, observed_number_text='037',
            observed_name='Cleffa', prior_verdicts_visible=False)
            for actor, family, sha in [('first','openai','b'),('second','google','c')]]
        self.row = dict(schema=number_evidence.SCHEMA, revision=1, card_id=self.cid,
            endpoint_snapshot=snap, identity_sha256=number_evidence.supported_catalog.digest(snap),
            source_ref=source, image_sha256='a'*64,
            review_groups=[dict(candidate_id='fixture', cohort_snapshot_sha256='d'*64, reviews=reviews)],
            status='catalog_denominator_not_observed', recorded_at='2026-10-02T00:01:00Z',
            **{k: False for k in number_evidence.FALSE_CLAIMS})
        self.sign(self.row)

    def sign(self, row):
        row['event_id'] = number_evidence.event_id(row)
        return row

    def tearDown(self):
        self.db.close()

    def test_promo_reading_preserves_coordinate_without_inventing_denominator(self):
        number_evidence.import_evidence(self.db, [self.row])
        ctx = number_graph.card_number_context(self.db, self.cid)
        self.assertEqual(ctx['catalog_number'], '037/225')
        self.assertEqual(ctx['printed_number_semantics'], 'legacy_catalog_coordinate_not_visual_evidence')
        observed = ctx['observed_printed_number']
        self.assertEqual(observed['observed_number_texts'], ['037'])
        self.assertFalse(observed['printed_denominator_observed'])
        for k in number_evidence.FALSE_CLAIMS: self.assertIs(observed[k], False)
        self.assertEqual(self.db.execute('SELECT collector_number FROM card WHERE card_id=?', (self.cid,)).fetchone()[0], '037/225')
        self.assertEqual(self.db.execute('SELECT count(*) FROM card_relationship_assertion').fetchone()[0], 0)

    def test_missing_evidence_is_not_generated_from_metadata(self):
        self.assertIsNone(number_graph.card_number_context(self.db, self.cid)['observed_printed_number'])
        self.assertEqual(number_evidence.status(self.db)['number_reading_events'], 0)

    def test_same_coordinate_sibling_does_not_inherit_number_reading(self):
        number_evidence.import_evidence(self.db, [self.row])
        self.assertIsNone(number_evidence.context(self.db, 'en:SVP:037/225:normal'))
        result = card_comparison.compare(self.db, dict(left=dict(card_id=self.cid),
            right=dict(card_id='en:SVP:037/225:normal')))
        self.assertEqual(len(result['left']['observed_printed_numbers']), 1)
        self.assertEqual(result['right']['observed_printed_numbers'], [])
        self.assertFalse(result['numbering']['printed_number_equivalence_established'])
        self.assertFalse(result['price_comparable'])

    def test_numeric_zero_format_does_not_erase_prefixes_or_fill_denominators(self):
        self.assertEqual(number_evidence.classify('005/073', ['005/073','5/73']), 'catalog_text_observed')
        self.assertEqual(number_evidence.classify('037/225', ['037','37']), 'catalog_denominator_not_observed')
        self.assertEqual(number_evidence.classify('SWSH093/307', ['093','093']), 'different_text_observed')
        self.assertEqual(number_evidence.classify('046/M-P', ['046/M-P','46/M-P']), 'catalog_text_observed')
        self.assertEqual(number_evidence.classify('TG10/TG30', ['TG10/TG30','TG10/TG30']), 'catalog_text_observed')

    def test_adjacent_rarity_tokens_preserve_raw_readings_without_filling_numbers(self):
        self.assertEqual(number_evidence.classify('003/187',['003/187','003/187 RR']), 'catalog_text_observed')
        self.assertEqual(number_evidence.classify('001/165',['001/165 C','1/165']), 'catalog_text_observed')
        for text in ['003 RR','003/187 UNKNOWN','003/187 RR extra','003/188 RR','TG03/TG30 RR']:
            self.assertNotEqual(number_evidence.classify('003/187',['003/187',text]), 'catalog_text_observed')
        r=copy.deepcopy(self.row)
        r['review_groups'][0]['reviews'][0]['observed_number_text']='037/225 RR'
        r['review_groups'][0]['reviews'][1]['observed_number_text']='037/225'
        r['status']='catalog_text_observed';self.sign(r);number_evidence.import_evidence(self.db,[r])
        context=number_evidence.context(self.db,self.cid)
        self.assertIn('037/225 RR',context['observed_number_texts'])
        for key in number_evidence.FALSE_CLAIMS:self.assertFalse(context[key])

    def test_disagreement_and_unreadable_text_are_held(self):
        for text in ['038','unclear?']:
            row = copy.deepcopy(self.row)
            row['review_groups'][0]['reviews'][1]['observed_number_text'] = text
            row['status'] = 'reading_hold'; self.sign(row)
            number_evidence.import_evidence(self.db, [row])
            ctx = number_evidence.context(self.db, self.cid)
            self.assertFalse(ctx['visible_text_agreement']); self.assertEqual(ctx['observed_number_texts'], [])
            self.db.execute('DELETE FROM card_number_reading_evidence'); self.db.commit()

    def test_source_snapshot_drift_withholds_prior_reading(self):
        number_evidence.import_evidence(self.db, [self.row])
        self.db.execute('UPDATE card SET provenance=? WHERE card_id=?', ('new-source',self.cid))
        ctx = number_evidence.context(self.db, self.cid)
        self.assertEqual(ctx['status'], 'stale_endpoint'); self.assertEqual(ctx['observed_number_texts'], [])
        self.assertEqual(number_evidence.status(self.db)['stale_number_readings'], 1)

    def test_import_rejects_stale_identity_or_substituted_review_asset(self):
        bad = copy.deepcopy(self.row); bad['review_groups'][0]['reviews'][1]['image_sha256'] = 'f'*64; self.sign(bad)
        with self.assertRaisesRegex(ValueError, 'image differs'): number_evidence.import_evidence(self.db, [bad])
        self.db.execute('UPDATE card SET name=? WHERE card_id=?', ('changed',self.cid))
        with self.assertRaisesRegex(ValueError, 'stale'): number_evidence.import_evidence(self.db, [self.row])

    def test_single_correlated_or_prior_visible_reviews_do_not_qualify(self):
        for mutate in [lambda r:r['review_groups'][0].update(reviews=r['review_groups'][0]['reviews'][:1]),
                       lambda r:r['review_groups'][0]['reviews'][1].update(model_family='openai'),
                       lambda r:r['review_groups'][0]['reviews'][1].update(actor='FIRST'),
                       lambda r:r['review_groups'][0]['reviews'][1].update(prior_verdicts_visible=True)]:
            row=copy.deepcopy(self.row); mutate(row); self.sign(row)
            with self.assertRaises(ValueError): number_evidence.import_evidence(self.db, [row])

    def test_outcome_and_permission_overclaims_rejected(self):
        for mutate in [lambda r:r.update(status='catalog_text_observed')]+[
                lambda r,k=k:r.update({k:True}) for k in number_evidence.FALSE_CLAIMS]:
            row=copy.deepcopy(self.row); mutate(row); self.sign(row)
            with self.assertRaises(ValueError): number_evidence.import_evidence(self.db, [row])

    def test_source_host_and_paths_are_bounded(self):
        for source in ['https://assets.tcgdex.net.evil/en/sv/svp/037/high.webp',
                       'https://assets.tcgdex.net/en/sv/svp/037/high.webp?secret=x',
                       'https://assets.tcgdex.net/en/../037/high.webp']:
            row=copy.deepcopy(self.row); row['source_ref']=source
            for r in row['review_groups'][0]['reviews']: r['source_ref']=source
            self.sign(row)
            with self.assertRaises(ValueError): number_evidence.import_evidence(self.db, [row])

    def test_idempotence_revisions_and_new_hold_supersede_old_reading(self):
        number_evidence.import_evidence(self.db, [self.row,self.row])
        self.assertEqual(number_evidence.status(self.db)['number_reading_events'], 1)
        newer=copy.deepcopy(self.row); newer['revision']=3; self.sign(newer)
        with self.assertRaisesRegex(ValueError, 'consecutive'): number_evidence.import_evidence(self.db, [newer])
        newer['revision']=2; newer['review_groups'][0]['reviews'][1]['observed_number_text']='038'
        newer['status']='reading_hold'; self.sign(newer); number_evidence.import_evidence(self.db,[newer])
        self.assertEqual(number_evidence.context(self.db,self.cid)['observed_number_texts'], [])
        self.assertEqual(number_evidence.status(self.db)['number_reading_events'], 2)

    def test_atomic_batch_does_not_leave_partial_import(self):
        bad=copy.deepcopy(self.row); bad['revision']=3; self.sign(bad)
        with self.assertRaises(ValueError): number_evidence.import_evidence(self.db,[self.row,bad])
        self.assertEqual(number_evidence.status(self.db)['number_reading_events'],0)

    def test_journey_revision_changes_with_number_evidence(self):
        before=collector_journey.catalog_revision(self.db)
        number_evidence.import_evidence(self.db,[self.row])
        self.assertNotEqual(collector_journey.catalog_revision(self.db),before)

    def test_future_review_timestamp_rejected(self):
        bad=copy.deepcopy(self.row); bad['review_groups'][0]['reviews'][1]['reviewed_at']='2027-10-02T00:00:00Z'; self.sign(bad)
        with self.assertRaisesRegex(ValueError,'predates'): number_evidence.import_evidence(self.db,[bad])

    def test_unreadable_number_is_null_and_never_backfilled(self):
        row=copy.deepcopy(self.row)
        row['review_groups'][0]['reviews'][1]['observed_number_text']=None
        row['status']='reading_hold';self.sign(row);number_evidence.import_evidence(self.db,[row])
        ctx=number_evidence.context(self.db,self.cid)
        self.assertEqual(ctx['observed_number_texts'],[])
        self.assertIsNone(ctx['review_groups'][0]['reviews'][1]['observed_number_text'])

    def test_matching_number_with_wrong_or_missing_name_remains_held(self):
        for name in ['Pikachu',None]:
            row=copy.deepcopy(self.row);row['review_groups'][0]['reviews'][1]['observed_name']=name
            row['status']='reading_hold';self.sign(row);number_evidence.import_evidence(self.db,[row])
            self.assertFalse(number_evidence.context(self.db,self.cid)['visible_text_agreement'])
            self.db.execute('DELETE FROM card_number_reading_evidence');self.db.commit()

    def test_canonical_energy_name_cannot_be_inserted_in_place_of_visible_symbol(self):
        self.assertEqual(number_evidence.classify('009/M-P',['009/M-P','009/M-P'],
            expected_name='基本草エネルギー',observed_names=['基本エネルギー','基本エネルギー']),'reading_hold')

    def test_catalog_number_preserves_source_case_separate_from_normalized_legacy_field(self):
        core.import_cards(self.db,[dict(language='en',set_code='MEP',collector_number='001/mep',
            variant='normal',name='Meganium',provenance='fixture',rights_reference='fixture')])
        ctx=number_graph.card_number_context(self.db,'en:MEP:001/mep:normal')
        self.assertEqual(ctx['catalog_number'],'001/mep')
        self.assertEqual(ctx['printed_number'],'001/MEP')

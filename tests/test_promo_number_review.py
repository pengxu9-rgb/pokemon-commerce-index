import copy,json,unittest
from scripts.review_promo_numbers_vertex import MODEL,parse


class PromoNumberReviewTests(unittest.TestCase):
    def response(self,reading):
        return dict(modelVersion=MODEL,candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(reading))]))])

    def reading(self):
        return dict(observed_name='Ho-Oh',observed_number_text='HGSS01',reading_status='readable',number_locator='bottom right',uncertainties='No slash suffix is visible.')

    def test_single_promo_code_is_not_given_an_inventory_denominator(self):
        reading,_=parse(self.response(self.reading()));self.assertEqual(reading['observed_number_text'],'HGSS01')

    def test_actual_unreadable_output_remains_null(self):
        r=self.reading();r.update(observed_number_text=None,observed_name=None,reading_status='unreadable')
        parsed,_=parse(self.response(r));self.assertIsNone(parsed['observed_number_text'])

    def test_incomplete_or_substituted_model_response_cannot_qualify(self):
        response=self.response(self.reading())
        for key,value in [('modelVersion','another-model'),('finishReason','MAX_TOKENS')]:
            bad=copy.deepcopy(response)
            if key=='modelVersion':bad[key]=value
            else:bad['candidates'][0][key]=value
            with self.assertRaises(ValueError):parse(bad)

    def test_readable_claim_with_missing_text_or_extra_identity_approval_rejected(self):
        r=self.reading();r['observed_number_text']=None
        with self.assertRaises(ValueError):parse(self.response(r))
        r=self.reading();r['catalog_identity_confirmed']=True
        with self.assertRaises(ValueError):parse(self.response(r))

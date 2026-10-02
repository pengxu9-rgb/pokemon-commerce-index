"""Synthetic parsing/provenance guards, not measured image accuracy."""
import json
import unittest
from scripts.review_relationship_expansion_vertex import parse, MODEL
from scripts.compile_relationship_identity_reviews import compile_reviews
from tests import test_relationship_identity_review as fixtures


class VertexExpansionTests(unittest.TestCase):
    def setUp(self):
        self.frozen=dict(endpoints=[dict(language='ja',name='ガラル マッスグマ',collector_number='060/100'),
                                   dict(language='en',name='Galarian Linoone',collector_number='160/264')])
        self.finding=dict(artwork_decision='same',rationale='Synthetic identical scene',identity_match='match',
            readings=[dict(side='ja',name='ガラルマッスグマ',collector_number='60/100'),
                      dict(side='en',name='Galarian Linoone',collector_number='160/264')],uncertainties='Stock images only.')

    def response(self,finding=None,**patch):
        return dict(modelVersion=MODEL,candidates=[dict(finishReason='STOP',content=dict(parts=[dict(text=json.dumps(finding or self.finding))]))],**patch)

    def test_both_actual_readings_need_matching_names_and_numbers(self):
        self.assertTrue(parse(self.response(),self.frozen)[1])
        wrong=json.loads(json.dumps(self.finding));wrong['readings'][0]['collector_number']='61/100'
        self.assertFalse(parse(self.response(wrong),self.frozen)[1])
        wrong['readings'][0]['collector_number']='60/100';wrong['readings'][1]['name']='Different card'
        self.assertFalse(parse(self.response(wrong),self.frozen)[1])

    def test_incomplete_duplicate_overclaimed_and_wrong_model_responses_rejected(self):
        malformed=[]
        malformed.append({**self.finding,'price_comparable':True})
        malformed.append({**self.finding,'readings':[self.finding['readings'][0]]})
        malformed.append({**self.finding,'readings':[self.finding['readings'][0]]*2})
        for value in malformed:
            with self.assertRaises(ValueError):parse(self.response(value),self.frozen)
        response=self.response();response['modelVersion']='another-model'
        with self.assertRaisesRegex(ValueError,'model version'):parse(response,self.frozen)
        response=self.response();response['candidates'][0]['finishReason']='MAX_TOKENS'
        with self.assertRaisesRegex(ValueError,'incomplete'):parse(response,self.frozen)

    def test_leading_zero_formatting_does_not_invent_missing_promo_denominator(self):
        self.frozen['endpoints'][1].update(name='Cleffa',collector_number='037/225')
        self.finding['readings'][1].update(name='Cleffa',collector_number='037')
        self.assertFalse(parse(self.response(),self.frozen)[1])
        self.frozen['endpoints'][1].update(name='Breloom',collector_number='005/073')
        self.finding['readings'][1].update(name='Breloom',collector_number='5/73')
        self.assertTrue(parse(self.response(),self.frozen)[1])

    def test_compiler_keeps_two_actual_model_provenance_and_hashes(self):
        fixture=fixtures.RelationshipIdentityReviewTests();fixture.setUp()
        try:
            a={**fixture.a,'model_family':'openai','model_version':None}
            b={**fixture.b,'model_family':'google','model_version':MODEL,'protocol_sha256':'a'*64,'response_sha256':'b'*64}
            row=compile_reviews(fixture.db,{fixture.cid:fixture.frozen},{fixture.cid:a},{fixture.cid:b})[0]
            evidence=json.loads(row['evidence_ref'])
            self.assertIn('Different recorded model families',evidence['independence_scope'])
            self.assertEqual(evidence['first_review']['model_family'],'openai')
            self.assertEqual(evidence['second_review']['model_version'],MODEL)
            self.assertIn('review_record_sha256',evidence['second_review'])
            self.assertFalse(evidence['price_comparable'])
            with self.assertRaisesRegex(ValueError,'both reviews need model-family'):
                compile_reviews(fixture.db,{fixture.cid:fixture.frozen},{fixture.cid:a},{fixture.cid:fixture.b})
        finally:fixture.tearDown()

import copy
import unittest
from scripts.verify_collector_cloud import graph_semantic_response,catalog_card_semantic_response


class CloudGraphComparisonTests(unittest.TestCase):
    def setUp(self):
        self.response={'official_metadata':{'fetched_at':'2026-10-01T00:00:00+00:00'},
            'ai_artwork_candidates':[{'asserted_by':'ai-artwork-review-v1',
                'review_status':'proposed','asserted_at':'2026-10-01T01:00:00+00:00',
                'assertion_id':'fixed','evidence_ref':'fixed evidence','price_comparable':False}]}

    def test_import_time_is_the_only_excluded_field(self):
        other=copy.deepcopy(self.response)
        other['ai_artwork_candidates'][0]['asserted_at']='2026-10-01T02:00:00+00:00'
        self.assertEqual(graph_semantic_response(self.response),graph_semantic_response(other))
        self.assertIn('asserted_at',self.response['ai_artwork_candidates'][0])
        other['ai_artwork_candidates'][0]['evidence_ref']='different evidence'
        self.assertNotEqual(graph_semantic_response(self.response),graph_semantic_response(other))

    def test_official_retrieval_time_remains_bound(self):
        other=copy.deepcopy(self.response)
        other['official_metadata']['fetched_at']='2026-10-01T02:00:00+00:00'
        self.assertNotEqual(graph_semantic_response(self.response),graph_semantic_response(other))

    def test_non_proposed_assertion_time_remains_bound(self):
        self.response['ai_artwork_candidates'][0]['review_status']='verified'
        other=copy.deepcopy(self.response)
        other['ai_artwork_candidates'][0]['asserted_at']='2026-10-01T02:00:00+00:00'
        self.assertNotEqual(graph_semantic_response(self.response),graph_semantic_response(other))


class CloudCatalogCardComparisonTests(unittest.TestCase):
    def setUp(self):
        self.response=dict(card=dict(card_id='ja:FIX:001/100:holo',provenance='bound source'),
            rarity_correction=dict(card_id='ja:FIX:001/100:holo',corrected_rarity='UR',
                provenance='bound rarity evidence',applied_at='2026-10-02T01:00:00Z'),
            source_corrections=dict(recorded_at='2026-10-02T00:00:00Z'))

    def test_only_application_time_is_excluded_original_values_retained(self):
        other=copy.deepcopy(self.response)
        other['rarity_correction']['applied_at']='2026-10-02T02:00:00Z'
        self.assertEqual(catalog_card_semantic_response(self.response),catalog_card_semantic_response(other))
        self.assertIn('applied_at',self.response['rarity_correction'])
        other['rarity_correction']['corrected_rarity']='SR'
        self.assertNotEqual(catalog_card_semantic_response(self.response),catalog_card_semantic_response(other))

    def test_evidence_creation_and_card_binding_are_not_ignored(self):
        other=copy.deepcopy(self.response)
        other['source_corrections']['recorded_at']='2026-10-02T02:00:00Z'
        self.assertNotEqual(catalog_card_semantic_response(self.response),catalog_card_semantic_response(other))
        other['rarity_correction']['card_id']='different'
        with self.assertRaisesRegex(ValueError,'outside the returned card'):
            catalog_card_semantic_response(other)

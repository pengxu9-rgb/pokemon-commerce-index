import copy
import unittest
from scripts.verify_collector_cloud import graph_semantic_response


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

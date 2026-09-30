import unittest
from scripts import vertex_public_question_facts_v7 as extractor
from tests import test_public_question_facts_v6 as previous


class PublicFactsV7Tests(unittest.TestCase):
    def fixture(self):
        question, answer = previous.PublicQuestionFactsV6Tests().answer()
        answer['facts'].update(merchant_refs=[], merchant_location=None, tcg_scope='pokemon_tcg',
                               seller_tasks=[], cost_basis=None)
        answer['evidence_spans'].update(merchant_refs=[], merchant_location=None,
                                       tcg_scope='Pokémon cards', seller_tasks=[], cost_basis=None)
        return question, answer

    def test_whole_collection_sale_is_a_lot_without_implying_bulk(self):
        question, answer = self.fixture()
        question['question'] = 'Where can I sell my collection all at once?'
        answer['facts'].update(primary_goal='channel_choice', tcg_scope='unknown',
                               sale_scope='my collection', sale_formats=['lot'])
        answer['evidence_spans'].update(goal='Where can I sell', tcg_scope=None,
                                       sale_scope='my collection', sale_formats=['all at once'])
        self.assertEqual(extractor.validate_answer(answer, question)[0]['sale_formats'], ['lot'])
        answer['facts']['sale_formats'] = ['bulk']
        with self.assertRaisesRegex(ValueError, 'sale_formats'):
            extractor.validate_answer(answer, question)

    def test_invented_store_or_location_is_rejected(self):
        question, answer = self.fixture()
        answer['facts'].update(merchant_refs=['BOOKOFF'], merchant_ref='BOOKOFF')
        answer['evidence_spans'].update(merchant_refs=['BOOKOFF'], merchant_ref='BOOKOFF')
        with self.assertRaises(ValueError):
            extractor.validate_answer(answer, question)
        question, answer = self.fixture()
        answer['facts']['merchant_location'] = 'Tokyo'
        answer['evidence_spans']['merchant_location'] = 'Tokyo'
        with self.assertRaisesRegex(ValueError, 'merchant_location'):
            extractor.validate_answer(answer, question)

    def test_new_task_spans_and_scope_require_literal_evidence(self):
        question, answer = self.fixture()
        answer['facts']['seller_tasks'] = ['merchant_discovery']
        answer['evidence_spans']['seller_tasks'] = ['find a Tokyo store']
        with self.assertRaisesRegex(ValueError, 'seller_tasks'):
            extractor.validate_answer(answer, question)

    def test_prompt_preserves_location_multistore_and_profit_boundaries(self):
        question, _ = self.fixture()
        prompt = extractor._request(question)[0]['contents'][0]['parts'][0]['text']
        for text in ('merchant_discovery', 'ALL explicitly', 'separate from destination',
                     'proposed purchase price is not a paid', 'all at once means lot'):
            self.assertIn(text, prompt)

    def test_owned_collection_does_not_prove_lot_selling(self):
        question, answer = self.fixture()
        question['question'] = 'I own my collection all at once and want an opinion.'
        answer['facts'].update(primary_goal='collecting_preference', tcg_scope='unknown',
                               sale_scope='my collection', sale_formats=['lot'])
        answer['evidence_spans'].update(goal='want an opinion', tcg_scope=None,
                                       sale_scope='my collection', sale_formats=['all at once'])
        with self.assertRaisesRegex(ValueError, 'explicit selling'):
            extractor.validate_answer(answer, question)

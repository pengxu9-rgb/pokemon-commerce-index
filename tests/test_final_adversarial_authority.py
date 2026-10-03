"""Independent final review: clarification is a durable selection boundary.

The production author does not own these tests. Fixtures use source-declared
synthetic catalog identities, and make no physical-copy or market claims.
"""
import unittest

import test_independent_recommendation_review as fixture


class FinalAdversarialAuthorityTests(unittest.TestCase):
    setUp = fixture.IndependentRecommendationReview.setUp
    tearDown = fixture.IndependentRecommendationReview.tearDown
    replay = fixture.IndependentRecommendationReview.replay
    start = fixture.IndependentRecommendationReview.start

    def assert_closed(self, turns):
        result = self.replay(turns)
        self.assertFalse(result['selection_allowed'])
        self.assertIsNone(result['target_intent'])
        return result

    def negated(self):
        return self.start() + [dict(type='reply', text='I do not like Pikachu')]

    def test_common_exclusion_wording_never_becomes_positive_taste(self):
        for wording in ['except Pikachu', 'other than Pikachu', 'anything but Pikachu']:
            with self.subTest(wording=wording):
                result = self.assert_closed([dict(type='ask', question='Recommend Japanese cards ' + wording)])
                self.assertNotIn(25, result['preferences'].get('collecting', {}).get('preferred_dex_ids', []))

    def test_unresolved_negation_rejects_direct_select_and_comparison_focus(self):
        turns = self.negated()
        self.assert_closed(turns)
        with self.assertRaises(ValueError):
            self.replay(turns + [dict(type='select', card_id=fixture.B)])
        compared = turns + [dict(type='compare', left_card_id=fixture.A, right_card_id=fixture.B),
                            dict(type='choose_comparison', side='right', card_id=fixture.B)]
        try:
            self.assert_closed(compared)
        except ValueError:
            pass

    def test_unrelated_actions_cannot_discard_pending_negation(self):
        actions = [
            dict(type='refine', scope={'language': 'ja'}),
            dict(type='reply', text='Japanese'),
            dict(type='preferences', preferences={'collecting': {'mode': 'explore'}}),
            dict(type='preferences', preferences={'collecting': {'subjective_notes': []}}),
            dict(type='preferences', preferences={'budget_minor': 5000, 'currency': 'USD'}),
            dict(type='feedback', card_id=fixture.B, reaction='like'),
            dict(type='inventory', owned_items=[]),
            dict(type='clear_target'),
            dict(type='page', offset=1),
        ]
        for action in actions:
            with self.subTest(action=action):
                turns = self.negated() + [action]
                try:
                    self.assert_closed(turns)
                except ValueError:
                    # Rejecting an action that would obscure unresolved intent
                    # is also a fail-closed outcome.
                    continue

    def test_yes_with_single_candidate_does_not_resolve_negation(self):
        turns = self.start() + [dict(type='refine', scope={'set_code': 'AAA', 'collector_number': '002/100'}),
                               dict(type='reply', text='I do not like Pikachu')]
        self.assert_closed(turns)
        try:
            self.assert_closed(turns + [dict(type='reply', text='yes')])
        except ValueError:
            pass

    def test_explicit_relevant_choice_can_recover_pending_negation(self):
        turns = self.negated() + [dict(type='preferences', preferences={'collecting': {
            'preferred_dex_ids': [151], 'excluded_dex_ids': [25]}})]
        result = self.replay(turns)
        self.assertTrue(result['selection_allowed'])
        self.assertEqual([c['card_id'] for c in result['candidate_cards']], [fixture.MEW])
        chosen = self.replay(turns + [dict(type='select', card_id=fixture.MEW)])
        self.assertEqual(chosen['target_intent']['card_id'], fixture.MEW)
        self.assertFalse(chosen['purchase_ready'])

    def test_ambiguous_hard_release_reply_survives_unrelated_updates(self):
        turns = self.start() + [dict(type='reply', text='Only from AAA or BBB')]
        self.assert_closed(turns)
        for action in [dict(type='refine', scope={'language': 'ja'}),
                       dict(type='reply', text='Japanese'),
                       dict(type='feedback', card_id=fixture.B, reaction='like'),
                       dict(type='preferences', preferences={'collecting': {'mode': 'explore'}}),
                       dict(type='inventory', owned_items=[]),
                       dict(type='page', offset=1), dict(type='clear_target')]:
            with self.subTest(action=action):
                try:
                    self.assert_closed(turns + [action])
                except ValueError:
                    continue
        with self.assertRaises(ValueError):
            self.replay(turns + [dict(type='select', card_id=fixture.B)])
        resolved = self.replay(turns + [dict(type='refine', scope={'set_code': 'AAA'})])
        self.assertTrue(resolved['selection_allowed'])
        self.assertTrue(all(c['set_code'] == 'AAA' for c in resolved['candidate_cards']))

    def test_compound_negation_does_not_erase_simultaneous_hard_release(self):
        for release in ['AAA or BBB', 'AAA']:
            with self.subTest(release=release):
                turns = self.start() + [dict(type='reply', text='I do not like Mew; only from ' + release),
                    dict(type='preferences', preferences={'collecting': {
                        'preferred_dex_ids': [25],
                        'preferred_releases': [{'language': 'ja', 'set_code': 'AAA'}]}})]
                result = self.replay(turns)
                self.assertFalse(result['selection_allowed'] and any(
                    c['set_code'] != 'AAA' for c in result['candidate_cards']))
                resolved = self.replay(turns + [dict(type='refine', scope={'set_code': 'AAA'})])
                self.assertTrue(resolved['selection_allowed'])
                self.assertTrue(all(c['set_code'] == 'AAA' for c in resolved['candidate_cards']))


if __name__ == '__main__':
    unittest.main()

import unittest
from pokemon_index import question_routing_v7 as routing
from tests.test_question_routing_v6 import facts as previous, COHORT


def facts(goal='merchant_acceptance', refs=None, location=None, tasks=None,
          scope='pokemon_tcg', **kwargs):
    refs = [] if refs is None else refs
    row = previous(goal, **kwargs)
    row['merchant_ref'] = refs[0] if len(refs) == 1 else None
    return {**row, 'merchant_refs': refs, 'merchant_location': location,
            'tcg_scope': scope, 'seller_tasks': [] if tasks is None else tasks, 'cost_basis': None}


class SellerRoutingV7Tests(unittest.TestCase):
    def actions(self, row, **kwargs):
        return {x['action']: x for x in routing.plan_question(row, **kwargs)['steps']}

    def test_acceptance_terms_are_separate_from_saleability_and_prices(self):
        actions = self.actions(facts(refs=['BOOKOFF'], channel='store_buyback'))
        self.assertEqual(actions['retrieve_buyback_terms']['status'], 'blocked')
        self.assertNotIn('retrieve_live_offers', actions)
        self.assertNotIn('ask_sale_format', actions)

    def test_city_store_discovery_does_not_require_a_shipping_destination(self):
        row = facts('merchant_discovery', location='東京', channel='store_buyback')
        row['destination'] = None
        plan = routing.plan_question(row, capabilities={'current_merchant_directory'})
        actions = {x['action']: x for x in plan['steps']}
        self.assertEqual(actions['retrieve_merchant_candidates']['status'], 'ready')
        self.assertEqual(actions['retrieve_buyback_terms']['requires_actions'], ['retrieve_merchant_candidates'])
        self.assertNotIn('retrieve_seller_outcomes', actions)
        self.assertEqual(plan['merchant_location'], '東京')
        self.assertIsNone(plan['destination'])

    def test_missing_city_is_clarified_without_inventing_stores(self):
        actions = self.actions(facts('merchant_discovery'))
        self.assertIn('ask_merchant_location', actions)
        self.assertNotIn('retrieve_merchant_candidates', actions)

    def test_secondary_merchant_task_survives_collection_triage(self):
        actions = self.actions(facts('collection_triage', tasks=['merchant_discovery'], location='Tokyo'))
        self.assertIn('retrieve_merchant_candidates', actions)

    def test_explicit_lot_channel_choice_requests_inventory_and_constraints(self):
        actions = self.actions(facts('channel_choice', formats=['lot'], channel='none'))
        self.assertIn('ask_collection_inventory', actions)
        self.assertIn('ask_selling_channel', actions)
        self.assertIn('ask_sale_goal', actions)

    def test_net_proceeds_wait_for_units_and_then_need_each_cost_source(self):
        row = facts('seller_net_proceeds', channel='comparing_channels', formats=['lot'])
        actions = self.actions(row, capabilities=routing.CAPABILITIES)
        self.assertIn('ask_cost_basis', actions)
        self.assertNotIn('retrieve_live_offers', actions)
        actions = self.actions(row, sale_cohort=COHORT)
        for name in ('retrieve_live_offers', 'retrieve_verified_sale_series', 'validate_series_coverage',
                     'retrieve_selling_fees', 'retrieve_shipping_costs', 'retrieve_buyback_quotes',
                     'retrieve_buyback_terms'):
            self.assertEqual(actions[name]['status'], 'blocked')

    def test_mixed_games_require_scope_before_terms_or_catalog(self):
        actions = self.actions(facts(refs=['ゲオ', 'TSUTAYA', 'BOOKOFF'], scope='mixed_tcg'),
                               capabilities=routing.CAPABILITIES)
        self.assertEqual(set(actions), {'ask_supported_tcg_scope'})
        with self.assertRaises(ValueError):
            self.actions(facts(scope='mixed_tcg'), sale_cohort=COHORT)

    def test_multi_store_list_cannot_select_one_store_silently(self):
        row = facts(refs=['ゲオ', 'BOOKOFF'])
        row['merchant_ref'] = 'BOOKOFF'
        with self.assertRaisesRegex(ValueError, 'explicit merchant list'):
            routing.validate_facts(row)

    def test_known_saleability_path_is_preserved(self):
        actions = self.actions(facts('seller_saleability'))
        self.assertIn('review_sale_cohort', actions)
        self.assertIn('retrieve_sale_candidates', actions)

    def test_unknown_game_retains_inventory_request_without_market_actions(self):
        row = facts('channel_choice', scope='unknown', formats=['lot'])
        plan = routing.plan_question(row, capabilities=routing.CAPABILITIES)
        self.assertEqual({step['action'] for step in plan['steps']},
                         {'ask_product_type', 'ask_collection_inventory'})
        self.assertEqual(plan['sale_formats'], ['lot'])
        self.assertEqual(plan['claim_status'], 'general_explanation_only')

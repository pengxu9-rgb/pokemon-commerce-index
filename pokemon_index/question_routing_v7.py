"""Seller evidence plans preserving merchant, location and product scope.

V6 and its fresh-question diagnostic stay frozen. No action here fetches data
or certifies a merchant, copy condition, payout or profit.
"""

from __future__ import annotations

from typing import Any
from . import question_routing_v6 as v6

OBJECT_TYPES = v6.OBJECT_TYPES
NEW_GOALS = {'merchant_acceptance', 'merchant_discovery', 'seller_net_proceeds'}
FOCUSES = v6.FOCUSES | NEW_GOALS
TRANSACTION_CONTEXTS = v6.TRANSACTION_CONTEXTS
SELLER_CHANNELS = v6.SELLER_CHANNELS
LANGUAGES = v6.LANGUAGES
MEDIA_STATES = v6.MEDIA_STATES
SALE_FORMATS = v6.SALE_FORMATS
SELLER_TASKS = {'merchant_acceptance', 'merchant_discovery', 'net_proceeds'}
TCG_SCOPES = {'pokemon_tcg', 'mixed_tcg', 'other_tcg', 'unknown'}
FACT_FIELDS = v6.FACT_FIELDS | {'merchant_refs', 'merchant_location', 'tcg_scope',
                              'seller_tasks', 'cost_basis'}
CAPABILITIES = v6.CAPABILITIES | {'current_merchant_directory'}
validate_sale_cohort = v6.validate_sale_cohort
build_sale_cohort = v6.build_sale_cohort


def v6_projection(facts: dict[str, Any]) -> dict[str, Any]:
    result = {key: facts[key] for key in v6.FACT_FIELDS}
    if result['primary_goal'] in NEW_GOALS:
        result['primary_goal'] = 'other'
    return result


def catalog_projection(facts: dict[str, Any]) -> dict[str, Any]:
    return v6.catalog_projection(v6_projection(facts))


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError('v7 question facts have missing or unexpected fields')
    if facts['primary_goal'] not in FOCUSES or facts['tcg_scope'] not in TCG_SCOPES:
        raise ValueError('unsupported v7 goal or TCG scope')
    refs = facts['merchant_refs']
    if (not isinstance(refs, list) or len(refs) > 10 or
            any(not isinstance(x, str) or not x.strip() or len(x) > 120 for x in refs) or
            len({x.casefold() for x in refs}) != len(refs)):
        raise ValueError('invalid merchant_refs')
    # A list of stores must not silently become one selected merchant.
    if facts['merchant_ref'] != (refs[0] if len(refs) == 1 else None):
        raise ValueError('merchant_ref must agree with the explicit merchant list')
    tasks = facts['seller_tasks']
    if (not isinstance(tasks, list) or any(not isinstance(x, str) or x not in SELLER_TASKS
                                         for x in tasks) or len(set(tasks)) != len(tasks)):
        raise ValueError('invalid seller_tasks')
    for field in ('merchant_location', 'cost_basis'):
        value = facts[field]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 160):
            raise ValueError(f'invalid {field}')
    v6.validate_facts(v6_projection(facts))
    return facts


def plan_question(facts: dict[str, Any], *, resolution: dict | None = None,
                  capabilities: set[str] | None = None,
                  sale_cohort: dict | None = None) -> dict:
    validate_facts(facts)
    available = set(capabilities or set())
    if available - CAPABILITIES:
        raise ValueError('unknown capability')
    if resolution is not None:
        v6.v2.validate_resolution(resolution)
    goal = facts['primary_goal']
    tasks = set(facts['seller_tasks'])
    tasks.update({'merchant_acceptance'} if goal == 'merchant_acceptance' else
                 {'merchant_discovery'} if goal == 'merchant_discovery' else
                 {'net_proceeds'} if goal == 'seller_net_proceeds' else set())
    seller_channel = facts['seller_channel']
    seller_choice = goal == 'channel_choice' and (
        seller_channel != 'none' or facts['transaction_context'] in {'owned', 'listed_for_sale',
            'seller_buyback'} or bool(facts['sale_formats']))
    custom = bool(tasks) or goal in NEW_GOALS or seller_choice
    scope = facts['tcg_scope']
    supported = scope == 'pokemon_tcg' and facts['object_type'] not in {
        'sealed_tcg', 'non_tcg_card', 'unknown'}
    steps = []

    def add(action, capability, reason):
        if action not in {step['action'] for step in steps}:
            steps.append({'action': action,
                          'status': 'ready' if capability is None or capability in available else 'blocked',
                          'requires_capability': capability, 'reason': reason})

    if not supported:
        if sale_cohort is not None:
            raise ValueError('sale cohort requires a supported Pokémon TCG scope')
        if scope == 'mixed_tcg':
            add('ask_supported_tcg_scope', None,
                'Separate Pokémon TCG cards from other games before catalog or merchant comparison.')
        elif scope == 'other_tcg' or facts['object_type'] in {'sealed_tcg', 'non_tcg_card'}:
            add('explain_scope', None, 'The index currently covers physical Pokémon TCG cards.')
        else:
            add('ask_product_type', None, 'Establish the supported Pokémon TCG product scope.')
            if seller_choice or 'net_proceeds' in tasks:
                add('ask_collection_inventory', None,
                    'Retain the selling request while clarifying inventory and supported game scope.')
        claim = 'general_explanation_only'
    elif not custom:
        base = v6.plan_question(v6_projection(facts), resolution=resolution,
                               capabilities=available & v6.CAPABILITIES, sale_cohort=sale_cohort)
        base.update(schema='pokemon.question-route-plan.v7',
                    **{k: facts[k] for k in ('merchant_refs', 'merchant_location',
                                            'tcg_scope', 'seller_tasks', 'cost_basis')})
        return base
    else:
        if sale_cohort is not None:
            validate_sale_cohort(sale_cohort)
        add('explain_selling_factors', None,
            'Distinguish merchant acceptance, channel proceeds, condition and selling effort.')
        if facts['sale_scope'] is None and not facts['identity_tokens']['card_names']:
            add('ask_sale_scope', None, 'Identify the inventory, card class, language and era.')
        if 'merchant_discovery' in tasks:
            if facts['merchant_location'] is None:
                add('ask_merchant_location', None, 'Ask where the user wants to find a buyback store.')
            else:
                add('retrieve_merchant_candidates', 'current_merchant_directory',
                    'Find current stores in the stated location without asserting reliability or best payout.')
                add('retrieve_buyback_terms', 'merchant_buyback_terms',
                    'Verify each candidate store accepts the stated card class and selling format.')
                steps[-1]['requires_actions'] = ['retrieve_merchant_candidates']
        if 'merchant_acceptance' in tasks:
            if not facts['merchant_refs']:
                add('ask_merchant_details', None, 'Identify the store whose acceptance rules are requested.')
            else:
                add('retrieve_buyback_terms', 'merchant_buyback_terms',
                    'Check current acceptance, rotation, sorting and submission rules separately for each named store.')
        # A selling channel request must retain its inventory/format clarifications.
        if seller_choice or 'net_proceeds' in tasks:
            if seller_channel == 'none':
                add('ask_selling_channel', None, 'Ask which marketplace or buyback options to compare.')
            if not facts['sale_formats']:
                add('ask_sale_format', None, 'Ask whether selling singles, a whole lot, evolution lines or bulk.')
            if facts['sale_constraints'] is None:
                add('ask_sale_goal', None, 'Ask about desired proceeds, time and listing effort.')
            if sale_cohort is None:
                add('ask_collection_inventory', None, 'Obtain inventory and condition before comparable net-proceeds calculations.')
                add('review_sale_cohort', 'internal_catalog', 'Bind the requested inventory to exact priceable units.')
            if 'net_proceeds' in tasks:
                if facts['cost_basis'] is None:
                    add('ask_cost_basis', None, 'Profit requires paid acquisition costs; gross proceeds alone are not profit.')
                if sale_cohort is not None and seller_channel != 'none' and facts['sale_formats']:
                    if seller_channel in {'marketplace_listing', 'comparing_channels'}:
                        add('retrieve_live_offers', 'authorized_live_offers', 'Current asks are supply context, not seller payout.')
                        add('retrieve_verified_sale_series', 'verified_sale_series', 'Use settled sale evidence for each exact unit.')
                        add('validate_series_coverage', 'validated_series_coverage', 'Check the sample and observation period.')
                        add('retrieve_selling_fees', 'current_selling_fees', 'Include current fees for the selected marketplace and format.')
                        add('retrieve_shipping_costs', 'current_shipping_costs', 'Include packing and shipping per order or lot.')
                    if seller_channel in {'store_buyback', 'comparing_channels'}:
                        add('retrieve_buyback_quotes', 'authorized_buyback_quotes', 'Use current quotes for the exact units and copy conditions.')
                        add('retrieve_buyback_terms', 'merchant_buyback_terms', 'Verify quote conditions, deductions and submission costs.')
                    if 'evolution_line' in facts['sale_formats']:
                        add('retrieve_reviewed_relations', 'reviewed_relationships', 'Verify line composition; keep different unit prices separate.')
                if not v6.v5._concrete_horizon(facts['time_window']):
                    add('ask_analysis_period', None, 'A paid-sale comparison needs a defined observation period.')
        claim = 'retrieval_and_quality_review_required'

    return {'schema': 'pokemon.question-route-plan.v7', 'primary_goal': goal,
            'object_type': facts['object_type'], 'tcg_scope': scope,
            'scope_status': 'supported_card_object' if supported else
                            'needs_scope' if scope in {'mixed_tcg', 'unknown'} or
                            facts['object_type'] == 'unknown' else 'unsupported_product',
            'transaction_context': facts['transaction_context'], 'seller_channel': seller_channel,
            'merchant_refs': facts['merchant_refs'], 'merchant_location': facts['merchant_location'],
            'destination': facts['destination'], 'seller_tasks': sorted(tasks),
            'sale_scope': facts['sale_scope'], 'sale_formats': facts['sale_formats'],
            'sale_constraints': facts['sale_constraints'], 'cost_basis': facts['cost_basis'],
            'time_window': facts['time_window'], 'sale_cohort': sale_cohort,
            'catalog_resolution': resolution, 'steps': steps, 'claim_status': claim,
            'claim_guards': ['no_store_acceptance_without_current_merchant_terms',
                             'no_merchant_ranking_from_directory_or_platform_stars',
                             'no_payout_from_buyer_asks', 'no_sales_from_asks_or_disappearance',
                             'no_profit_without_cost_basis_fees_shipping_and_settlement',
                             'no_lot_price_from_sum_of_single_asks',
                             'no_cross_unit_price_pooling', 'no_mixed_tcg_catalog_assumption',
                             'no_reliability_claim_without_fulfilment_evidence']}

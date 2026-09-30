"""Evidence plans for seller timing, relative value and card selection.

V4 is frozen against the v8 public-question cohort. This successor only
plans evidence retrieval and clarification; it never predicts or recommends.
"""

from __future__ import annotations

from typing import Any

from . import question_routing_v2 as v2
from . import question_routing_v4 as v4

OBJECT_TYPES = v4.OBJECT_TYPES
FOCUSES = v4.FOCUSES | {"seller_timing", "relative_value_explanation"}
TRANSACTION_CONTEXTS = v4.TRANSACTION_CONTEXTS
SELLER_CHANNELS = v4.SELLER_CHANNELS
LANGUAGES = v4.LANGUAGES
MEDIA_STATES = v4.MEDIA_STATES
FACT_FIELDS = v4.FACT_FIELDS | {"sale_constraints"}
CAPABILITIES = v4.CAPABILITIES | {"authorized_buyback_quotes", "current_selling_fees",
                                  "reviewed_relationships"}
NEW_GOALS = {"seller_timing", "relative_value_explanation"}
VAGUE_HORIZONS = {"今後", "これから", "future", "later", "eventually", "long term",
                  "someday", "over time"}


def v4_projection(facts: dict[str, Any]) -> dict[str, Any]:
    projected = {key: facts[key] for key in v4.FACT_FIELDS}
    if projected["primary_goal"] in NEW_GOALS:
        projected["primary_goal"] = "other"
    return projected


def catalog_projection(facts: dict[str, Any]) -> dict[str, Any]:
    return v4.catalog_projection(v4_projection(facts))


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError("v5 question facts have missing or unexpected fields")
    if facts["primary_goal"] not in FOCUSES:
        raise ValueError("unsupported goal")
    constraint = facts["sale_constraints"]
    if constraint is not None and (not isinstance(constraint, str) or
                                   not constraint.strip() or len(constraint) > 160):
        raise ValueError("invalid sale_constraints")
    v4.validate_facts(v4_projection(facts))
    return facts


def _concrete_horizon(value: str | None) -> bool:
    return value is not None and value.strip().casefold() not in VAGUE_HORIZONS


def plan_question(facts: dict[str, Any], *, resolution: dict[str, Any] | None = None,
                  capabilities: set[str] | None = None) -> dict[str, Any]:
    validate_facts(facts)
    available = set() if capabilities is None else set(capabilities)
    if available - CAPABILITIES:
        raise ValueError("unknown capability")
    if resolution is not None:
        v2.validate_resolution(resolution)
    goal = facts["primary_goal"]
    if goal not in NEW_GOALS and goal != "collecting_preference":
        plan = v4.plan_question(v4_projection(facts), resolution=resolution,
                                capabilities=available & v4.CAPABILITIES)
        plan.update(schema="pokemon.question-route-plan.v5",
                    sale_constraints=facts["sale_constraints"])
        if goal in v4.TREND_GOALS and not _concrete_horizon(facts["time_window"]):
            action = "ask_decision_horizon" if goal == "purchase_timing" else "ask_time_window"
            if action not in {step["action"] for step in plan["steps"]}:
                plan["steps"].append({"action": action, "status": "ready",
                                      "requires_capability": None,
                                      "reason": "A vague future reference does not define an analysis or decision interval."})
        return plan

    catalog_attempted = resolution is not None
    resolution = resolution or {"status": "not_attempted", "candidate_ids": [],
                                "evidence_ref": None}
    steps: list[dict[str, Any]] = []

    def add(action: str, capability: str | None, reason: str) -> None:
        if action not in {step["action"] for step in steps}:
            steps.append({"action": action,
                          "status": "ready" if capability is None or capability in available
                          else "blocked", "requires_capability": capability,
                          "reason": reason})

    obj = facts["object_type"]
    names = facts["identity_tokens"]["card_names"]
    if obj in {"sealed_tcg", "non_tcg_card"}:
        add("explain_scope", None, "The current index does not cover this product.")
        scope = "unsupported_product"
    elif obj == "unknown":
        add("ask_product_type", None, "Identify the Pokémon TCG product scope first.")
        scope = "needs_scope"
    else:
        scope = "supported_card_object"

    if scope == "supported_card_object" and goal == "collecting_preference":
        add("explain_selection_factors", None,
            "Describe fit, condition, budget and uncertainty without naming a winner.")
        if not names:
            add("ask_candidate_cards_or_preferences", None,
                "The question has no usable card choices or stated artwork, era or character preference.")
        else:
            add("retrieve_catalog_candidates", "internal_catalog",
                "Resolve each named option without assuming the same printing or condition.")
            add("retrieve_reviewed_relations", "reviewed_relationships",
                "Use reviewed card relationships for alternatives, not unsupported similarity claims.")
        if facts["purchase_constraints"] is None:
            add("ask_budget_and_condition", None,
                "A useful shortlist needs a budget and target copy condition.")
        if facts["media_state"] == "referenced_not_collected":
            add("ask_listed_choices", None, "Referenced photos are not available to this review.")
    elif scope == "supported_card_object" and goal in NEW_GOALS:
        add("explain_market_context", None,
            "Separate observations, relative values and forecasts; old quotes are historical context.")
        seller_state_ok = facts["transaction_context"] in {
            "owned", "listed_for_sale", "sold_pending_fulfillment", "completed_sale"}
        if goal == "seller_timing" and not seller_state_ok:
            add("ask_sale_state", None, "A seller timing decision needs the user's sale state.")
        if obj in {"card_collection", "card_market_segment"}:
            add("ask_comparable_cohort", None,
                "Define comparable cards, languages, grades and releases before a market comparison.")
        elif len(names) != 1:
            add("ask_target_card", None, "Choose one named card before a printing-level analysis.")
        elif resolution["status"] == "not_attempted":
            add("ask_printing_details" if catalog_attempted else "retrieve_catalog",
                None if catalog_attempted else "internal_catalog",
                "Identify the release, language, number and printing first.")
        elif resolution["status"] == "multiple_candidates":
            add("ask_printing_details", None,
                "Several catalog printings can have different market values.")
        elif resolution["status"] == "no_match":
            add("explain_catalog_gap", None, "No supported catalog printing matched.")
            add("ask_printing_details", None, "Request better release or card-face evidence.")
        elif goal != "seller_timing" or seller_state_ok:
            if goal == "relative_value_explanation":
                add("retrieve_reviewed_counterpart", "reviewed_relationships",
                    "A counterpart comparison needs a reviewed printing relationship.")
            add("retrieve_historical_asks", "authorized_ask_history",
                "Dated asks describe listings, not paid transactions.")
            add("retrieve_verified_sale_series", "verified_sale_series",
                "Dated settled sales describe paid-price evidence.")
            add("validate_series_coverage", "validated_series_coverage",
                "Check sample count, time window and source mix for each comparable unit.")
            if goal == "seller_timing":
                add("retrieve_live_offers", "authorized_live_offers",
                    "Fresh asks provide current market context, not seller payout.")
                if facts["seller_channel"] in {"store_buyback", "comparing_channels"}:
                    add("retrieve_buyback_quotes", "authorized_buyback_quotes",
                        "Store buyback is a separate current net-proceeds option.")
                if facts["seller_channel"] in {"marketplace_listing", "comparing_channels"}:
                    add("retrieve_selling_fees", "current_selling_fees",
                        "Marketplace fees are needed to compare net proceeds.")
        if goal == "seller_timing":
            if facts["seller_channel"] == "none":
                add("ask_selling_channel", None,
                    "The seller may use a marketplace, buyback shop or both.")
            if not _concrete_horizon(facts["time_window"]):
                add("ask_sale_horizon", None, "Choose a concrete hold or sale horizon.")
            if facts["sale_constraints"] is None:
                add("ask_sale_constraints", None,
                    "Ask about cash need, target net proceeds and willingness to wait.")
            if facts["media_state"] != "available":
                add("ask_front_back_photos", None,
                    "The actual copy's condition affects proceeds; photos are unavailable.")
        elif not _concrete_horizon(facts["time_window"]):
            add("ask_comparison_period", None,
                "A measured relative value needs a defined time period.")

    return {"schema": "pokemon.question-route-plan.v5",
            "object_type": obj, "primary_goal": goal, "scope_status": scope,
            "transaction_context": facts["transaction_context"],
            "seller_channel": facts["seller_channel"],
            "catalog_resolution": resolution,
            "catalog_query": facts["identity_tokens"],
            "time_window": facts["time_window"],
            "purchase_constraints": facts["purchase_constraints"],
            "sale_constraints": facts["sale_constraints"],
            "steps": steps, "answer_mode": "explain_then_evidence",
            "claim_status": "retrieval_and_quality_review_required" if (
                scope == "supported_card_object" and obj == "single_card" and
                resolution["status"] == "unique" and goal != "collecting_preference")
            else "general_explanation_only",
            "claim_guards": ["no_unique_printing_without_catalog_evidence",
                             "no_current_price_from_forum_quote",
                             "no_paid_price_from_asks",
                             "no_cross_printing_price_join_without_reviewed_relation",
                             "no_seller_payout_from_buyer_asks",
                             "no_guaranteed_future_price_prediction",
                             "no_card_recommendation_without_resolved_choices_and_preferences"]}

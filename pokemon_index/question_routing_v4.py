"""Evidence plan for price trends and purchase timing, separate from frozen v3."""

from __future__ import annotations

from typing import Any

from . import question_routing_v2 as v2
from . import question_routing_v3 as v3

OBJECT_TYPES = v3.OBJECT_TYPES | {"card_market_segment"}
FOCUSES = v3.FOCUSES | {"price_trend", "purchase_timing"}
TRANSACTION_CONTEXTS = v3.TRANSACTION_CONTEXTS
SELLER_CHANNELS = v3.SELLER_CHANNELS
LANGUAGES = v3.LANGUAGES
MEDIA_STATES = v3.MEDIA_STATES
FACT_FIELDS = v3.FACT_FIELDS | {"time_window", "purchase_constraints"}
CAPABILITIES = v3.V3_CAPABILITIES | {"authorized_ask_history",
                                    "verified_sale_series", "validated_series_coverage"}
TREND_GOALS = {"price_trend", "purchase_timing"}


def catalog_projection(facts: dict[str, Any]) -> dict[str, Any]:
    projected = {key: facts[key] for key in v3.FACT_FIELDS}
    if projected["object_type"] == "card_market_segment":
        projected["object_type"] = "card_collection"
    if projected["primary_goal"] in TREND_GOALS:
        projected["primary_goal"] = "other"
    return projected


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError("v4 question facts have missing or unexpected fields")
    if facts["object_type"] not in OBJECT_TYPES or facts["primary_goal"] not in FOCUSES:
        raise ValueError("unsupported object or goal")
    for field in ("time_window", "purchase_constraints"):
        value = facts[field]
        if value is not None and (not isinstance(value, str) or not value.strip()
                                  or len(value) > 160):
            raise ValueError(f"invalid {field}")
    v3.validate_facts(catalog_projection(facts))
    return facts


def plan_question(facts: dict[str, Any], *, resolution: dict[str, Any] | None = None,
                  capabilities: set[str] | None = None) -> dict[str, Any]:
    """Plan retrievals; never decide a price trend or recommend a purchase."""
    validate_facts(facts)
    available = set() if capabilities is None else set(capabilities)
    if available - CAPABILITIES:
        raise ValueError("unknown capability")
    if resolution is not None:
        v2.validate_resolution(resolution)
    goal = facts["primary_goal"]
    if goal not in TREND_GOALS:
        plan = v3.plan_question(catalog_projection(facts), resolution=resolution,
                                capabilities=available & v3.V3_CAPABILITIES)
        if resolution is not None and resolution["status"] == "not_attempted":
            for step in plan["steps"]:
                if step["action"] == "retrieve_catalog":
                    step.update(action="ask_printing_details", status="ready",
                                requires_capability=None,
                                reason="Catalog lookup needs more printing evidence.")
        plan.update(schema="pokemon.question-route-plan.v4",
                    object_type=facts["object_type"], primary_goal=goal,
                    time_window=facts["time_window"],
                    purchase_constraints=facts["purchase_constraints"])
        return plan

    catalog_attempted = resolution is not None
    resolution = (resolution or {"status": "not_attempted", "candidate_ids": [],
                                "evidence_ref": None})
    steps: list[dict[str, Any]] = []

    def add(action: str, capability: str | None, reason: str) -> None:
        if action not in {step["action"] for step in steps}:
            steps.append({"action": action,
                          "status": "ready" if capability is None or capability in available
                          else "blocked",
                          "requires_capability": capability, "reason": reason})

    object_type = facts["object_type"]
    names = facts["identity_tokens"]["card_names"]
    add("explain_market_context", None,
        "Explain the question without treating quoted or historical asks as current prices.")
    if object_type in {"sealed_tcg", "non_tcg_card"}:
        add("explain_scope", None, "This card index does not cover the requested product.")
        scope = "unsupported_product"
    elif object_type == "unknown":
        add("ask_product_type", None, "Identify the Pokémon TCG product scope first.")
        scope = "needs_scope"
    elif object_type in {"card_collection", "card_market_segment"}:
        add("ask_market_scope", None,
            "Choose a card group, release or comparable printings before a segment trend.")
        scope = "supported_card_object"
    else:
        scope = "supported_card_object"
        if len(names) != 1:
            add("ask_target_card", None, "Choose one card before a printing-level trend.")
        elif resolution["status"] == "not_attempted":
            add("ask_printing_details" if catalog_attempted else "retrieve_catalog",
                None if catalog_attempted else "internal_catalog",
                "Identify the language, release, number and printing first.")
        elif resolution["status"] == "multiple_candidates":
            add("ask_printing_details", None,
                "Several catalog printings have different price histories.")
        elif resolution["status"] == "no_match":
            add("explain_catalog_gap", None, "No supported catalog printing matched.")
            add("ask_printing_details", None, "Request better release or card-face evidence.")
        else:
            add("retrieve_historical_asks", "authorized_ask_history",
                "An ask trend requires dated, authorized listing observations for the same unit.")
            add("retrieve_verified_sale_series", "verified_sale_series",
                "A paid-price trend requires dated, verified transactions for the same unit.")
            add("validate_series_coverage", "validated_series_coverage",
                "Check sample count, missed listings, time window and source mix before inferring movement.")
            if goal == "purchase_timing":
                add("retrieve_live_offers", "authorized_live_offers",
                    "A current decision also needs fresh offers for the exact unit.")

    if scope == "supported_card_object":
        if facts["time_window"] is None:
            add("ask_decision_horizon" if goal == "purchase_timing" else "ask_time_window",
                None, "The relevant time interval has not been specified.")
        if goal == "purchase_timing" and facts["purchase_constraints"] is None:
            add("ask_purchase_constraints", None,
                "A buy-or-wait decision needs budget, condition and risk preferences.")

    return {"schema": "pokemon.question-route-plan.v4",
            "object_type": object_type, "primary_goal": goal, "scope_status": scope,
            "transaction_context": facts["transaction_context"],
            "catalog_resolution": resolution,
            "catalog_query": facts["identity_tokens"],
            "time_window": facts["time_window"],
            "purchase_constraints": facts["purchase_constraints"],
            "steps": steps,
            "answer_mode": "explain_then_evidence",
            "claim_status": ("retrieval_and_quality_review_required"
                             if scope == "supported_card_object" and
                             object_type == "single_card" and
                             resolution["status"] == "unique"
                             else "general_explanation_only"),
            "claim_guards": ["no_current_price_from_forum_quote",
                             "no_paid_price_from_asks",
                             "no_trend_without_unit_and_coverage",
                             "no_guaranteed_future_price_prediction",
                             "no_buy_now_recommendation_from_listing_asks_alone"]}

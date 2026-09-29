"""Deterministic evidence plan for a *structured* collector question.

A language model may propose the facts, but this module does not infer them
from prose and never generates a card, seller, price or policy claim.
"""

from __future__ import annotations

from typing import Any

PRODUCT_SCOPES = {"tcg_single", "tcg_collection", "sealed_tcg",
                  "non_tcg_card", "marketplace_process", "unknown"}
FOCUSES = {"identify_card", "identify_variant", "cross_language_relation",
           "price_comparison", "condition_assessment", "authenticity",
           "seller_pricing", "grading_decision", "channel_choice",
           "merchant_reliability", "landed_cost", "collection_triage",
           "collecting_preference", "marketplace_policy", "other"}
CAPABILITIES = {"internal_catalog", "authorized_live_offers", "verified_sales",
                "current_marketplace_policy", "listing_photos", "seller_outcomes",
                "landed_quotes", "official_release_source",
                "merchant_buyback_terms", "authorized_buyback_quotes"}
REQUIRED_FACTS = {"product_scope", "focus", "named_card", "exact_printing",
                  "specific_copy", "photos_available", "language_scope"}


def _step(action: str, *, capability: str | None = None,
          reason: str | None = None, available: set[str],
          waiting_for_user: bool = False) -> dict[str, Any]:
    return {"action": action,
            "status": ("waiting_for_user" if waiting_for_user else
                       "ready" if capability is None or capability in available else "blocked"),
            "requires_capability": capability,
            "capability_ready": capability is None or capability in available,
            "reason": reason}


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Validate one model-proposed fact bundle before any action planning."""
    if not isinstance(facts, dict) or set(facts) != REQUIRED_FACTS:
        raise ValueError("question facts have missing or unexpected fields")
    if facts["product_scope"] not in PRODUCT_SCOPES or facts["focus"] not in FOCUSES:
        raise ValueError("unsupported question scope or focus")
    if facts["language_scope"] not in {"ja_en", "other", "unspecified"}:
        raise ValueError("unsupported language scope")
    if any(type(facts[key]) is not bool for key in
           ("named_card", "exact_printing", "specific_copy", "photos_available")):
        raise ValueError("identity and media facts must be booleans")
    if facts["exact_printing"] and not facts["named_card"]:
        raise ValueError("an exact printing requires a named card")
    return facts


def plan_question(facts: dict[str, Any], *, capabilities: set[str] | None = None) -> dict[str, Any]:
    """Plan an answer and next evidence requests without making factual claims.

    A step marked blocked remains visible so a caller can explain what is
    missing. The caller must separately authorize and perform retrieval.
    """
    validate_facts(facts)
    available = set() if capabilities is None else set(capabilities)
    if available - CAPABILITIES:
        raise ValueError("unknown capability")
    scope, focus = facts["product_scope"], facts["focus"]
    steps: list[dict[str, Any]] = []

    def add(action: str, *, capability: str | None = None,
            reason: str | None = None) -> None:
        if action not in {step["action"] for step in steps}:
            steps.append(_step(action, capability=capability,
                               reason=reason, available=available,
                               waiting_for_user=action.startswith("retrieve_") and
                               any(step["action"].startswith("ask_") for step in steps)))

    if scope in {"sealed_tcg", "non_tcg_card"}:
        add("explain_scope", reason="The current catalog indexes physical Pokémon TCG cards and collections of those cards.")
        status = "unsupported_product"
    elif scope == "unknown":
        add("ask_product_type", reason="The question does not establish whether the item is a supported TCG card.")
        status = "needs_scope"
    elif scope == "marketplace_process":
        add("explain_general", reason="General process guidance does not require a card identity.")
        if focus == "marketplace_policy":
            add("retrieve_current_policy", capability="current_marketplace_policy",
                reason="A platform-specific obligation or protection requires current policy evidence.")
        elif focus == "merchant_reliability":
            add("retrieve_seller_outcomes", capability="seller_outcomes",
                reason="A merchant reliability claim requires fulfilment outcome evidence.")
        elif focus == "channel_choice":
            add("retrieve_buyback_terms", capability="merchant_buyback_terms",
                reason="Store acceptance and buyback rules require current merchant evidence.")
        status = "general_guidance_only"
    elif (facts["language_scope"] == "other" and
          focus == "cross_language_relation"):
        add("explain_catalog_coverage", reason="The current card catalog covers Japanese and English physical printings.")
        add("retrieve_official_release", capability="official_release_source",
            reason="Other-language artwork or printing claims need release evidence outside the current catalog.")
        status = "limited_catalog_scope"
    else:
        status = "supported_catalog_scope"
        if focus in {"grading_decision", "collecting_preference", "channel_choice",
                     "collection_triage", "merchant_reliability", "other",
                     "condition_assessment", "authenticity", "marketplace_policy"}:
            add("explain_general", reason="State the decision factors without claiming a case-specific outcome.")
        if focus == "price_comparison" and not facts["specific_copy"]:
            add("explain_general", reason="A category-level comparison can explain price drivers without inventing current numeric values.")
        if focus in {"identify_card", "identify_variant", "cross_language_relation",
                     "price_comparison", "seller_pricing", "landed_cost",
                     "condition_assessment", "authenticity", "grading_decision"}:
            if not facts["named_card"] and focus not in {"grading_decision"}:
                add("ask_card_details", reason="A card name or set and number is needed before catalog lookup.")
            if facts["named_card"] and not facts["exact_printing"] and focus in {
                    "price_comparison", "seller_pricing", "landed_cost",
                    "cross_language_relation"}:
                add("ask_printing_details", reason="Language, set, number and finish must be fixed before comparing offers or relations.")
        if focus in {"identify_card", "identify_variant", "cross_language_relation"}:
            add("retrieve_catalog", capability="internal_catalog",
                reason="Catalog and reviewed graph evidence are needed for printing claims.")
        if focus in {"condition_assessment", "authenticity", "grading_decision",
                     "seller_pricing"} and facts["specific_copy"]:
            if not facts["photos_available"]:
                add("ask_front_back_photos", reason="The actual copy cannot be assessed without its photos.")
            else:
                add("review_supplied_photos", reason="Visual evidence can support observations, not a guaranteed grade or authenticity verdict.")
        if focus in {"price_comparison", "seller_pricing", "landed_cost", "channel_choice"}:
            if facts["exact_printing"]:
                if focus == "seller_pricing":
                    add("retrieve_buyback_quotes", capability="authorized_buyback_quotes",
                        reason="A seller payout estimate needs authorized, current buyback quotes.")
                else:
                    add("retrieve_live_offers", capability="authorized_live_offers",
                        reason="Current asks require an authorized, fresh listing source.")
                add("retrieve_verified_sales", capability="verified_sales",
                    reason="A paid-price claim requires verified transaction evidence.")
            if focus == "landed_cost":
                add("retrieve_landed_quotes", capability="landed_quotes",
                    reason="Destination and all fee components require a current quote.")
        if focus == "merchant_reliability":
            add("retrieve_seller_outcomes", capability="seller_outcomes",
                reason="Marketplace stars do not establish fulfilment quality.")
        if focus == "marketplace_policy":
            add("retrieve_current_policy", capability="current_marketplace_policy",
                reason="A platform-specific rule requires current policy evidence.")

    if len(steps) == 1:
        answer_mode = "single_step"
    elif steps[0]["action"] == "explain_general":
        answer_mode = "explain_then_evidence"
    else:
        answer_mode = "evidence_sequence"
    return {"schema": "pokemon.question-route-plan.v1",
            "product_scope": scope, "focus": focus, "scope_status": status,
            "answer_mode": answer_mode, "steps": steps,
            "claim_guards": ["no_live_price_without_authorized_offer",
                             "no_paid_sale_without_settlement_evidence",
                             "no_grade_or_condition_claim_without_copy_evidence",
                             "no_cross_printing_price_join_from_same_artwork"]}

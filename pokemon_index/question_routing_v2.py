"""Experimental evidence planner with object, task and transaction kept separate.

The language model extracts what the user actually said. Catalog identity is a
separate, evidence-backed result. Neither extraction nor this planner performs
retrieval or establishes a current marketplace fact.
"""

from __future__ import annotations

from typing import Any

OBJECT_TYPES = {"single_card", "card_collection", "sealed_tcg", "non_tcg_card", "unknown"}
FOCUSES = {"identify_card", "identify_variant", "cross_language_relation",
           "price_comparison", "condition_assessment", "authenticity",
           "seller_pricing", "grading_decision", "channel_choice",
           "merchant_reliability", "landed_cost", "collection_triage",
           "collecting_preference", "marketplace_policy", "other"}
TRANSACTION_CONTEXTS = {"none", "prospective_buy", "owned", "listed_for_sale",
                        "completed_purchase", "seller_buyback"}
MEDIA_STATES = {"available", "referenced_not_collected", "none"}
LANGUAGES = {"ja", "en", "zh", "ko", "fr", "other", "unspecified_foreign"}
TOKEN_FIELDS = {"card_names", "set_name", "collector_number", "language", "finish", "grade"}
FACT_FIELDS = {"object_type", "primary_goal", "transaction_context", "identity_tokens",
               "media_state", "language_mentions", "merchant_ref", "destination"}
RESOLUTION_STATES = {"not_attempted", "unique", "multiple_candidates", "no_match"}
V2_CAPABILITIES = {"internal_catalog", "reviewed_relationships",
                   "authorized_live_offers", "verified_sales",
                   "current_marketplace_policy", "seller_outcomes",
                   "landed_quotes", "official_release_source",
                   "merchant_buyback_terms", "authorized_buyback_quotes"}


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError("v2 question facts have missing or unexpected fields")
    if facts["object_type"] not in OBJECT_TYPES or facts["primary_goal"] not in FOCUSES:
        raise ValueError("unsupported object or goal")
    if facts["transaction_context"] not in TRANSACTION_CONTEXTS or facts["media_state"] not in MEDIA_STATES:
        raise ValueError("unsupported transaction or media state")
    languages = facts["language_mentions"]
    if (not isinstance(languages, list) or
            any(not isinstance(item, str) for item in languages) or
            len(languages) != len(set(languages)) or set(languages) - LANGUAGES):
        raise ValueError("invalid explicit language mentions")
    tokens = facts["identity_tokens"]
    if not isinstance(tokens, dict) or set(tokens) != TOKEN_FIELDS:
        raise ValueError("identity tokens have missing or unexpected fields")
    names = tokens["card_names"]
    if (not isinstance(names, list) or len(names) > 8 or
            any(not isinstance(name, str) or not name.strip() or len(name) > 120
                for name in names) or len(names) != len(set(names))):
        raise ValueError("invalid card names")
    for field in TOKEN_FIELDS - {"card_names"}:
        value = tokens[field]
        if value is not None and (not isinstance(value, str) or not value.strip()
                                  or len(value) > 120):
            raise ValueError(f"invalid identity token: {field}")
    if tokens["language"] is not None and tokens["language"] not in LANGUAGES - {"unspecified_foreign"}:
        raise ValueError("card language must be explicit")
    for field in ("merchant_ref", "destination"):
        value = facts[field]
        if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 160):
            raise ValueError(f"invalid {field}")
    return facts


def validate_resolution(resolution: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(resolution, dict) or set(resolution) != {
            "status", "candidate_ids", "evidence_ref"}:
        raise ValueError("catalog resolution has missing or unexpected fields")
    status, ids, evidence = (resolution[key] for key in
                             ("status", "candidate_ids", "evidence_ref"))
    if (status not in RESOLUTION_STATES or not isinstance(ids, list) or
            any(not isinstance(item, str) or not item for item in ids) or
            len(ids) != len(set(ids)) or
            (evidence is not None and (not isinstance(evidence, str) or not evidence.strip()))):
        raise ValueError("invalid catalog resolution")
    if status == "unique" and (len(ids) != 1 or evidence is None):
        raise ValueError("unique printing requires one catalog ID and evidence")
    if status == "multiple_candidates" and (len(ids) < 2 or evidence is None):
        raise ValueError("multiple candidates require catalog evidence")
    if status in {"not_attempted", "no_match"} and ids:
        raise ValueError("unresolved printing cannot carry a catalog ID")
    if status == "no_match" and evidence is None:
        raise ValueError("a catalog miss requires a search evidence reference")
    return resolution


def plan_question(facts: dict[str, Any], *,
                  resolution: dict[str, Any] | None = None,
                  capabilities: set[str] | None = None) -> dict[str, Any]:
    """Return an evidence plan; no plan step itself performs a retrieval."""
    validate_facts(facts)
    resolution = ({"status": "not_attempted", "candidate_ids": [], "evidence_ref": None}
                  if resolution is None else validate_resolution(resolution))
    available = set() if capabilities is None else set(capabilities)
    if available - V2_CAPABILITIES:
        raise ValueError("unknown capability")
    object_type, goal = facts["object_type"], facts["primary_goal"]
    names = facts["identity_tokens"]["card_names"]
    steps: list[dict[str, Any]] = []

    def add(action: str, *, capability: str | None = None, reason: str) -> None:
        if action in {step["action"] for step in steps}:
            return
        steps.append({"action": action,
                      "status": "ready" if capability is None or capability in available else "blocked",
                      "requires_capability": capability,
                      "reason": reason})

    def identity_gate() -> bool:
        """Return true only when independent catalog evidence identifies one printing."""
        if len(names) != 1:
            add("ask_target_card", reason="Choose one named card before comparing a printing or price.")
            return False
        status = resolution["status"]
        if status == "not_attempted":
            add("retrieve_catalog", capability="internal_catalog",
                reason="Resolve the stated name, set, number and language against the catalog.")
            return False
        if status == "multiple_candidates":
            add("ask_printing_details", reason="Catalog search returned several physical printings.")
            return False
        if status == "no_match":
            add("explain_catalog_gap", reason="The catalog found no supported printing for these tokens.")
            add("ask_printing_details", reason="Request the release, number or card-face evidence for a new search.")
            return False
        return True

    if object_type in {"sealed_tcg", "non_tcg_card"}:
        add("explain_scope", reason="The current catalog covers physical Pokémon TCG cards and card collections.")
        scope_status = "unsupported_product"
    elif object_type == "unknown":
        add("ask_product_type", reason="The user has not established a supported card object.")
        scope_status = "needs_scope"
    else:
        scope_status = "supported_card_object"
        if goal in {"grading_decision", "collecting_preference", "channel_choice",
                    "collection_triage", "merchant_reliability", "other",
                    "condition_assessment", "authenticity", "marketplace_policy",
                    "price_comparison", "seller_pricing", "landed_cost"}:
            add("explain_general", reason="Explain decision factors without claiming a case-specific result.")
        if goal == "marketplace_policy":
            add("retrieve_current_policy", capability="current_marketplace_policy",
                reason="Return, authentication and account rules require current platform evidence.")
        elif goal == "merchant_reliability":
            if facts["merchant_ref"] is None:
                add("ask_merchant_details", reason="A generic seller signal cannot establish one merchant's reliability.")
            else:
                add("retrieve_seller_outcomes", capability="seller_outcomes",
                    reason="Fulfilment evidence is needed for this identified merchant.")
        elif goal == "collecting_preference":
            pass
        elif goal == "collection_triage":
            add("ask_collection_inventory", reason="A collection decision needs an inventory or stated collecting goal.")
        elif goal == "cross_language_relation":
            if "unspecified_foreign" in facts["language_mentions"] or set(
                    facts["language_mentions"]) & {"zh", "ko", "fr", "other"}:
                add("explain_catalog_coverage", reason="The current canonical card catalog is Japanese and English.")
                add("retrieve_official_release", capability="official_release_source",
                    reason="Other-language printing claims require external release evidence.")
            else:
                if identity_gate():
                    add("show_catalog_relation", capability="reviewed_relationships",
                        reason="A cross-printing claim requires an independently reviewed graph edge.")
        elif goal in {"identify_card", "identify_variant"}:
            if not names:
                add("ask_card_details", reason="A name, card number or supplied image is needed to begin identification.")
            else:
                if identity_gate():
                    add("show_catalog_identity", reason="Present the uniquely resolved catalog printing and its evidence.")
        elif goal in {"condition_assessment", "authenticity", "grading_decision"}:
            if facts["transaction_context"] != "none":
                if facts["media_state"] == "available":
                    add("review_supplied_photos", reason="Inspect actual front and back; never guarantee grade or authenticity.")
                else:
                    add("ask_front_back_photos", reason="A specific copy cannot be assessed from text or uncollected images.")
        elif goal in {"price_comparison", "seller_pricing", "landed_cost"}:
            if goal == "seller_pricing" and facts["transaction_context"] != "none":
                if facts["media_state"] == "available":
                    add("review_supplied_photos", reason="Seller payout depends on the actual copy's condition.")
                else:
                    add("ask_front_back_photos", reason="Seller payout depends on the actual copy's condition.")
            resolved = identity_gate()
            if resolved:
                if goal == "seller_pricing":
                    add("retrieve_buyback_quotes", capability="authorized_buyback_quotes",
                        reason="Seller payout requires current authorized buyback quotes.")
                else:
                    add("retrieve_live_offers", capability="authorized_live_offers",
                        reason="Current asking prices require an authorized, fresh listing source.")
                add("retrieve_verified_sales", capability="verified_sales",
                    reason="A paid-price claim requires verified transaction evidence.")
            if goal == "landed_cost":
                if facts["destination"] is None:
                    add("ask_destination", reason="A landed quote needs a destination.")
                elif resolved:
                    add("retrieve_landed_quotes", capability="landed_quotes",
                        reason="Fees and tax must be quoted for this destination.")
        elif goal == "channel_choice":
            if facts["transaction_context"] == "seller_buyback":
                add("retrieve_buyback_terms", capability="merchant_buyback_terms",
                    reason="A store's acceptance rules require current merchant evidence.")
        else:
            add("explain_general", reason="State the decision factors without a case-specific claim.")

    answer_mode = ("single_step" if len(steps) == 1 else
                   "explain_then_evidence" if steps[0]["action"] == "explain_general" else
                   "evidence_sequence")
    return {"schema": "pokemon.question-route-plan.v2",
            "object_type": object_type, "primary_goal": goal,
            "scope_status": scope_status, "answer_mode": answer_mode,
            "catalog_resolution": resolution, "steps": steps,
            "claim_guards": ["no_unique_printing_without_catalog_evidence",
                             "no_live_price_without_authorized_offer",
                             "no_paid_sale_without_settlement_evidence",
                             "no_seller_payout_from_buyer_asks",
                             "no_condition_or_grade_guarantee_from_text_or_photos",
                             "no_cross_printing_price_join_from_same_artwork"]}

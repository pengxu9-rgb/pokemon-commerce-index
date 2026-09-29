"""Question facts v3 and an evidence plan, without changing frozen v2 runs.

The extractor supplies only text facts. Catalog identity, marketplace evidence,
merchant outcomes and policy freshness are still independent capabilities.
"""

from __future__ import annotations

import re
from typing import Any

from . import question_routing_v2 as v2

OBJECT_TYPES = v2.OBJECT_TYPES
FOCUSES = v2.FOCUSES
MEDIA_STATES = v2.MEDIA_STATES
LANGUAGES = v2.LANGUAGES
TRANSACTION_CONTEXTS = {"none", "observed_listing", "prospective_buy", "owned", "listed_for_sale",
                        "sold_pending_fulfillment", "completed_purchase", "completed_sale"}
SELLER_CHANNELS = {"none", "marketplace_listing", "store_buyback", "comparing_channels"}
TOKEN_FIELDS = v2.TOKEN_FIELDS | {"rarity"}
FACT_FIELDS = {"object_type", "primary_goal", "transaction_context", "seller_channel",
               "identity_tokens", "media_state", "language_mentions", "platform_refs",
               "merchant_ref", "destination"}
V3_CAPABILITIES = v2.V2_CAPABILITIES | {"current_selling_fees"}

# Exact platform/service names only. A named shop or seller on a platform is
# still allowed. This list is a guard against the failures observed in v6.
PLATFORM_NAMES = {"mercari", "mercarijp", "メルカリ", "yahooフリマ", "ヤフーフリマ",
                  "yahoojapan", "yahoojp", "ヤフオク", "ebay", "snkrdunk",
                  "スニダン", "buyee"}
RARITY_CODES = {"UR", "MUR", "SAR", "SR", "AR", "RR", "RRR", "HR", "CSR", "CHR"}


def _platform_key(value: str) -> str:
    return re.sub(r"[\s!./・_-]+", "", value.casefold())


def _short_string(value: Any, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError("v3 question facts have missing or unexpected fields")
    for field, options in (("object_type", OBJECT_TYPES), ("primary_goal", FOCUSES),
                           ("transaction_context", TRANSACTION_CONTEXTS),
                           ("seller_channel", SELLER_CHANNELS), ("media_state", MEDIA_STATES)):
        if not isinstance(facts[field], str) or facts[field] not in options:
            raise ValueError(f"unsupported {field}")
    for field, options in (("language_mentions", LANGUAGES),):
        values = facts[field]
        if (not isinstance(values, list) or len(values) != len(set(
                value for value in values if isinstance(value, str))) or
                any(not isinstance(value, str) or value not in options for value in values)):
            raise ValueError(f"invalid {field}")
    tokens = facts["identity_tokens"]
    if not isinstance(tokens, dict) or set(tokens) != TOKEN_FIELDS:
        raise ValueError("identity tokens have missing or unexpected fields")
    names = tokens["card_names"]
    if (not isinstance(names, list) or len(names) > 8 or
            any(not _short_string(name, 120) for name in names) or
            len(names) != len(set(names))):
        raise ValueError("invalid card names")
    for field in TOKEN_FIELDS - {"card_names"}:
        value = tokens[field]
        if value is not None and not _short_string(value, 120):
            raise ValueError(f"invalid identity token: {field}")
    if tokens["language"] is not None and tokens["language"] not in LANGUAGES - {
            "unspecified_foreign"}:
        raise ValueError("card language must be explicit")
    if tokens["finish"] is not None and tokens["finish"].strip().upper() in RARITY_CODES:
        raise ValueError("rarity code cannot be a finish")
    platforms = facts["platform_refs"]
    if (not isinstance(platforms, list) or len(platforms) > 8 or
            any(not _short_string(item, 160) for item in platforms) or
            len({_platform_key(item) for item in platforms}) != len(platforms)):
        raise ValueError("invalid platform references")
    for field in ("merchant_ref", "destination"):
        value = facts[field]
        if value is not None and not _short_string(value, 160):
            raise ValueError(f"invalid {field}")
    merchant = facts["merchant_ref"]
    if merchant is not None:
        parts = [part for part in re.split(r"\s*(?:/|、|,|，)\s*", merchant) if part]
        if parts and all(_platform_key(part) in PLATFORM_NAMES for part in parts):
            raise ValueError("a platform is not a merchant")
    if (facts["seller_channel"] != "none" and
            facts["transaction_context"] in {"observed_listing", "prospective_buy",
                                             "completed_purchase"}):
        raise ValueError("seller channel conflicts with buyer transaction")
    return facts


def _v2_projection(facts: dict[str, Any]) -> dict[str, Any]:
    context = facts["transaction_context"]
    if context == "observed_listing":
        context = "prospective_buy"  # A specific third-party copy still needs copy evidence.
    if context in {"sold_pending_fulfillment", "completed_sale"}:
        context = "listed_for_sale"
    if facts["primary_goal"] == "channel_choice" and facts["seller_channel"] in {
            "store_buyback", "comparing_channels"}:
        context = "seller_buyback"
    return {"object_type": facts["object_type"], "primary_goal": facts["primary_goal"],
            "transaction_context": context,
            "identity_tokens": {key: facts["identity_tokens"][key] for key in v2.TOKEN_FIELDS},
            "media_state": facts["media_state"],
            "language_mentions": facts["language_mentions"],
            "merchant_ref": facts["merchant_ref"], "destination": facts["destination"]}


def plan_question(facts: dict[str, Any], *, resolution: dict[str, Any] | None = None,
                  capabilities: set[str] | None = None) -> dict[str, Any]:
    """Build a v3 plan while retaining the v2 identity and evidence gates."""
    validate_facts(facts)
    available = set() if capabilities is None else set(capabilities)
    if available - V3_CAPABILITIES:
        raise ValueError("unknown capability")
    plan = v2.plan_question(_v2_projection(facts), resolution=resolution,
                            capabilities=available & v2.V2_CAPABILITIES)
    steps = plan["steps"]

    def add(action: str, capability: str | None, reason: str) -> None:
        if action not in {step["action"] for step in steps}:
            steps.append({"action": action,
                          "status": "ready" if capability is None or capability in available else "blocked",
                          "requires_capability": capability, "reason": reason})

    if plan["scope_status"] == "supported_card_object" and facts["primary_goal"] == "seller_pricing":
        channel = facts["seller_channel"]
        if channel in {"none", "marketplace_listing"}:
            steps[:] = [step for step in steps if step["action"] != "retrieve_buyback_quotes"]
        if channel == "none":
            add("ask_selling_channel", None,
                "A seller payout depends on whether this is store buyback or marketplace sale.")
        if channel in {"marketplace_listing", "comparing_channels"}:
            if (len(facts["identity_tokens"]["card_names"]) == 1 and
                    plan["catalog_resolution"]["status"] == "unique"):
                add("retrieve_live_offers", "authorized_live_offers",
                    "Current listing asks are context for a seller's market, not net proceeds.")
            add("retrieve_selling_fees", "current_selling_fees",
                "Estimate net proceeds after current platform fees.")
            if facts["platform_refs"]:
                add("retrieve_current_policy", "current_marketplace_policy",
                    "Authentication and dispute rules affect the sale channel.")
    if plan["scope_status"] == "supported_card_object" and facts["primary_goal"] == "channel_choice":
        if facts["seller_channel"] == "comparing_channels":
            add("retrieve_selling_fees", "current_selling_fees",
                "Compare the seller's net proceeds after current marketplace fees.")
        if facts["seller_channel"] in {"marketplace_listing", "comparing_channels"} and facts[
                "platform_refs"]:
            add("retrieve_current_policy", "current_marketplace_policy",
                "Transaction and authentication rules depend on the named platform.")
    plan.update(schema="pokemon.question-route-plan.v3",
                transaction_context=facts["transaction_context"],
                seller_channel=facts["seller_channel"],
                platform_refs=facts["platform_refs"],
                catalog_query=facts["identity_tokens"],
                answer_mode=("single_step" if len(steps) == 1 else
                             "explain_then_evidence" if steps[0]["action"] == "explain_general"
                             else "evidence_sequence"))
    return plan

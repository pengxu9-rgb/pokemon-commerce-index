"""Evidence plans for selling a card class individually, in lines or as bulk.

V5 stays frozen. Candidate selection is separate from a reviewed priceable-unit
cohort; a question extractor cannot certify that cohort or saleability.
"""

from __future__ import annotations

import re
import hashlib
import json
import sqlite3
from typing import Any

from . import question_routing_v2 as v2
from . import question_routing_v5 as v5

OBJECT_TYPES = v5.OBJECT_TYPES
FOCUSES = v5.FOCUSES | {"seller_saleability"}
TRANSACTION_CONTEXTS = v5.TRANSACTION_CONTEXTS
SELLER_CHANNELS = v5.SELLER_CHANNELS
LANGUAGES = v5.LANGUAGES
MEDIA_STATES = v5.MEDIA_STATES
SALE_FORMATS = {"single", "evolution_line", "lot", "bulk"}
FACT_FIELDS = v5.FACT_FIELDS | {"sale_scope", "sale_formats"}
CAPABILITIES = v5.CAPABILITIES | {"current_shipping_costs"}


def v5_projection(facts: dict[str, Any]) -> dict[str, Any]:
    result = {key: facts[key] for key in v5.FACT_FIELDS}
    if result["primary_goal"] == "seller_saleability":
        result["primary_goal"] = "other"
    return result


def catalog_projection(facts: dict[str, Any]) -> dict[str, Any]:
    return v5.catalog_projection(v5_projection(facts))


def validate_facts(facts: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(facts, dict) or set(facts) != FACT_FIELDS:
        raise ValueError("v6 question facts have missing or unexpected fields")
    if facts["primary_goal"] not in FOCUSES:
        raise ValueError("unsupported goal")
    scope = facts["sale_scope"]
    if scope is not None and (not isinstance(scope, str) or not scope.strip() or len(scope) > 160):
        raise ValueError("invalid sale_scope")
    formats = facts["sale_formats"]
    if (not isinstance(formats, list) or any(not isinstance(x, str) or x not in SALE_FORMATS
                                           for x in formats) or len(set(formats)) != len(formats)):
        raise ValueError("invalid sale_formats")
    v5.validate_facts(v5_projection(facts))
    return facts


def validate_sale_cohort(cohort: dict[str, Any]) -> dict[str, Any]:
    """Validate an upstream evidence envelope, never an extractor fact."""
    if not isinstance(cohort, dict) or set(cohort) != {"unit_ids", "evidence_ref"}:
        raise ValueError("sale cohort needs reviewed units and an evidence reference")
    units, ref = cohort["unit_ids"], cohort["evidence_ref"]
    if (not isinstance(units, list) or not 1 <= len(units) <= 1000
            or any(not isinstance(x, str) or len(x) > 240 for x in units)
            or len(set(units)) != len(units)
            or not isinstance(ref, str)
            or not re.fullmatch(r"catalog-unit-cohort-sha256:[0-9a-f]{64}", ref)):
        raise ValueError("invalid reviewed sale cohort")
    for unit in units:
        parts = unit.split("|")
        if (len(parts) != 4 or any(not part for part in parts)
                or len(parts[0].split(":")) != 4 or any(not x for x in parts[0].split(":"))
                or parts[3].casefold() in {"unknown", "unspecified"}
                or parts[1] not in {"RAW", "PSA", "BGS", "CGC", "ARS", "PGC"}
                or (parts[1] == "RAW" and parts[2] != "raw")
                or (parts[1] != "RAW" and
                    (not re.fullmatch(r"10|[1-9](?:\.5)?", parts[2]) or parts[3] != "graded"))):
            raise ValueError("sale cohort needs exact priceable units and known condition")
    return cohort


def build_sale_cohort(db: sqlite3.Connection, unit_ids: list[str]) -> dict[str, Any]:
    """Bind a cohort to existing, match-eligible unit rows without market claims."""
    validate_sale_cohort({"unit_ids": unit_ids,
                          "evidence_ref": "catalog-unit-cohort-sha256:" + "0" * 64})
    records = []
    for unit_id in sorted(unit_ids):
        row = db.execute("""SELECT u.*,c.provenance,c.rarity,c.match_eligible
            FROM priceable_unit u JOIN card c ON c.card_id=u.card_id WHERE u.unit_id=?""",
                         (unit_id,)).fetchone()
        if not row or not row["match_eligible"]:
            raise ValueError("sale cohort contains missing or match-ineligible units")
        if unit_id != "|".join(row[key] for key in
                              ("card_id", "grade_company", "grade_value", "condition_bucket")):
            raise ValueError("sale cohort unit coordinates disagree with catalog rows")
        records.append(dict(row))
    digest = hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    return {"unit_ids": sorted(unit_ids), "evidence_ref": f"catalog-unit-cohort-sha256:{digest}"}


def plan_question(facts: dict[str, Any], *, resolution: dict[str, Any] | None = None,
                  capabilities: set[str] | None = None,
                  sale_cohort: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_facts(facts)
    available = set() if capabilities is None else set(capabilities)
    if available - CAPABILITIES:
        raise ValueError("unknown capability")
    if facts["primary_goal"] != "seller_saleability":
        if sale_cohort is not None:
            raise ValueError("sale cohort is only supported for seller saleability")
        plan = v5.plan_question(v5_projection(facts), resolution=resolution,
                                capabilities=available & v5.CAPABILITIES)
        plan.update(schema="pokemon.question-route-plan.v6",
                    sale_scope=facts["sale_scope"], sale_formats=facts["sale_formats"])
        return plan
    if resolution is not None:
        v2.validate_resolution(resolution)
    if sale_cohort is not None:
        validate_sale_cohort(sale_cohort)
    steps = []

    def add(action: str, capability: str | None, reason: str) -> None:
        steps.append({"action": action,
                      "status": "ready" if capability is None or capability in available else "blocked",
                      "requires_capability": capability, "reason": reason})

    obj = facts["object_type"]
    supported = obj not in {"sealed_tcg", "non_tcg_card", "unknown"}
    if not supported:
        add("ask_product_type" if obj == "unknown" else "explain_scope", None,
            "Identify a supported Pokémon TCG card scope first.")
    else:
        add("explain_saleability_factors", None,
            "Explain demand, condition, net proceeds and listing effort without naming profitable cards.")
        if facts["sale_scope"] is None:
            add("ask_sale_scope", None,
                "Define era, language, category, rarity/finish and the inventory or card class.")
        if not facts["sale_formats"]:
            add("ask_sale_format", None, "Ask whether single cards, evolution lines, lots or bulk are considered.")
        if facts["seller_channel"] == "none":
            add("ask_selling_channel", None, "Net proceeds depend on marketplace selling or store buyback.")
        if facts["sale_constraints"] is None:
            add("ask_sale_goal", None, "Ask for acceptable proceeds, effort and time to sell.")
        if not v5._concrete_horizon(facts["time_window"]):
            add("ask_analysis_period", None, "Sales frequency and coverage need a defined observation period.")
        if sale_cohort is None:
            add("ask_target_condition", None, "Raw condition and graded status must remain separate.")
            if facts["sale_scope"] is not None or facts["identity_tokens"]["card_names"]:
                add("retrieve_sale_candidates", "internal_catalog",
                    "Retrieve metadata candidates for the stated scope, without asserting saleability.")
            add("review_sale_cohort", "internal_catalog",
                "Resolve exact priceable units and inventory condition before market evidence retrieval.")
        else:
            add("retrieve_live_offers", "authorized_live_offers",
                "Current asks describe available supply for each reviewed unit.")
            add("retrieve_verified_sale_series", "verified_sale_series",
                "Settled sales and frequency are needed to assess whether cards actually sell.")
            add("validate_series_coverage", "validated_series_coverage",
                "Check unit-level sample counts, observation window and censored or missing sales.")
            if facts["seller_channel"] in {"marketplace_listing", "comparing_channels"}:
                add("retrieve_selling_fees", "current_selling_fees",
                    "Compare per-order fees and selling costs across the requested sale formats.")
                add("retrieve_shipping_costs", "current_shipping_costs",
                    "Packing and shipping costs can make low-priced singles uneconomic.")
            if facts["seller_channel"] in {"store_buyback", "comparing_channels"}:
                add("retrieve_buyback_quotes", "authorized_buyback_quotes",
                    "Store buyback proceeds are a separate option from marketplace asks.")
            if "evolution_line" in facts["sale_formats"]:
                add("retrieve_reviewed_relations", "reviewed_relationships",
                    "Validate evolution-line composition; a relationship never makes unit prices interchangeable.")

    return {"schema": "pokemon.question-route-plan.v6", "object_type": obj,
            "primary_goal": facts["primary_goal"],
            "scope_status": ("supported_card_object" if supported else
                             "needs_scope" if obj == "unknown" else "unsupported_product"),
            "transaction_context": facts["transaction_context"],
            "seller_channel": facts["seller_channel"], "catalog_resolution": resolution,
            "sale_scope": facts["sale_scope"], "sale_formats": facts["sale_formats"],
            "sale_constraints": facts["sale_constraints"], "time_window": facts["time_window"],
            "sale_cohort": sale_cohort, "steps": steps,
            "claim_status": "retrieval_and_quality_review_required" if supported and sale_cohort
                            else "general_explanation_only",
            "claim_guards": ["no_saleability_ranking_without_reviewed_units_and_market_evidence",
                             "no_sales_from_asks_or_disappearance",
                             "no_profit_from_gross_asks_without_fees_shipping_and_cost_basis",
                             "no_cross_unit_price_pooling",
                             "no_evolution_line_from_unreviewed_relations",
                             "no_bulk_or_bundle_price_from_summing_single_card_asks"]}

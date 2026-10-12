"""Conservative, read-only resolution of v3 question tokens against catalog rows."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from typing import Any

from . import core, question_routing_v3


def _key(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").replace('♀', 'female').replace('♂', 'male')
    return re.sub(r"[\W_]+", "", normalized.casefold())


def _finish_matches(finish: str, variant: str) -> bool:
    """A broad finish must retain edition and promo subvariants."""
    wanted = re.sub(r"[\W]+", "_", unicodedata.normalize("NFKC", finish).casefold()).strip("_")
    observed = re.sub(r"[\W]+", "_", unicodedata.normalize("NFKC", variant).casefold()).strip("_")
    return observed == wanted or observed.startswith(wanted + "_")


def resolve_question(db: sqlite3.Connection, facts: dict[str, Any], *,
                     candidate_limit: int = 20) -> dict[str, Any]:
    """Return a v2-compatible resolution and an auditable candidate summary.

    A unique catalog row requires an explicit name, language, set and number.
    This identifies a catalog printing, not a marketplace copy or its condition.
    """
    question_routing_v3.validate_facts(facts)
    if not 2 <= candidate_limit <= 100:
        raise ValueError("candidate_limit must be 2–100")
    tokens = facts["identity_tokens"]
    empty = {"status": "not_attempted", "candidate_ids": [], "evidence_ref": None}
    if facts["object_type"] != "single_card" or len(tokens["card_names"]) != 1:
        return {"resolution": empty, "reason": "single_named_card_required",
                "matched_total": 0, "candidates": [], "query": tokens}

    name = _key(tokens["card_names"][0])
    language = tokens["language"]
    number = (core.normalize_collector_number(tokens["collector_number"])
              if tokens["collector_number"] else None)
    set_key = _key(tokens["set_name"])
    rarity_key = _key(tokens["rarity"])
    finish = tokens["finish"]
    rows = db.execute(
        """SELECT c.card_id, c.language, c.set_code, c.collector_number,
                  c.variant, c.name, c.rarity, c.provenance, c.match_eligible,
                  s.name AS localized_set_name
           FROM card c LEFT JOIN catalog_set_localized s
             ON s.language=c.language AND s.set_code=c.set_code
           WHERE (? IS NULL OR c.language=?)
             AND (? IS NULL OR c.collector_number=?)
           ORDER BY c.card_id""",
        (language, language, number, number),
    ).fetchall()
    matched = []
    for row in rows:
        if _key(row["name"]) != name:
            continue
        if set_key and set_key not in {_key(row["set_code"]), _key(row["localized_set_name"])}:
            continue
        if rarity_key and row["rarity"] and _key(row["rarity"]) != rarity_key:
            continue
        if finish and not _finish_matches(finish, row["variant"]):
            continue
        matched.append(dict(row))

    digest = hashlib.sha256(json.dumps({"query": tokens, "matched": matched},
                                      ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    evidence_ref = f"catalog-query-sha256:{digest}"
    eligible = [row for row in matched if row["match_eligible"]]
    exact_coordinates = all((language, set_key, number))
    unknown_rarity = bool(rarity_key and any(not row["rarity"] for row in matched))
    excluded = len(matched) != len(eligible)
    if not matched:
        status, reason, ids = "no_match", "no_catalog_row", []
    elif len(eligible) == 1 and len(matched) == 1 and exact_coordinates and not unknown_rarity:
        status, reason, ids = "unique", "exact_catalog_coordinates", [eligible[0]["card_id"]]
    elif len(eligible) >= 2:
        status, reason = "multiple_candidates", "ambiguous_catalog_printing"
        ids = [row["card_id"] for row in eligible[:candidate_limit]]
    else:
        status = "not_attempted"
        reason = ("excluded_or_unverified_catalog_row" if excluded else
                  "rarity_not_verified" if unknown_rarity else "insufficient_printing_coordinates")
        ids = []
    resolution = {"status": status, "candidate_ids": ids,
                  "evidence_ref": evidence_ref if status != "not_attempted" else None}
    return {"resolution": resolution, "reason": reason,
            "matched_total": len(matched),
            "candidates": [{key: row[key] for key in (
                "card_id", "language", "set_code", "collector_number", "variant",
                "name", "rarity", "match_eligible")}
                for row in matched[:candidate_limit]],
            "query": tokens, "query_evidence_ref": evidence_ref}


def plan_question_with_catalog(db: sqlite3.Connection, facts: dict[str, Any], *,
                               capabilities: set[str] | None = None) -> dict[str, Any]:
    """Resolve against a catalog snapshot, then apply the existing v3 evidence gates."""
    lookup = resolve_question(db, facts)
    plan = question_routing_v3.plan_question(
        facts, resolution=lookup["resolution"], capabilities=capabilities)
    if lookup["resolution"]["status"] == "not_attempted" and lookup[
            "reason"] != "single_named_card_required":
        for step in plan["steps"]:
            if step["action"] == "retrieve_catalog":
                step.update(action="ask_printing_details", status="ready",
                            requires_capability=None,
                            reason="The catalog lookup needs more or verified printing evidence.")
    plan["catalog_lookup"] = lookup
    return plan

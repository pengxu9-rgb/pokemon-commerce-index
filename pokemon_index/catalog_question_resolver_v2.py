"""Reviewed bilingual name retrieval on top of the frozen v1 card resolver.

A bilingual concept translates a name only. It never proves a counterpart
printing, a physical finish, or cross-region price comparability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from typing import Any

from . import catalog_question_resolver as v1
from . import question_routing_v3


def _cross_language_name(name: str, language: str | None) -> bool:
    return bool((language == "ja" and re.search(r"[A-Za-z]", name)) or
                (language == "en" and re.search(r"[\u3040-\u30ff\u3400-\u9fff]", name)))


def _reviewed_aliases(db: sqlite3.Connection, name: str,
                      language: str) -> list[dict[str, Any]]:
    rows = db.execute("""WITH ranked AS (
                SELECT *, ROW_NUMBER() OVER
                (PARTITION BY concept_id ORDER BY revision DESC) AS rank
                FROM bilingual_concept_revision)
            SELECT concept_id, revision, name_ja, name_en, category,
                   review_event_id, rights_reference
            FROM ranked WHERE rank=1 AND status='approved'""").fetchall()
    source, target = (("name_en", "name_ja") if language == "ja"
                      else ("name_ja", "name_en"))
    return [{"concept_id": row["concept_id"], "revision": row["revision"],
             "translated_name": row[target], "category": row["category"],
             "review_event_id": row["review_event_id"],
             "rights_reference": row["rights_reference"]}
            for row in rows if v1._key(row[source]) == v1._key(name)]


def resolve_question(db: sqlite3.Connection, facts: dict[str, Any], *,
                     candidate_limit: int = 20) -> dict[str, Any]:
    first = v1.resolve_question(db, facts, candidate_limit=candidate_limit)
    tokens = facts["identity_tokens"]
    if (first["resolution"]["status"] != "no_match" or
            facts["object_type"] != "single_card" or
            len(tokens["card_names"]) != 1 or
            not _cross_language_name(tokens["card_names"][0], tokens["language"])):
        return first

    aliases = _reviewed_aliases(db, tokens["card_names"][0], tokens["language"])
    names = {v1._key(alias["translated_name"]) for alias in aliases}
    if len(names) != 1:
        return {**first,
                "resolution": {"status": "not_attempted", "candidate_ids": [],
                               "evidence_ref": None},
                "reason": ("ambiguous_reviewed_translation" if len(names) > 1
                           else "unresolved_cross_language_name"),
                "name_aliases": aliases}

    translated = copy.deepcopy(facts)
    translated["identity_tokens"]["card_names"] = [aliases[0]["translated_name"]]
    found = v1.resolve_question(db, translated, candidate_limit=candidate_limit)
    found["query"] = tokens
    found["name_aliases"] = aliases
    if found["resolution"]["status"] == "no_match":
        found["resolution"] = {"status": "not_attempted", "candidate_ids": [],
                               "evidence_ref": None}
        found["reason"] = "translated_name_scope_unresolved"
        return found
    if found["resolution"]["status"] == "not_attempted":
        found["reason"] = ("translated_name_catalog_row_ineligible"
                           if found["reason"] == "excluded_or_unverified_catalog_row"
                           else "translated_name_insufficient_coordinates")
        return found
    if found["resolution"]["status"] == "unique":
        classification = db.execute("SELECT category FROM card_classification WHERE card_id=?",
                                    (found["resolution"]["candidate_ids"][0],)).fetchone()
        if (classification is None or
                classification["category"] not in {alias["category"] for alias in aliases}):
            found["resolution"] = {"status": "not_attempted", "candidate_ids": [],
                                   "evidence_ref": None}
            found["reason"] = "translated_name_category_unverified"
            return found
    trace = {"original_query": tokens, "aliases": aliases,
             "translated_query_evidence_ref": found["query_evidence_ref"],
             "candidate_ids": found["resolution"]["candidate_ids"]}
    digest = hashlib.sha256(json.dumps(trace, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest()
    found["resolution"]["evidence_ref"] = f"reviewed-name-alias-sha256:{digest}"
    found["reason"] = "reviewed_name_alias_then_" + found["reason"]
    return found


def plan_question_with_catalog(db: sqlite3.Connection, facts: dict[str, Any], *,
                               capabilities: set[str] | None = None) -> dict[str, Any]:
    lookup = resolve_question(db, facts)
    plan = question_routing_v3.plan_question(
        facts, resolution=lookup["resolution"], capabilities=capabilities)
    if lookup["resolution"]["status"] == "not_attempted":
        for step in plan["steps"]:
            if step["action"] == "retrieve_catalog":
                step.update(action="ask_printing_details", status="ready",
                            requires_capability=None,
                            reason="The catalog needs verified name or printing evidence.")
    plan["catalog_lookup"] = lookup
    return plan

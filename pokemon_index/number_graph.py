"""Release-scoped collector-number facts, kept separate from card equivalence."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from typing import Any

from . import number_conflicts


def _token(value: str) -> str:
    token = unicodedata.normalize("NFKC", value).strip().upper()
    return str(int(token)) if token.isdecimal() else token


def parse_number(value: str) -> dict[str, str | None]:
    raw = unicodedata.normalize("NFKC", str(value)).strip().upper()
    if not raw:
        raise ValueError("collector number cannot be empty")
    if raw.count("/") == 1:
        left, right = (_token(part) for part in raw.split("/", 1))
        if left and right:
            if left.isdecimal() and right.isdecimal():
                kind = "numeric_fraction"
            elif left.isdecimal() or right.isdecimal():
                kind = "mixed_fraction"
            else:
                kind = "coded_fraction"
            return {"printed_number": raw, "full_number_key": f"{left}/{right}",
                    "numerator_key": left, "denominator_key": right,
                    "number_format": kind}
    kind = "single" if "/" not in raw and re.fullmatch(r"[A-Z0-9-]+", raw) else "other"
    return {"printed_number": raw, "full_number_key": _token(raw),
            "numerator_key": None, "denominator_key": None,
            "number_format": kind}


def _context_values(card: sqlite3.Row | dict[str, Any]) -> tuple[Any, ...]:
    parsed = parse_number(card["collector_number"])
    return (card["card_id"], f"{card['language'].lower()}:{card['set_code'].upper()}",
            "provisional_language_set", parsed["printed_number"],
            parsed["full_number_key"], parsed["numerator_key"],
            parsed["denominator_key"], parsed["number_format"],
            card["variant"], "card_metadata_v1")


def upsert_number_context(db: sqlite3.Connection, card: sqlite3.Row | dict[str, Any]) -> None:
    db.execute("""INSERT INTO card_number_context VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(card_id) DO UPDATE SET
        number_scope_id=excluded.number_scope_id,
        printed_number=excluded.printed_number,
        full_number_key=excluded.full_number_key,
        numerator_key=excluded.numerator_key,
        denominator_key=excluded.denominator_key,
        number_format=excluded.number_format,
        variant_label=excluded.variant_label""", _context_values(card))


def backfill_number_context(db: sqlite3.Connection) -> int:
    missing = db.execute("""SELECT c.card_id,c.language,c.set_code,c.collector_number,c.variant
        FROM card c LEFT JOIN card_number_context n ON n.card_id=c.card_id
        WHERE n.card_id IS NULL""").fetchall()
    db.executemany("INSERT INTO card_number_context VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (_context_values(card) for card in missing))
    return len(missing)


def card_number_context(db: sqlite3.Connection, card_id: str) -> dict[str, Any]:
    row = db.execute("""SELECT n.*,c.language,c.set_code,c.name,c.match_eligible,
        c.display_allowed,c.provenance,c.rights_reference FROM card_number_context n
        JOIN card c ON c.card_id=n.card_id
        WHERE n.card_id=?""", (card_id,)).fetchone()
    if row is None:
        raise ValueError("unknown card or missing number context")
    conflict = number_conflicts.rule_for_card(
        db, row["language"], row["set_code"], row["printed_number"], row["provenance"])
    number_conflict = ({"rule_id": conflict["rule_id"],
                        "catalog_denominator": conflict["catalog_denominator"],
                        "official_denominator": conflict["official_denominator"],
                        "reason": conflict["reason"]} if conflict else None)
    alias = db.execute("""SELECT official_number_candidate,official_record_count,evidence_json
        FROM card_number_alias_candidate WHERE card_id=?""", (card_id,)).fetchone()
    number_alias = None
    if alias:
        evidence = json.loads(alias["evidence_json"])
        number_alias = {"official_number_candidate": alias["official_number_candidate"],
                        "official_record_count": alias["official_record_count"],
                        "official_source_page_urls_unverified": [
                            record["url"] for record in evidence["official_records"]],
                        "source_revision": evidence["official_source_revision"],
                        "physical_printing_status": "unverified",
                        "offer_matching_status": "blocked"}
    visual = db.execute("""SELECT group_id,visual_status,evidence_json
        FROM card_number_alias_visual_context WHERE card_id=?""", (card_id,)).fetchone()
    visual_signal = None
    if visual:
        evidence = json.loads(visual["evidence_json"])
        visual_signal = {"group_id": visual["group_id"],
                         "visual_status": visual["visual_status"],
                         "source_jp_ids": evidence["source_jp_ids"],
                         "official_record_to_catalog_variant_assignment": "unestablished",
                         "physical_printing_status": "unverified",
                         "offer_matching_status": "blocked"}
    return dict(row) | {"region": None, "finish": None, "stamp": None,
                        "edition": None, "physical_variant_status": "unverified",
                        "source_number_conflict": number_conflict,
                        "source_number_alias_candidate": number_alias,
                        "multi_record_visual_signal": visual_signal}


def number_alignment(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    same_scope = left["number_scope_id"] == right["number_scope_id"]
    same_full = left["full_number_key"] == right["full_number_key"]
    numerator_known = left["numerator_key"] is not None and right["numerator_key"] is not None
    denominator_known = left["denominator_key"] is not None and right["denominator_key"] is not None
    same_numerator = numerator_known and left["numerator_key"] == right["numerator_key"]
    same_denominator = denominator_known and left["denominator_key"] == right["denominator_key"]
    if same_full:
        alignment = "same_number_same_scope" if same_scope else "same_number_different_scope"
    elif same_numerator:
        alignment = "same_numerator_different_denominator"
    elif same_denominator:
        alignment = "different_numerator_same_denominator"
    else:
        alignment = "different_or_unparsed"
    return {"number_alignment": alignment, "same_provisional_scope": same_scope,
            "same_full_number": same_full,
            "same_numerator": same_numerator if numerator_known else None,
            "same_denominator": same_denominator if denominator_known else None}


def explain_number_pair(db: sqlite3.Connection, left_card_id: str,
                        right_card_id: str) -> dict[str, Any]:
    """Explain number alignment only for two explicit cards; never infer a price link."""
    if left_card_id == right_card_id:
        raise ValueError("choose two distinct cards")
    left = card_number_context(db, left_card_id)
    right = card_number_context(db, right_card_id)
    numbers = number_alignment(left, right)
    endpoints = sorted((left_card_id, right_card_id))
    latest = {}
    for row in db.execute("""SELECT assertion_id,relation_type,review_status,
        asserted_by,asserted_at,evidence_ref FROM card_relationship_assertion
        WHERE left_card_id=? AND right_card_id=? ORDER BY rowid DESC""", endpoints):
        latest.setdefault(row["relation_type"], dict(row))
    relationships = [latest[key] for key in sorted(latest)]
    active = [row for row in relationships if row["review_status"] in {"proposed", "verified"}]
    if numbers["same_provisional_scope"] and numbers["same_full_number"]:
        evidence_status = "same_scope_number_variant_candidates"
    elif any(row["review_status"] == "verified" for row in active):
        evidence_status = "reviewed_relationship"
    elif active:
        evidence_status = "proposed_relationship_only"
    else:
        evidence_status = "cross_card_relationship_unestablished"
    return {"left": left, "right": right,
            **numbers,
            "relationships": relationships, "evidence_status": evidence_status,
            "same_physical_printing_established": False,
            "price_series_merge_allowed": False,
            "numeric_price_gap_available": False,
            "scope": "internal numbering explanation; matching numbers or artwork do not establish identical printing or price comparability"}

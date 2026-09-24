"""Internal, evidence-backed card relationships and structured discovery state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any, Iterable

from . import core

RELATION_TYPES = {"localization_counterpart", "same_artwork", "collecting_alternative"}
REVIEW_STATUSES = {"proposed", "verified", "rejected"}
CONSTRAINT_FIELDS = {
    "query", "language", "set_code", "collector_number", "variant",
    "grade_company", "grade_value", "budget_minor", "currency", "destination",
}


def _card(db: sqlite3.Connection, card_id: str) -> sqlite3.Row:
    card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    if card is None:
        raise ValueError(f"unknown card {card_id!r}")
    return card


def assert_relationships(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Import reviewed or proposed claims. Exact duplicate assertions are idempotent."""
    prepared = []
    for row in rows:
        core._required(row, "left_card_id", "right_card_id", "relation_type",
                       "review_status", "evidence_ref", "rights_reference", "asserted_by")
        if row["relation_type"] not in RELATION_TYPES or row["review_status"] not in REVIEW_STATUSES:
            raise ValueError("unsupported relationship type or review status")
        if row["review_status"] != "proposed" and not row.get("reviewer"):
            raise ValueError("verified or rejected relationships require a reviewer")
        left, right = sorted((str(row["left_card_id"]), str(row["right_card_id"])))
        if left == right:
            raise ValueError("a card cannot relate to itself")
        left_card, right_card = _card(db, left), _card(db, right)
        if row["relation_type"] == "localization_counterpart" and left_card["language"] == right_card["language"]:
            raise ValueError("localization counterparts must use different languages")
        asserted_at = core.parse_time(row.get("asserted_at") or core.utcnow()).isoformat()
        actor = str(row.get("reviewer") or row["asserted_by"])
        assertion = {
            "left_card_id": left, "right_card_id": right,
            "relation_type": row["relation_type"], "review_status": row["review_status"],
            "evidence_ref": row["evidence_ref"], "rights_reference": row["rights_reference"],
            "asserted_by": actor,
        }
        assertion_id = hashlib.sha256(json.dumps(assertion, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        prepared.append((assertion_id, left, right, row["relation_type"], row["review_status"],
                         row["evidence_ref"], row["rights_reference"], actor, asserted_at))
    count = 0
    with db:
        for values in prepared:
            count += db.execute(
                "INSERT OR IGNORE INTO card_relationship_assertion VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values,
            ).rowcount
    return count


def card_neighborhood(db: sqlite3.Connection, card_id: str,
                      include_proposed: bool = False) -> dict[str, Any]:
    """Internal view. Same set/number variants are structural; other edges need review."""
    card = _card(db, card_id)
    variants = [dict(row) for row in db.execute(
        """SELECT card_id, name, variant, match_eligible, display_allowed FROM card
        WHERE language=? AND set_code=? AND collector_number=? AND card_id<>?
        ORDER BY variant""",
        (card["language"], card["set_code"], card["collector_number"], card_id),
    )]
    assertions = db.execute(
        """SELECT a.*, CASE WHEN a.left_card_id=? THEN a.right_card_id ELSE a.left_card_id END AS other_card_id,
        c.name AS other_name, c.language AS other_language, c.match_eligible AS other_match_eligible,
        c.display_allowed AS other_display_allowed
        FROM card_relationship_assertion a JOIN card c
        ON c.card_id=CASE WHEN a.left_card_id=? THEN a.right_card_id ELSE a.left_card_id END
        WHERE a.left_card_id=? OR a.right_card_id=?
        ORDER BY a.rowid DESC""", (card_id, card_id, card_id, card_id),
    )
    latest: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in assertions:
        key = (row["left_card_id"], row["right_card_id"], row["relation_type"])
        latest.setdefault(key, dict(row))
    reviewed = [item for item in latest.values()
                if item["review_status"] == "verified"
                or (include_proposed and item["review_status"] == "proposed")]
    reviewed.sort(key=lambda item: (item["relation_type"], item["other_card_id"]))
    return {"card_id": card_id, "variants_at_number": variants,
            "relationships": reviewed,
            "scope": "internal metadata; only verified edges support factual discovery claims"}


def _validate_constraints(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - CONSTRAINT_FIELDS:
        raise ValueError("constraints must be an object with supported fields")
    result = {key: field for key, field in value.items() if field is not None}
    if any(not isinstance(field, str) or not field.strip()
           for key, field in result.items() if key != "budget_minor"):
        raise ValueError("constraint values must be nonempty strings")
    if "budget_minor" in result and (type(result["budget_minor"]) is not int or result["budget_minor"] < 0):
        raise ValueError("budget_minor must be a nonnegative integer")
    if result.get("language") and result["language"] not in {"ja", "en"}:
        raise ValueError("unsupported language")
    if result.get("set_code"):
        result["set_code"] = result["set_code"].upper()
    if result.get("collector_number"):
        result["collector_number"] = core.normalize_collector_number(result["collector_number"])
    if result.get("variant"):
        result["variant"] = result["variant"].lower()
    return result


def save_exploration(db: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    """Save a structured revision with optimistic version checking and no raw chat log."""
    core._required(row, "session_id", "owner_key", "expected_version")
    session_id, owner_key = str(row["session_id"]), str(row["owner_key"])
    prior = db.execute("SELECT * FROM exploration_session WHERE session_id=?", (session_id,)).fetchone()
    expected = row["expected_version"]
    if type(expected) is not int or expected < 0 or expected != (prior["version"] if prior else 0):
        raise ValueError("exploration version conflict")
    if prior and prior["owner_key"] != owner_key:
        raise ValueError("exploration owner mismatch")
    constraints = json.loads(prior["constraints_json"]) if prior else {}
    patch = _validate_constraints(row.get("constraints", {}))
    for key, value in row.get("constraints", {}).items():
        if value is None:
            constraints.pop(key, None)
    constraints.update(patch)
    shortlist = row.get("shortlist_card_ids", json.loads(prior["shortlist_json"]) if prior else [])
    if (not isinstance(shortlist, list) or len(shortlist) > 50
            or any(not isinstance(card_id, str) for card_id in shortlist)
            or len(shortlist) != len(set(shortlist))):
        raise ValueError("shortlist must contain at most 50 distinct card IDs")
    for card_id in shortlist:
        _card(db, card_id)
    target = row.get("target_card_id", prior["target_card_id"] if prior else None)
    if row.get("clear_target"):
        target = None
    if target:
        _card(db, target)
    status = row.get("status", "targeted" if target else "exploring")
    if status not in {"exploring", "targeted", "paused"} or (status != "paused" and (status == "targeted") != bool(target)):
        raise ValueError("targeted status requires an exact card; exploring status cannot hold one")
    now = core.parse_time(row.get("recorded_at") or core.utcnow()).isoformat()
    version = expected + 1
    snapshot = {"constraints": constraints, "shortlist_card_ids": shortlist,
                "target_card_id": target, "status": status}
    with db:
        if prior:
            changed = db.execute(
                """UPDATE exploration_session SET status=?, constraints_json=?, shortlist_json=?,
                target_card_id=?, version=?, updated_at=?
                WHERE session_id=? AND owner_key=? AND version=?""",
                (status, json.dumps(constraints, sort_keys=True), json.dumps(shortlist), target,
                 version, now, session_id, owner_key, expected),
            ).rowcount
            if changed != 1:
                raise ValueError("exploration version conflict")
        else:
            try:
                db.execute(
                    "INSERT INTO exploration_session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (session_id, owner_key, status, json.dumps(constraints, sort_keys=True),
                     json.dumps(shortlist), target, version, now, now),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("exploration version conflict") from exc
        db.execute("INSERT INTO exploration_revision VALUES (?, ?, ?, ?)",
                   (session_id, version, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now))
    return get_exploration(db, session_id, owner_key)


def get_exploration(db: sqlite3.Connection, session_id: str, owner_key: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM exploration_session WHERE session_id=? AND owner_key=?",
                     (session_id, owner_key)).fetchone()
    if row is None:
        raise ValueError("unknown exploration or owner")
    constraints = json.loads(row["constraints_json"])
    target = row["target_card_id"]
    card = _card(db, target) if target else None
    missing = []
    if not target:
        for field in ("query", "language", "set_code", "collector_number", "variant"):
            if not constraints.get(field):
                missing.append(field)
    return {"session_id": session_id, "status": row["status"], "version": row["version"],
            "constraints": constraints, "shortlist_card_ids": json.loads(row["shortlist_json"]),
            "target_card_id": target, "next_clarifications": missing,
            "ready_for_offer_tracking": bool(card and card["match_eligible"]),
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "scope": "internal structured intent; no live offers or user-facing display approval implied"}


def exploration_candidates(db: sqlite3.Connection, session_id: str, owner_key: str,
                           limit: int = 20) -> dict[str, Any]:
    """Retrieve internal card candidates for the latest structured constraints."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1–100")
    state = get_exploration(db, session_id, owner_key)
    filters = state["constraints"]
    shortlist = state["shortlist_card_ids"]
    if not shortlist and not any(filters.get(field) for field in
                                 ("query", "set_code", "collector_number")):
        return {"session_id": session_id, "cards": [], "total": 0,
                "reason": "add a card name, set code, collector number or shortlist"}
    rows = db.execute(
        """SELECT card_id, language, set_code, collector_number, variant, name, rarity,
        match_eligible, display_allowed FROM card
        WHERE (? IS NULL OR language=?) AND (? IS NULL OR set_code=?)
        AND (? IS NULL OR collector_number=?) AND (? IS NULL OR variant=?)
        ORDER BY match_eligible DESC, set_code, collector_number, variant""",
        (filters.get("language"), filters.get("language"),
         filters.get("set_code"), filters.get("set_code"),
         filters.get("collector_number"), filters.get("collector_number"),
         filters.get("variant"), filters.get("variant")),
    )
    terms = [term.casefold() for term in filters.get("query", "").split()]
    found = [{**dict(card), "matched_via": "catalog_text"} for card in rows
             if (not shortlist or card["card_id"] in shortlist)
             and all(term in f"{card['name']} {card['set_code']} {card['collector_number']}".casefold()
                     for term in terms)]
    # A reviewed JP↔EN edge can resolve a name in one language to a printing in
    # the requested language. No name/number coincidence creates such an edge.
    if terms and filters.get("language") and not filters.get("set_code"):
        seen = {card["card_id"] for card in found}
        for edge in db.execute(
            """SELECT a.*, l.name AS left_name, l.language AS left_language,
            r.name AS right_name, r.language AS right_language
            FROM card_relationship_assertion a
            JOIN card l ON l.card_id=a.left_card_id
            JOIN card r ON r.card_id=a.right_card_id
            WHERE a.relation_type='localization_counterpart' AND a.review_status='verified'
            AND a.rowid=(SELECT MAX(b.rowid) FROM card_relationship_assertion b
                         WHERE b.left_card_id=a.left_card_id AND b.right_card_id=a.right_card_id
                         AND b.relation_type=a.relation_type)"""
        ):
            if edge["left_language"] == filters["language"]:
                target_id, source_name = edge["left_card_id"], edge["right_name"]
            elif edge["right_language"] == filters["language"]:
                target_id, source_name = edge["right_card_id"], edge["left_name"]
            else:
                continue
            if target_id in seen or (shortlist and target_id not in shortlist):
                continue
            target = _card(db, target_id)
            if filters.get("collector_number") and target["collector_number"] != filters["collector_number"]:
                continue
            if filters.get("variant") and target["variant"] != filters["variant"]:
                continue
            if all(term in source_name.casefold() for term in terms):
                found.append({key: target[key] for key in
                              ("card_id", "language", "set_code", "collector_number", "variant",
                               "name", "rarity", "match_eligible", "display_allowed")}
                             | {"matched_via": "verified_localization_counterpart",
                                "relationship_assertion_id": edge["assertion_id"]})
                seen.add(target_id)
    return {"session_id": session_id, "cards": found[:limit], "total": len(found),
            "scope": "internal metadata; candidate is not an offer or verified counterpart"}

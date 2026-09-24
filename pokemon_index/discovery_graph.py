"""Internal, evidence-backed card relationships and structured discovery state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections import Counter
from typing import Any, Iterable

from . import core

RELATION_TYPES = {"localization_counterpart", "same_artwork", "collecting_alternative"}
REVIEW_STATUSES = {"proposed", "verified", "rejected"}
CONSTRAINT_FIELDS = {
    "query", "language", "set_code", "collector_number", "variant",
    "dex_id", "illustrator", "grade_company", "grade_value", "budget_minor",
    "currency", "destination",
}


def _card(db: sqlite3.Connection, card_id: str) -> sqlite3.Row:
    card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    if card is None:
        raise ValueError(f"unknown card {card_id!r}")
    return card


def assert_relationships(db: sqlite3.Connection, rows: Iterable[dict[str, Any]]) -> int:
    """Append review events. Repeating the current claim is idempotent; reversal is possible."""
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
        actor = str(row["asserted_by"])
        reviewer = str(row["reviewer"]) if row.get("reviewer") else None
        assertion = {
            "left_card_id": left, "right_card_id": right,
            "relation_type": row["relation_type"], "review_status": row["review_status"],
            "evidence_ref": row["evidence_ref"], "rights_reference": row["rights_reference"],
            "asserted_by": actor, "reviewer": reviewer,
        }
        event_id = row.get("assertion_id")
        if event_id is not None and (not isinstance(event_id, str) or not event_id.strip()):
            raise ValueError("assertion_id must be a nonempty string")
        prepared.append((event_id, assertion, asserted_at))
    count = 0
    with db:
        for event_id, assertion, asserted_at in prepared:
            fields = (assertion["left_card_id"], assertion["right_card_id"],
                      assertion["relation_type"], assertion["review_status"],
                      assertion["evidence_ref"], assertion["rights_reference"],
                      assertion["asserted_by"], assertion["reviewer"])
            if event_id:
                existing = db.execute(
                    "SELECT * FROM card_relationship_assertion WHERE assertion_id=?", (event_id,)
                ).fetchone()
                if existing:
                    stored = tuple(existing[key] for key in (
                        "left_card_id", "right_card_id", "relation_type", "review_status",
                        "evidence_ref", "rights_reference", "asserted_by", "reviewer"))
                    if stored != fields:
                        raise ValueError("assertion_id already belongs to a different event")
                    continue
            else:
                latest = db.execute(
                    """SELECT * FROM card_relationship_assertion
                    WHERE left_card_id=? AND right_card_id=? AND relation_type=?
                    ORDER BY rowid DESC LIMIT 1""", fields[:3]
                ).fetchone()
                if latest and tuple(latest[key] for key in (
                        "left_card_id", "right_card_id", "relation_type", "review_status",
                        "evidence_ref", "rights_reference", "asserted_by", "reviewer")) == fields:
                    continue
                event_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO card_relationship_assertion VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event_id, *fields, asserted_at),
            )
            count += 1
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
           for key, field in result.items() if key not in {"budget_minor", "dex_id"}):
        raise ValueError("constraint values must be nonempty strings")
    if "budget_minor" in result and (type(result["budget_minor"]) is not int or result["budget_minor"] < 0):
        raise ValueError("budget_minor must be a nonnegative integer")
    if "dex_id" in result and (type(result["dex_id"]) is not int or not 1 <= result["dex_id"] <= 9999):
        raise ValueError("dex_id must be a positive integer below 10000")
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
    old_target = prior["target_card_id"] if prior else None
    target = row.get("target_card_id", old_target)
    if row.get("clear_target"):
        target = None
    target_card = None
    if target:
        target_card = _card(db, target)
        for field in ("language", "set_code", "collector_number", "variant"):
            if constraints.get(field) and constraints[field] != target_card[field]:
                raise ValueError(f"selected target conflicts with {field}; clear or change the target")
    if "status" in row:
        status = row["status"]
    elif prior and prior["status"] == "paused":
        status = "paused"
    elif target != old_target:
        status = "targeted" if target else "exploring"
    else:
        status = prior["status"] if prior else ("targeted" if target else "exploring")
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
            "ready_for_offer_tracking": bool(row["status"] == "targeted" and card and card["match_eligible"]),
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
                                 ("query", "set_code", "collector_number", "dex_id", "illustrator")):
        return {"session_id": session_id, "cards": [], "total": 0,
                "facets": {}, "reason": "add a card name, set code, collector number or shortlist"}
    rows = db.execute(
        """SELECT card_id, language, set_code, collector_number, variant, name, rarity,
        match_eligible, display_allowed FROM card
        WHERE (? IS NULL OR language=?) AND (? IS NULL OR set_code=?)
        AND (? IS NULL OR collector_number=?) AND (? IS NULL OR variant=?)
        AND (? IS NULL OR EXISTS (SELECT 1 FROM card_facet f WHERE f.card_id=card.card_id
            AND f.facet_type='dex_id' AND f.value=?))
        AND (? IS NULL OR EXISTS (SELECT 1 FROM card_facet f WHERE f.card_id=card.card_id
            AND f.facet_type='illustrator' AND lower(f.value)=lower(?)))
        ORDER BY match_eligible DESC, set_code, collector_number, variant""",
        (filters.get("language"), filters.get("language"),
         filters.get("set_code"), filters.get("set_code"),
         filters.get("collector_number"), filters.get("collector_number"),
         filters.get("variant"), filters.get("variant"),
         filters.get("dex_id"), str(filters["dex_id"]) if filters.get("dex_id") else None,
         filters.get("illustrator"), filters.get("illustrator")),
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
    # A common dex ID expands a translated character name to *other cards of
    # that character*, never to a verified printing counterpart.
    if terms and filters.get("language") and not found:
        alias_ids = {}
        for source in db.execute(
            """SELECT c.card_id, c.name, f.value, f.provenance FROM card c JOIN card_facet f
            ON f.card_id=c.card_id WHERE c.language<>? AND f.facet_type='dex_id'
            AND (SELECT COUNT(*) FROM card_facet single_species
                 WHERE single_species.card_id=c.card_id AND single_species.facet_type='dex_id')=1""",
            (filters["language"],),
        ):
            if (not filters.get("dex_id") or source["value"] == str(filters["dex_id"])) and all(
                    term in source["name"].casefold() for term in terms):
                alias_ids.setdefault(source["value"], dict(source))
                if len(alias_ids) > 3:
                    break
        if 0 < len(alias_ids) <= 3:
            seen = set()
            for target in db.execute(
                """SELECT c.card_id, c.language, c.set_code, c.collector_number, c.variant,
                c.name, c.rarity, c.match_eligible, c.display_allowed,
                f.value AS dex_id, f.provenance AS facet_provenance
                FROM card c JOIN card_facet f ON f.card_id=c.card_id
                WHERE c.language=? AND f.facet_type='dex_id'
                ORDER BY c.match_eligible DESC, c.set_code, c.collector_number, c.variant""",
                (filters["language"],),
            ):
                if target["dex_id"] not in alias_ids or target["card_id"] in seen:
                    continue
                if shortlist and target["card_id"] not in shortlist:
                    continue
                if any(filters.get(field) and target[field] != filters[field]
                       for field in ("set_code", "collector_number", "variant")):
                    continue
                if filters.get("illustrator") and not db.execute(
                    """SELECT 1 FROM card_facet WHERE card_id=? AND facet_type='illustrator'
                    AND lower(value)=lower(?)""", (target["card_id"], filters["illustrator"])
                ).fetchone():
                    continue
                source = alias_ids[target["dex_id"]]
                found.append({key: target[key] for key in
                              ("card_id", "language", "set_code", "collector_number", "variant",
                               "name", "rarity", "match_eligible", "display_allowed")}
                             | {"matched_via": "same_character",
                                "character_dex_id": int(target["dex_id"]),
                                "character_evidence": {
                                    "source_card_id": source["card_id"],
                                    "source_provenance": source["provenance"],
                                    "target_provenance": target["facet_provenance"]}})
                seen.add(target["card_id"])
    facets = {}
    for field in ("language", "set_code", "collector_number", "variant"):
        counts = Counter(str(card[field]) for card in found)
        facets[field] = {"distinct_count": len(counts),
                         "values": [value for value, _ in counts.most_common(12)]}
    return {"session_id": session_id, "cards": found[:limit], "total": len(found),
            "facets": facets,
            "scope": "internal metadata; candidate is not an offer or verified counterpart"}


def exploration_decision(db: sqlite3.Connection, session_id: str,
                         owner_key: str) -> dict[str, Any]:
    """Return one explainable next step without claiming a live price or sale."""
    state = get_exploration(db, session_id, owner_key)
    candidates = exploration_candidates(db, session_id, owner_key, limit=20)
    pending_market_filters = [field for field in ("grade_company", "grade_value", "budget_minor",
                                                  "currency", "destination")
                              if field in state["constraints"]]
    decision: dict[str, Any] = {
        "session_id": session_id, "session_version": state["version"],
        "target_card_id": state["target_card_id"],
        "candidate_count": candidates["total"],
        "candidate_cards": candidates["cards"],
        "ready_for_offer_tracking": state["ready_for_offer_tracking"],
        "pending_market_filters": pending_market_filters,
        "market_filter_note": "budget, grade and destination are saved but cannot filter cards or offers until authorized offer data exists",
        "scope": "internal catalog discovery; no live offers, market price or purchase recommendation",
    }
    if state["status"] == "paused":
        decision.update(code="paused", next_question={"field": "status", "prompt": "Resume this exploration?"})
    elif state["target_card_id"]:
        if not state["ready_for_offer_tracking"]:
            decision.update(code="target_unverified", next_question={
                "field": "printing_evidence", "prompt": "Confirm the exact printing before tracking offers."})
        else:
            decision.update(code="target_selected", next_question=None)
    elif not candidates["total"]:
        decision.update(code="no_matches", next_question={
            "field": "query", "prompt": "Try a different card name, set or collector number."})
    elif candidates["total"] == 1:
        card = candidates["cards"][0]
        if card["match_eligible"]:
            decision.update(code="confirm_target", next_question={
                "field": "target_card_id", "prompt": "Is this the exact printing you want to track?",
                "options": [card["card_id"]]})
        else:
            decision.update(code="unverified_printing", next_question={
                "field": "printing_evidence", "prompt": "This printing needs verification before offer tracking."})
    else:
        facets = candidates["facets"]
        field = next((name for name in ("language", "set_code", "collector_number", "variant")
                      if facets[name]["distinct_count"] > 1), None)
        decision.update(
            code="multiple_printings" if field == "variant" else "narrow_candidates",
            next_question={"field": field, "prompt": f"Which {field} do you mean?",
                           "options": facets[field]["values"]} if field else {
                               "field": "target_card_id", "prompt": "Which exact card do you mean?",
                               "options": [card["card_id"] for card in candidates["cards"]]},
        )
    return decision

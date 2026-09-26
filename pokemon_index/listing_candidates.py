"""Retrieve internal card candidates for listing-photo review, never price matching.

This path deliberately includes match-disabled identities and cards whose name
conflicts with the title. A visual pass must resolve the physical printing.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from typing import Any

from . import core

SET_TOKEN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z][A-Za-z0-9.+-]{0,15}(?![A-Za-z0-9])")
PROMO_NUMBER = re.compile(r"(?<!\d)\d{1,3}/(?:SV-P|S-P|SM-P|XY-P)(?![A-Za-z0-9])", re.I)
LEGACY_SET_ALIASES = {
    "DP6": ("DPS-B",), "BW3": ("BW3-BH", "BW3-BP"),
    "BW4": ("BW4-B",), "BW6": ("BW6-BC", "BW6-BF"),
    "BW7": ("BW7-B",),
}


def _set_evidence(title: str, known: set[str]) -> tuple[set[str], str]:
    tokens = {match.group(0).upper() for match in SET_TOKEN.finditer(title)}
    codes = tokens & known
    if ("MEGAドリーム" in title.upper() or "メガドリーム" in title) and "M2A" in known:
        return {"M2A"}, "set_name"
    if "M2A" in codes:
        codes.discard("MA")
    if "S6A" in codes:
        codes.discard("SA")
    aliases = tokens & LEGACY_SET_ALIASES.keys()
    if len(aliases) == 1:
        alias = next(iter(aliases))
        return (set(LEGACY_SET_ALIASES[alias]) & known) | (codes - {alias}), "legacy_alias"
    if codes == {"MA"} or (codes == {"SA"} and "/069" in title):
        return set(), "artwork_shorthand"
    return codes, "exact_set_code" if codes else "none"


def retrieve(db: sqlite3.Connection, title: str, limit: int = 12) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip() or not 1 <= limit <= 50:
        raise ValueError("title and a limit from 1 to 50 are required")
    normalized = unicodedata.normalize("NFKC", title)
    base = {"status": "none", "title": title, "candidate_count": 0,
            "candidates": [], "scope": "internal visual-review retrieval only; no offer resolution"}
    if core.BUNDLE_RE.search(normalized):
        return {**base, "status": "excluded_bundle"}
    numbers = {core.normalize_collector_number(value)
               for value in core.NUMBER_RE.findall(normalized)}
    if len(numbers) > 1 or PROMO_NUMBER.search(normalized):
        return {**base, "status": "ambiguous_identifiers"}
    known = {row[0] for row in db.execute("SELECT DISTINCT set_code FROM card")}
    codes, set_signal = _set_evidence(normalized, known)
    if not numbers and not codes:
        return {**base, "status": "need_set_or_number"}
    params: list[str] = []
    clauses = []
    if numbers:
        clauses.append("collector_number=?")
        params.append(next(iter(numbers)))
    if codes:
        clauses.append("set_code IN (" + ",".join("?" for _ in codes) + ")")
        params.extend(sorted(codes))
    rows = db.execute(
        """SELECT c.card_id,c.language,c.set_code,c.collector_number,c.variant,
        c.name,c.rarity,c.match_eligible,c.provenance,e.official_printing_type
        FROM card c LEFT JOIN card_identity_exception e ON e.card_id=c.card_id
        WHERE """ + " AND ".join("c." + clause for clause in clauses), params).fetchall()
    compact_title = core._compact_identity_text(normalized)
    candidates = []
    for row in rows:
        name_match = core._compact_identity_text(row["name"]) in compact_title
        # A bare collector number occurs in many unrelated sets. It needs a
        # visible name signal before it is useful even as a review candidate.
        if numbers and not codes and not name_match:
            continue
        if not numbers and not name_match:
            continue
        signal = ("set_number_name" if numbers and codes and name_match else
                  "set_number_name_conflict" if numbers and codes else
                  "number_name" if numbers else "set_name")
        candidates.append({"card_id": row["card_id"], "language": row["language"],
                           "set_code": row["set_code"],
                           "collector_number": row["collector_number"],
                           "name": row["name"], "variant": row["variant"],
                           "official_printing_type": row["official_printing_type"],
                           "rarity": row["rarity"],
                           "match_eligible": bool(row["match_eligible"]),
                           "retrieval_signal": signal,
                           "metadata_provenance": row["provenance"]})
    priority = {"set_number_name": 0, "number_name": 1, "set_name": 2,
                "set_number_name_conflict": 3}
    candidates.sort(key=lambda item: (priority[item["retrieval_signal"]],
                                      not item["match_eligible"], item["card_id"]))
    return {**base, "status": "candidate_only" if candidates else "none",
            "candidate_count": len(candidates), "candidates": candidates[:limit],
            "truncated": len(candidates) > limit, "set_signal": set_signal,
            "collector_number": next(iter(numbers)) if numbers else None}

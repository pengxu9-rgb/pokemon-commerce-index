"""Read-only handoff contract for Pivota's catalog resolver and offer lane."""

from __future__ import annotations

import sqlite3
from typing import Any

from . import core


def export_card(db: sqlite3.Connection, card_id: str, destination: str,
                as_of: str | None = None) -> dict[str, Any]:
    """Build a reviewable candidate. This does not write to Pivota's database.

    Pivota owns content_key assignment. A card edition is the family; grade and
    raw condition remain separate units so offer prices cannot be conflated.
    """
    card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
    if not card:
        raise ValueError("unknown card")
    if not card["display_allowed"]:
        raise ValueError("catalog source is not approved for display")
    if not destination:
        raise ValueError("destination is required")
    unit_rows = []
    for unit in core.units_for_card(db, card_id):
        mapped_offers = []
        for offer in core.offers(db, card_id, destination, as_of, unit["unit_id"]):
            quote = offer.get("quote")
            mapped_offers.append({
                "source": offer["source"],
                "source_listing_id": offer["native_id"],
                "source_url": offer["url"],
                "title": offer["title"],
                "observed_at": offer["last_seen"],
                "ask": {"amount_minor": offer["current_price_minor"],
                        "currency": offer["currency"]},
                "landed_quote": ({"amount_minor": quote["total_minor"],
                                  "currency": quote["currency"],
                                  "expires_at": quote["expires_at"],
                                  "evidence_ref": quote["evidence_ref"]}
                                 if quote else None),
                "offer_source": "external_referral",
                "purchasable": False,
                "purchase_action": None,
            })
        unit_rows.append({
            "unit_id": unit["unit_id"],
            "grade_company": unit["grade_company"],
            "grade_value": unit["grade_value"],
            "condition_bucket": unit["condition_bucket"],
            "pivota_content_key": None,
            "offers": mapped_offers,
        })
    return {
        "contract": "pokemon-commerce-to-pivota.v1",
        "candidate_only": True,
        "destination": destination,
        "card": {"card_id": card["card_id"], "language": card["language"],
                 "set_code": card["set_code"],
                 "collector_number": card["collector_number"],
                 "variant": card["variant"], "name": card["name"],
                 "rarity": card["rarity"], "provenance": card["provenance"],
                 "rights_reference": card["rights_reference"]},
        "priceable_units": unit_rows,
        "identity_rule": "Pivota resolver assigns content_key; grade/condition must remain distinct",
    }

"""Disposable synthetic offer → URL-in BNS quote rehearsal, with sockets denied."""
from __future__ import annotations

import argparse
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from pokemon_index import buyship_partner, core

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-20T00:05:00Z"
CARD = "ja:SV2A:173/165:standard"


def rehearse() -> dict:
    """No database input, persisted offers, recommendations or order/payment action."""
    with patch("socket.create_connection", side_effect=AssertionError("offline rehearsal")), \
            patch("socket.socket.connect", side_effect=AssertionError("offline rehearsal")), \
            closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        core.init_db(db)
        core.register_source(db, {"source": "licensed_fixture",
            "rights_reference": "synthetic offline rehearsal only", "ingest_allowed": True,
            "display_allowed": True, "partner_handoff_allowed": True,
            "partner_quote_store_allowed": False, "retention_days": 1, "listing_ttl_hours": 1})
        core.import_cards(db, [{"match_eligible": True, "language": "ja", "set_code": "SV2a",
            "collector_number": "173/165", "variant": "standard", "name": "ピカチュウ AR",
            "rarity": "AR", "provenance": "synthetic test", "rights_reference": "synthetic test",
            "display_allowed": True}])
        fixture = json.loads((ROOT / "examples/buyship_partner_preview.json").read_text())
        fixture["quote"]["expires_at"] = "2026-10-20T00:20:00Z"
        previews, requests = [], []
        for native_id, grade_text in (("demo-2", ""), ("demo-slab", " PSA 10 鑑定品")):
            url = "https://example.invalid/" + native_id
            core.import_observations(db, [{"source": "licensed_fixture", "native_id": native_id,
                "title": "ピカチュウ AR SV2a 173/165" + grade_text, "url": url,
                "language": "ja", "observed_at": "2026-10-20T00:00:00Z", "status": "on_sale",
                "price_minor": 380000, "currency": "JPY", "evidence_ref": "synthetic:offline:" + native_id}])
            unit = db.execute("SELECT unit_id FROM listing WHERE native_id=?", (native_id,)).fetchone()[0]
            response = copy.deepcopy(fixture)
            response["resolve"]["url"] = url
            client = buyship_partner.FixturePartnerClient(response)
            previews.append(buyship_partner.preview_quote(db, card_id=CARD, unit_id=unit,
                source="licensed_fixture", native_id=native_id, destination={"country": "HK"},
                client=client, now=NOW))
            requests.extend(client.calls)
        stored = db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0]
        return {"schema": "pokemon.c2c-bns-offline-rehearsal.v1", "mode": "synthetic_only",
                "network_access": "socket connections denied", "network_calls": 0,
                "production_database_opened": False, "real_offers_imported": 0,
                "stored_quotes": stored, "real_verified_psa_inventory": 0,
                "order_created": False, "purchasable": False, "purchase_action": None,
                "fixture_requests": requests, "previews": previews}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON report; no database is opened")
    args = parser.parse_args()
    report = json.dumps(rehearse(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(report)
    else:
        print(report, end="")


if __name__ == "__main__":
    main()

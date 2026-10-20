"""Offline, disposable multi-market native-ask tracking rehearsal."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch

from pokemon_index import core, ingestion_worker as worker

CARD_ID = "ja:SV2A:173/165:standard"
RAW_UNIT = CARD_ID + "|RAW|raw|unknown"
PSA9_UNIT = CARD_ID + "|PSA|9|graded"
PSA10_UNIT = CARD_ID + "|PSA|10|graded"
SOURCES = ("mercari_fixture", "ebay_fixture", "snkrdunk_fixture")


def deny_network():
    """Return a context that denies TCP and datagram outbound socket entry points."""
    context = ExitStack()
    for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex",
                   "socket.socket.sendto", "socket.socket.sendmsg", "socket.getaddrinfo"):
        context.enter_context(patch(target, side_effect=AssertionError("offline rehearsal denies network")))
    return context


def build_fixture(database: Path, *, now: str | None = None) -> dict:
    """Create only a new synthetic database; never open existing market state."""
    database = Path(database)
    if database.exists():
        raise FileExistsError("fixture database must be a new path")
    database.parent.mkdir(parents=True, exist_ok=True)
    stamp = core.parse_time(now or core.utcnow())
    def at(minutes):
        return (stamp - timedelta(minutes=minutes)).isoformat()
    def row(source, native, minutes, amount, *, grade=None, currency="JPY", status="on_sale"):
        suffix = f" PSA {grade} 鑑定品" if grade else ""
        return dict(source=source, native_id=native,
                    title="ピカチュウ SV2a 173/165" + suffix,
                    url=f"https://{source.replace('_', '-')}.invalid/{native}",
                    language="ja", observed_at=at(minutes), status=status,
                    price_minor=amount, currency=currency,
                    evidence_ref=f"synthetic:{source}:{native}:{minutes}:{status}:{amount}")
    alpha, beta, gamma = SOURCES
    rows = [
        row(alpha, "stale-a", 120, 999),
        row(alpha, "raw-a", 45, 1000),
        row(alpha, "sold-a", 45, 1550),
        row(alpha, "gone-a", 45, 1600),
        row(alpha, "raw-a", 30, 1100),
        row(alpha, "raw-a2", 30, 1500),
        row(alpha, "psa9-a", 30, 8000, grade="9"),
        row(alpha, "psa10-a", 30, 12000, grade="10"),
        row(beta, "raw-b", 30, 1300),
        row(beta, "psa10-b", 30, 14000, grade="10"),
        row(gamma, "raw-c", 30, 1200, currency="USD"),
        row(gamma, "psa10-c", 30, 18000, grade="10", currency="USD"),
        row(alpha, "raw-a", 15, 1100),
        row(alpha, "sold-a", 5, 1550, status="sold_out"),
        row(alpha, "gone-a", 5, 1600, status="gone"),
    ]
    with closing(core.connect(database)) as db:
        core.init_db(db)
        for source in SOURCES:
            core.register_source(db, dict(source=source, rights_reference="synthetic local rehearsal only",
                ingest_allowed=True, display_allowed=True, price_statistics_allowed=True,
                cross_source_use_allowed=True, seller_analytics_allowed=False,
                media_ai_allowed=False, partner_handoff_allowed=False,
                partner_quote_store_allowed=False, retention_days=7, listing_ttl_hours=1))
        core.import_cards(db, [dict(language="ja", set_code="SV2a", collector_number="173/165",
            variant="standard", name="ピカチュウ", provenance="synthetic local rehearsal",
            rights_reference="synthetic local rehearsal only", display_allowed=True,
            match_eligible=True)])
        worker.initialize(db)
        receipts = []
        for number, observation in enumerate(rows):
            source, observed = observation["source"], observation["observed_at"]
            worker.enqueue(db, f"fixture-{number:02}", source,
                           {"native_ids": [observation["native_id"]]}, now=observed)
            result = worker.run_next(db, lambda request, item=observation: [item],
                                     source=source, now=observed)
            if result["status"] != "done":
                raise AssertionError(f"fixture ingestion failed: {result}")
            receipts.append(result)
        # An exact replay exercises immutable receipts without creating an observation.
        replay = rows[4]
        worker.enqueue(db, "fixture-exact-replay", alpha, {"native_ids": [replay["native_id"]]}, now=stamp.isoformat())
        replay_result = worker.run_next(db, lambda _: [replay], source=alpha, now=stamp.isoformat())
        if replay_result.get("duplicates") != 1:
            raise AssertionError("fixture replay was not deduplicated")
        counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("listing", "observation", "landed_quote", "verified_sale")}
    return dict(as_of=stamp.isoformat(), card_id=CARD_ID, sources=list(SOURCES),
                synthetic=True, ingestion=receipts, replay=replay_result, counts=counts)


def rehearse() -> dict:
    from pokemon_index.market_tracking import build_report
    with deny_network(), tempfile.TemporaryDirectory(prefix="market-tracking-offline-") as directory:
        database = Path(directory) / "synthetic.sqlite3"
        fixture = build_fixture(database)
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        report = build_report(database, CARD_ID, now=fixture["as_of"], history_days=7,
                              sources=list(SOURCES))
        after = hashlib.sha256(database.read_bytes()).hexdigest()
        groups = [group for platform in report["platforms"] for group in platform["groups"]]
        current = {(platform["source"], offer["native_id"])
                   for platform in report["platforms"] for group in platform["groups"]
                   for offer in group["offers"]}
        alpha_raw = next(group for platform in report["platforms"] if platform["source"] == SOURCES[0]
                         for group in platform["groups"] if group["unit_id"] == RAW_UNIT)
        alpha_events = next(platform["listing_events"] for platform in report["platforms"]
                            if platform["source"] == SOURCES[0])
        checks = dict(three_platforms=len(report["platforms"]) == 3,
            raw_psa9_psa10_separate={group["unit_id"] for group in groups} == {RAW_UNIT, PSA9_UNIT, PSA10_UNIT},
            currencies_separate={group["currency"] for group in groups} == {"JPY", "USD"},
            repeated_polls_not_extra_listings=alpha_raw["listing_count"] == 2,
            median_preserves_native_minor_precision=alpha_raw["median_ask_minor_decimal"] == "1300",
            terminal_and_stale_not_current=not any(native in {"stale-a", "sold-a", "gone-a"}
                                                   for source, native in current),
            price_change_retained=[event["price_minor"] for event in alpha_events
                                   if event["native_id"] == "raw-a"] == [1000, 1100, 1100],
            status_events_retained={event["status"] for event in alpha_events} >= {"on_sale", "sold_out", "gone"},
            no_quote_or_paid_records=fixture["counts"]["landed_quote"] == fixture["counts"]["verified_sale"] == 0,
            database_bytes_unchanged=before == after,
            native_listing_asks_only=report["price_type"] == "native_listing_ask",
            explicit_sources_preserved=set(report["requested_sources"]) == set(SOURCES),
            no_live_collection_claim=report["data_readiness"]["live_source_collection_verified"] is False)
        return dict(schema="pokemon.offline-multi-market-tracking-rehearsal.v1",
            network_calls=0, network_access="socket entry points denied", synthetic_only=True,
            no_real_marketplace_observations=True, purchase_action=None,
            database_sha256_before=before, database_sha256_after=after,
            fixture=fixture, report=report, checks=checks, passed=all(checks.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    result = rehearse()
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"]}))
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()

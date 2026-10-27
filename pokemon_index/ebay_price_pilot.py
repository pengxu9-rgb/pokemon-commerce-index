"""A default-off, process-memory-only rehearsal of five current eBay asks.

This bypasses managed chat/conversation history entirely. It never writes or
prints listing data. The explicit ``report`` result is for a transient view;
callers must not persist it. This helper does not certify deletion-notice
exemption or complete the managed-chat integration.

``python -m pokemon_index.ebay_price_pilot`` prints a zero-network plan.
Only ``--execute`` can request a token; all access gates still apply.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re

from .commerce_loop import CommerceLoop
from .ebay_official import BrowseClient, EbayOfficialCrawler, OfficialEbayError

CANDIDATE_LIMIT = 5
REQUEST_BUDGET = 7  # one token, one search, at most five exact-item refreshes


class MemoryPricePilotResult:
    """Only the explicit report attribute carries marketplace data."""
    __slots__ = ("report", "receipt")

    def __init__(self, report, receipt):
        self.report, self.receipt = report, receipt

    def __repr__(self):
        return f"<MemoryPricePilotResult status={self.receipt['status']!r}; report omitted>"


class _NoFallback:
    def search(self, *_args, **_kwargs):
        raise OfficialEbayError("ebay_price_pilot_fallback_forbidden")

    detail = search


class _NoSecondSearch(EbayOfficialCrawler):
    def search(self, source, query, limit=3):
        # An empty or entirely unsupported search response is not permission
        # to repeat the search through CommerceLoop's no-URL path.
        return {"source": "ebay_us", "status": "no_results", "listings": []}


def _utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError()
    return value


def run_memory_price_pilot(env, *, card_id=None, query=None, read_until=None,
                           execute=False, transport=None, now=None):
    """Return a transient research DTO, never an order/quote/history artifact.

    An injected transport is always labelled synthetic, even when it exercises
    production-shaped item responses. The operational receipt/repr excludes
    listing fields, exact result counts, URLs, IDs and payloads; it includes
    only outcome and budget telemetry, not proof of deletion-waiver eligibility.
    """
    receipt = {"schema": "pokemon.ebay-memory-price-pilot.v1", "status": "prepared",
        "mode": "synthetic_fixture" if transport is not None else "live_access_not_started",
        "candidate_limit": CANDIDATE_LIMIT, "http_attempt_budget": REQUEST_BUDGET,
        "http_budget_reservations": 0, "data_written_by_helper": False,
        "managed_chat_verified": False, "orders": 0, "payments": 0,
        "bns_calls": 0, "psa_calls": 0}
    if execute is not True:
        return MemoryPricePilotResult(None, receipt)
    clock = now or (lambda: datetime.now(timezone.utc))
    client = None
    try:
        start, end = _utc(clock()), _utc(read_until)
        if not 0 < (end - start).total_seconds() <= 15 * 60:
            raise ValueError()
        if (not isinstance(card_id, str) or not 1 <= len(card_id.strip()) <= 240
                or not isinstance(query, str) or not 2 <= len(query.strip()) <= 120
                or re.search(r"[\x00-\x1f\x7f]", card_id + query)):
            raise ValueError()
        if (any(key in env and env[key] != "production" for key in
                ("EBAY_ENVIRONMENT", "EBAY_API_ENVIRONMENT"))
                or any(key in env for key in ("EBAY_API_BASE_URL", "EBAY_BASE_URL",
                    "EBAY_BROWSE_BASE_URL", "EBAY_TOKEN_URL", "EBAY_API_URL", "EBAY_SANDBOX"))):
            raise ValueError()
        # EPN is deliberately absent from this first price-only pilot. These
        # are the only credentials/configuration consumed from the process.
        client = BrowseClient(env.get("EBAY_CLIENT_ID"), env.get("EBAY_CLIENT_SECRET"),
            allow_network=True, production_approved=env.get("EBAY_PRODUCTION_APPROVED") == "true",
            display_approved=env.get("EBAY_DISPLAY_APPROVED") == "true", read_until=end,
            request_budget=REQUEST_BUDGET, transport=transport, now=clock)
        searched = client.search(query, limit=CANDIDATE_LIMIT)
        urls = [row["url"] for row in searched["listings"]]
        producer = (EbayOfficialCrawler if urls else _NoSecondSearch)(_NoFallback(), client)
        loop = CommerceLoop(producer, now=lambda: _utc(clock()).isoformat())
        report = loop.research("memory-price-pilot", {"card_id": card_id, "query": query,
            "platforms": ["ebay_us"], "product_urls": urls})
        client._check()
        # Price discovery only: no onward provider operation is exposed here.
        report["forwarders"] = []
        report["pilot_evidence"] = {"process_memory_only": True,
            "transport": "injected_test_transport" if transport is not None else "official_ebay",
            "managed_chat_verified": False}
        current = [o for o in report["offers"] if o["availability"] == "available"
                   and o["currency"] == "USD" and type(o["price_minor"]) is int]
        receipt["status"] = "ready_for_review" if len(current) == CANDIDATE_LIMIT else "partial"
        receipt["mode"] = "synthetic_fixture" if transport is not None else "official_ebay"
        if transport is not None:
            report["mode"] = "synthetic_fixture"
            for offer in report["offers"]:
                offer["synthetic"] = True
            for platform in report["platforms"]:
                platform.update(status="synthetic_fixture",
                    message="Synthetic injected responses; no real marketplace was contacted.")
            report["marketplace_connections"][0].update(status="configured_offline",
                message="Offline injected transport; official eBay access was not tested.")
        return MemoryPricePilotResult(report, receipt)
    except Exception:
        # Never echo the query, response, transport exception or credentials.
        receipt.update(status="blocked", error="ebay_price_pilot_configuration_or_read_failed")
        return MemoryPricePilotResult(None, receipt)
    finally:
        if client is not None:
            receipt["http_budget_reservations"] = REQUEST_BUDGET - client._remaining
            # Drop token/credential references held by this transient client.
            # Python string storage is not claimed to be securely overwritten.
            client._token = client._id = client._secret = None


def main(argv=None, *, env=None, transport=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--card-id")
    parser.add_argument("--query")
    parser.add_argument("--read-until", help="explicit future UTC end, at most15minutes away")
    args = parser.parse_args(argv)
    result = run_memory_price_pilot(os.environ if env is None else env,
        card_id=args.card_id, query=args.query, read_until=args.read_until,
        execute=args.execute, transport=transport, now=now)
    print(json.dumps(result.receipt, sort_keys=True))
    result.report = None
    return 0 if result.receipt["status"] in {"prepared", "ready_for_review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

"""Disposable, quote-only BNS workers for the authenticated chat sidecar.

Each handoff gets a fresh OAuth client and three-request sender. The parent
kills and reaps the worker on timeout, so DNS/body/SQLite waits cannot leave a
provider request running after its deadline. No client token is shared across
handoffs and no database writes, orders or payments are implemented here.
"""
from __future__ import annotations

from datetime import timedelta
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from .bns_transport import BNS_PATHS, OneShotBNSSender, _base_url, _destination
from .buyship_partner import PartnerClient, QUOTE_COMPONENTS, _buyer_labels, _money, _preview_digest, _require_preview_binding
from .commerce_loop import BoundBuyShipForwarder, _quote_block_reason, _time, utcnow
from .marketplace_crawl import canonical_product_url
from .psa_cert import _response

REQUEST_SCHEMA = "pokemon.bounded-buyship-request.v1"
RESULT_SCHEMA = "pokemon.bounded-buyship-result.v1"
WORKER_SECONDS = 18
MAX_BYTES = 65536
_ACTIVE_WORKER = threading.Lock()


def _unavailable():
    return ValueError("bounded Buy&Ship quote unavailable")


def _text(value, maximum=300):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum and all(ord(c) >= 32 for c in value)


def _exact_money(value, currency=None):
    if (not isinstance(value, dict) or set(value) != {"currency", "subunit_amount"}
            or not isinstance(value["currency"], str) or not re.fullmatch(r"[A-Z]{3}", value["currency"])):
        raise _unavailable()
    result = _money(value, currency)
    if result["subunit_amount"] > 2**53 - 1:
        raise _unavailable()
    return result


def _research(offer, destination):
    if not _destination(destination) or not isinstance(offer, dict) or _quote_block_reason(offer):
        raise _unavailable()
    source, native, url = canonical_product_url(offer.get("url"))
    if (source != offer.get("source") or native != offer.get("native_id") or url != offer.get("url")
            or offer.get("authenticity_verified") is not False
            or not isinstance(offer.get("grade"), dict) or offer["grade"].get("certificate_verified") is not False):
        raise _unavailable()
    instant, observed, expires = _time(utcnow()), _time(offer.get("observed_at")), _time(offer.get("fresh_until"))
    if not instant - timedelta(seconds=300) <= observed <= instant < expires <= observed + timedelta(seconds=300):
        raise _unavailable()


def _validate_quote(quote, card_id, offer, destination):
    """Validate the IPC result as well as the worker's frozen quote gate."""
    fields = {"status", "purchasable", "purchase_action", "order_created", "card_id", "unit_id",
              "listing", "buyer_labels", "buyship", "evidence"}
    if (not isinstance(quote, dict) or set(quote) != fields or quote.get("status") != "quote_ready_for_review"
            or quote.get("card_id") != card_id or quote.get("purchasable") is not False
            or quote.get("order_created") is not False or quote.get("purchase_action") is not None):
        raise _unavailable()
    _require_preview_binding(quote)
    listing, bns, labels = quote["listing"], quote["buyship"], quote["buyer_labels"]
    expected_labels = _buyer_labels({"title": offer["title"], "grade_company": offer["grade"]["company"] or "RAW",
                                    "grade_value": offer["grade"]["value"]})
    if (set(listing) != {"source", "native_id", "url", "title", "observed_at", "ask", "evidence_ref", "identity_basis"}
            or any(listing.get(key) != offer.get(key) for key in ("source", "native_id", "url", "title"))
            or listing.get("ask") != {"currency": offer["currency"], "subunit_amount": offer["price_minor"]}
            or bns.get("canonical_url") != offer["url"] or bns.get("destination") != destination
            or labels != expected_labels
            or any(labels.get(key) is not False for key in ("certificate_verified", "authenticity_verified", "physical_inspection_performed"))
            or type(labels.get("real_verified_psa_inventory")) is not int):
        raise _unavailable()
    if (set(bns) != {"reference_id", "variant_key", "canonical_url", "merchant_domain", "resolve_price",
                    "resolve_price_differs_from_observation", "quote_id", "expires_at", "quoted_at",
                    "destination", "currency", "unit_price", "components", "grand_total"}
            or set(bns["components"]) != set(QUOTE_COMPONENTS)):
        raise _unavailable()
    if (not all(_text(value) for value in (quote["unit_id"], bns["quote_id"], bns["reference_id"], bns["variant_key"]))
            or bns["merchant_domain"] is not None and (not _text(bns["merchant_domain"], 253)
                or not re.fullmatch(r"[A-Za-z0-9.-]+", bns["merchant_domain"]))
            or not isinstance(bns["currency"], str) or not re.fullmatch(r"[A-Z]{3}", bns["currency"])
            or type(bns["resolve_price_differs_from_observation"]) is not bool):
        raise _unavailable()
    _exact_money(bns["unit_price"], bns["currency"])
    _exact_money(bns["resolve_price"])
    total = _exact_money(bns["grand_total"], bns["currency"])
    if sum(_exact_money(bns["components"][key], bns["currency"])["subunit_amount"] for key in QUOTE_COMPONENTS) != total["subunit_amount"]:
        raise _unavailable()
    evidence = quote["evidence"]
    hashes = {"observation_sha256", "listing_snapshot_sha256", "resolve_response_sha256",
              "quote_response_sha256", "binding_sha256", "observation_quality_sha256"}
    if (set(evidence) != hashes | {"schema", "mode", "binding_scope", "limitations"}
            or evidence["schema"] != "pokemon.buyship-quote-evidence.v1"
            or evidence["mode"] != "injected_test_transport"
            or any(not isinstance(evidence[key], str) or not re.fullmatch(r"[0-9a-f]{64}", evidence[key]) for key in hashes)
            or not _text(evidence["binding_scope"])
            or not isinstance(evidence["limitations"], list) or len(evidence["limitations"]) != 3
            or any(not _text(value) for value in evidence["limitations"])):
        raise _unavailable()
    if not _time(bns["quoted_at"]) <= _time(utcnow()) < _time(bns["expires_at"]):
        raise _unavailable()
    return quote


def _preview(payload, *, env=None, transport=None):
    """Worker implementation. Tests may inject wire fixtures without networking."""
    env = os.environ if env is None else env
    if (not isinstance(payload, dict) or set(payload) != {"schema", "database", "card_id", "offer", "destination", "deadline"}
            or payload["schema"] != REQUEST_SCHEMA or type(payload["deadline"]) not in (int, float)
            or not math.isfinite(payload["deadline"]) or time.monotonic() >= payload["deadline"]):
        raise _unavailable()
    _research(payload["offer"], payload["destination"])
    gate = BoundBuyShipForwarder(payload["database"], None)
    expected = gate._indexed_binding(payload["card_id"], payload["offer"], payload["destination"], deadline=payload["deadline"])

    def guard():
        current = gate._indexed_binding(payload["card_id"], payload["offer"], payload["destination"], deadline=payload["deadline"])
        if current != expected:
            raise _unavailable()

    sender = OneShotBNSSender(env["BNS_PARTNER_BASE_URL"], authorized=True, transport=transport,
                             deadline=payload["deadline"], before_request=guard)
    client = PartnerClient(sender.base_url, env["BNS_PARTNER_CLIENT_ID"], env["BNS_PARTNER_CLIENT_SECRET"],
                           sender=sender, live_authorized=True)
    quote = BoundBuyShipForwarder(payload["database"], client).preview(payload["card_id"], payload["offer"], payload["destination"])
    if sender.requests != list(BNS_PATHS) or time.monotonic() >= payload["deadline"]:
        raise _unavailable()
    guard()
    # Add the additive seller-quality binding without modifying the frozen
    # adapter. Its digest includes the extension; its legacy mode is retained.
    quote["evidence"]["observation_quality_sha256"] = expected[2]
    quote["evidence"]["binding_sha256"] = _preview_digest(quote)
    return _validate_quote(quote, payload["card_id"], payload["offer"], payload["destination"])


def _worker():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        _, payload = _response({"status": 200, "body": raw}, MAX_BYTES)
        result = {"schema": RESULT_SCHEMA, "quote": _preview(payload)}
        encoded = json.dumps(result, allow_nan=False)
        if len(encoded.encode()) > MAX_BYTES:
            raise _unavailable()
    except Exception:
        encoded = json.dumps({"schema": RESULT_SCHEMA, "error": "quote_unavailable"})
    print(encoded)


class BoundedBuyShipForwarder:
    id, label = "buyship", "Buy & Ship"

    def __init__(self, database, base_url, client_id, client_secret, *, live_authorized=False,
                 runner=None, monotonic=time.monotonic):
        self.database = Path(database).resolve()
        if not self.database.is_file() or not client_id or not client_secret:
            raise _unavailable()
        self.base_url = _base_url(base_url)
        self.client_id, self.client_secret = client_id, client_secret
        self.live_authorized = live_authorized is True
        self.runner, self.monotonic = runner or subprocess.run, monotonic

    def preview(self, card_id, offer, destination):
        return self.preview_before(card_id, offer, destination, deadline=self.monotonic() + WORKER_SECONDS)

    def preview_before(self, card_id, offer, destination, *, deadline):
        if not self.live_authorized or type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise _unavailable()
        if not _ACTIVE_WORKER.acquire(blocking=False):
            raise _unavailable()
        try:
            _research(offer, destination)
            payload = json.dumps({"schema": REQUEST_SCHEMA, "database": str(self.database), "card_id": card_id,
                                  "offer": offer, "destination": destination, "deadline": deadline}, allow_nan=False)
            if len(payload.encode()) > MAX_BYTES:
                raise _unavailable()
            # Provider credentials are server-only environment, never argv or
            # browser-controlled fields. Override inherited values explicitly.
            env = dict(os.environ)
            env.update(BNS_PARTNER_BASE_URL=self.base_url, BNS_PARTNER_CLIENT_ID=self.client_id,
                       BNS_PARTNER_CLIENT_SECRET=self.client_secret)
            remaining = min(WORKER_SECONDS, deadline - self.monotonic())
            if remaining <= 0:
                raise _unavailable()
            result = self.runner([sys.executable, "-c", "from pokemon_index.bounded_buyship import _worker; _worker()"],
                input=payload, env=env, capture_output=True, text=True, timeout=remaining, check=False)
            # subprocess.run kills AND reaps on TimeoutExpired. Never replace
            # this with a thread timeout that abandons a live provider call.
            if self.monotonic() >= deadline or result.returncode != 0:
                raise _unavailable()
            _, value = _response({"status": 200, "body": result.stdout}, MAX_BYTES)
            if set(value) != {"schema", "quote"} or value["schema"] != RESULT_SCHEMA:
                raise _unavailable()
            quote = _validate_quote(value["quote"], card_id, offer, destination)
            current = BoundBuyShipForwarder(self.database, None)._indexed_binding(card_id, offer, destination, deadline=deadline)
            if current != (quote["unit_id"], quote["evidence"]["listing_snapshot_sha256"], quote["evidence"]["observation_quality_sha256"]):
                raise _unavailable()
            if self.monotonic() >= deadline:
                raise _unavailable()
            return quote
        except Exception:
            # Never expose worker stdout/stderr, credentials or provider text.
            raise _unavailable() from None
        finally:
            _ACTIVE_WORKER.release()

"""Offline preflight and explicitly opt-in, one-case provider probes.

Default CLI execution never constructs a live client. Future execution selects
one provider, runs in a disposable worker with a 25-second wall deadline, and
never crawls, imports observations, changes source approval or stores a quote.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import time
from urllib.parse import urlsplit

from .commerce_loop import BoundBuyShipForwarder, _quote_block_reason
from .marketplace_crawl import _PinnedHTTPS, canonical_product_url
from .psa_cert import CERT_PATTERN, PSACertClient, _https_get, _response, compare_record

SCHEMA = "pokemon.provider-smoke.v1"
PLAN_SCHEMA = "pokemon.provider-smoke-plan.v1"
PSA_FIELDS = {"subject", "card_number", "year", "brand", "grade"}
AUTH_FLAGS = ("certificate_verified", "authenticity_verified", "physical_authenticity_verified")
BNS_PATHS = ("/v1/oauth/token", "/v1/products/resolve", "/v1/quotes")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result.astimezone(timezone.utc)


def _text(value, maximum=256):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and all(ord(char) >= 32 for char in value))


def _report(provider, *, authorized=False):
    return {"schema": SCHEMA, "provider": provider, "status": "blocked", "reason": None,
            "live_attempt_authorized": authorized is True, "checks": {},
            "transport": "not_started",
            "request_budget": 1 if provider == "psa" else 3, "lookup_calls": 0,
            "order_created": False, "purchasable": False, "purchase_action": None,
            "physical_authenticity_verified": False}


def _failure(report, reason, *, attempted=False):
    report.update(status="failed" if attempted else "blocked", reason=reason)
    return report


def _psa_inputs(certificate_number, expected):
    if not isinstance(certificate_number, str) or not CERT_PATTERN.fullmatch(certificate_number):
        return "known_certificate_required"
    if (not isinstance(expected, dict) or not PSA_FIELDS.issubset(expected)
            or set(expected) - PSA_FIELDS - {"variety"}
            or any(not _text(value) for value in expected.values())):
        return "full_expected_certificate_identity_required"
    return None


def psa_smoke(certificate_number, expected, *, client, authorized=False, now=utcnow):
    """One lookup, then local repeat/mismatch comparisons of the same record."""
    report = _report("psa", authorized=authorized)
    if authorized is not True:
        return _failure(report, "live_not_authorized")
    invalid = _psa_inputs(certificate_number, expected)
    if invalid:
        return _failure(report, invalid)
    report["certificate_ref"] = hashlib.sha256(certificate_number.encode()).hexdigest()
    report["transport"] = "psa_fixed_https" if getattr(client, "_transport", None) is _https_get else "injected_transport"
    try:
        report["lookup_calls"] = 1
        result = client.lookup(certificate_number, expected=expected)
        instant = _instant(now())
        if (not isinstance(result, dict) or result.get("schema") != "pokemon.psa-cert.v1"
                or result.get("provider") != "psa" or result.get("status") != "found"
                or result.get("record_found") is not True or result.get("cached") is not False
                or result.get("certificate_number") != certificate_number
                or any(result.get(field) is not False for field in AUTH_FLAGS)):
            return _failure(report, "fresh_matching_record_required", attempted=True)
        record = result.get("record")
        if not isinstance(record, dict) or record.get("certificate_number") != certificate_number:
            return _failure(report, "certificate_record_differs", attempted=True)
        checked, expires = _instant(result.get("checked_at")), _instant(result.get("expires_at"))
        if not instant - timedelta(seconds=300) <= checked <= instant < expires <= checked + timedelta(seconds=300):
            return _failure(report, "record_evidence_expired", attempted=True)
        comparison = compare_record(record, expected)
        if comparison["status"] != "matched" or result.get("comparison") != comparison:
            return _failure(report, "certificate_identity_mismatch", attempted=True)
        # No second lookup, random certificate or provider-negative request.
        repeat = compare_record(record, expected)
        different_grade = "9" if compare_record(record, {"grade": "10"})["status"] == "matched" else "10"
        mismatch = compare_record(record, {"grade": different_grade})
        if repeat != comparison or mismatch["status"] != "mismatch":
            return _failure(report, "local_comparison_check_failed", attempted=True)
        report.update(status="passed", reason=None, checks={
            "exact_certificate": True, "full_expected_identity": True, "evidence_current": True,
            "matched_fields": comparison["matched_fields"], "local_repeat": True,
            "local_grade_mismatch": True, "authentication_claims_false": True})
        return report
    except Exception:
        # Never print exception/provider text, credentials, certificate or record.
        return _failure(report, "certificate_probe_unavailable", attempted=True)


def _destination(value):
    if not isinstance(value, dict) or set(value) - {"country", "state"}:
        return False
    return (value.get("country") == "HK" and set(value) == {"country"}
            or value.get("country") == "US" and set(value) == {"country", "state"}
            and isinstance(value["state"], str) and bool(re.fullmatch(r"[A-Z]{2}", value["state"])))


def bns_preflight(database, card_id, offer, destination, *, now=utcnow):
    """Read an existing operator database; never establish its missing approvals."""
    report = _report("bns")
    if not _destination(destination):
        return _failure(report, "hk_or_us_state_destination_required")
    if not _text(card_id) or not isinstance(offer, dict):
        return _failure(report, "exact_researched_offer_required")
    try:
        reason = _quote_block_reason(offer)
        if reason:
            return _failure(report, reason)
        source, native_id, canonical = canonical_product_url(offer.get("url"))
        if source != offer.get("source") or native_id != offer.get("native_id") or canonical != offer["url"]:
            return _failure(report, "listing_url_identity_differs")
        grade = offer.get("grade")
        if (not isinstance(grade, dict) or grade.get("certificate_verified") is not False
                or offer.get("authenticity_verified") is not False):
            return _failure(report, "unverified_seller_claim_labels_required")
        instant, observed, fresh_until = _instant(now()), _instant(offer.get("observed_at")), _instant(offer.get("fresh_until"))
        if not instant - timedelta(seconds=300) <= observed <= instant < fresh_until <= observed + timedelta(seconds=300):
            return _failure(report, "fresh_researched_offer_required")
        if not database or not Path(database).is_file():
            return _failure(report, "existing_operator_database_required")
        binding = BoundBuyShipForwarder(database, None)._indexed_binding(card_id, offer, destination)
        report.update(status="ready", reason=None, checks={"read_only_index_binding": True,
            "confirmed_stock": True, "exact_listing": True, "research_current": True,
            "source_permission_current": True, "indexed_unit_ref": hashlib.sha256(binding[0].encode()).hexdigest(),
            "snapshot_sha256": binding[1], "observation_quality_sha256": binding[2]})
        return report
    except Exception:
        return _failure(report, "eligible_indexed_offer_required")


class ProbeError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _base_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ProbeError("approved_bns_endpoint_required")
    p = urlsplit(value)
    if (p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in {"", "/"}
            or p.port not in (None, 443) or p.hostname in {"localhost", "metadata.google.internal"}
            or any(p.hostname.endswith(suffix) for suffix in (".local", ".internal", ".invalid"))):
        raise ProbeError("approved_bns_endpoint_required")
    try:
        address = ipaddress.ip_address(p.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ProbeError("approved_bns_endpoint_required")
    return value.rstrip("/")


def _bns_https(request, *, timeout, max_bytes):
    """Pinned public DNS, verified TLS, direct POST; redirects are never followed."""
    p = urlsplit(request.full_url)
    connection = _PinnedHTTPS(p.hostname, port=p.port or 443, timeout=timeout, context=ssl.create_default_context())
    try:
        connection.request("POST", p.path, body=request.data, headers=dict(request.header_items()))
        response = connection.getresponse()
        if response.status != 200:
            return {"status": response.status, "body": b""}
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() not in {"application/json", "text/json"}:
            raise ProbeError("bns_response_invalid")
        return {"status": response.status, "body": response.read(max_bytes + 1)}
    finally:
        connection.close()


class OneShotBNSSender:
    """One OAuth, one resolve, one quantity-one quote; no auth retry or redirects.

    The CLI additionally kills its worker at 25 seconds, covering DNS, slow
    headers/body and database waits that per-socket timeouts alone cannot bound.
    """
    def __init__(self, base_url, *, authorized=False, transport=None, monotonic=time.monotonic):
        self.base_url = _base_url(base_url)
        self.authorized = authorized is True
        self.transport, self.monotonic = transport or _bns_https, monotonic
        self.started = monotonic()
        self.requests = []

    def __call__(self, request):
        if not self.authorized:
            raise ProbeError("live_not_authorized")
        elapsed = self.monotonic() - self.started
        if elapsed < 0 or elapsed >= 18:
            raise ProbeError("bns_request_deadline")
        index = len(self.requests)
        if (index >= len(BNS_PATHS) or request.full_url != self.base_url + BNS_PATHS[index]
                or request.get_method() != "POST" or not isinstance(request.data, bytes)
                or len(request.data) > 16384):
            raise ProbeError("bns_request_budget_or_route")
        if index == 2:
            _, payload = _response({"status": 200, "body": request.data}, 16384)
            if (not isinstance(payload.get("items"), list) or len(payload["items"]) != 1
                    or type(payload["items"][0].get("quantity")) is not int
                    or payload["items"][0]["quantity"] != 1 or not _destination(payload.get("destination"))):
                raise ProbeError("single_quote_only")
        self.requests.append(BNS_PATHS[index])
        reply = self.transport(request, timeout=min(5, 18 - elapsed), max_bytes=65536)
        status = reply.get("status") if isinstance(reply, dict) else None
        if status != 200:
            raise ProbeError("bns_access_rejected" if status in {401, 403} else
                             "bns_rate_limited" if status == 429 else "bns_http_rejected")
        try:
            _, payload = _response(reply, 65536)
            if index == 0:
                token = payload.get("access_token")
                if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
                    raise ValueError("invalid token")
        except Exception:
            raise ProbeError("bns_response_invalid") from None
        if self.monotonic() - self.started >= 18:
            raise ProbeError("bns_request_deadline")
        return 200, payload


def bns_smoke(database, card_id, offer, destination, *, client, authorized=False, now=utcnow):
    report = _report("bns", authorized=authorized)
    if authorized is not True:
        return _failure(report, "live_not_authorized")
    preflight = bns_preflight(database, card_id, offer, destination, now=now)
    if preflight["status"] != "ready":
        return preflight
    from .buyship_partner import PartnerClient, _require_preview_binding
    if not isinstance(client, PartnerClient) or not isinstance(client.sender, OneShotBNSSender) or not client.sender.authorized:
        return _failure(report, "one_shot_transport_required")
    report["transport"] = "bounded_https" if client.sender.transport is _bns_https else "injected_transport"
    try:
        before = preflight["checks"]
        quote = BoundBuyShipForwarder(database, client).preview(card_id, offer, destination)
        _require_preview_binding(quote)
        final = bns_preflight(database, card_id, offer, destination, now=now)
        if final["status"] != "ready" or final["checks"] != before:
            return _failure(report, "indexed_evidence_changed", attempted=True)
        b = quote["buyship"]
        if not _instant(b["quoted_at"]) <= _instant(now()) < _instant(b["expires_at"]):
            return _failure(report, "provider_quote_expired", attempted=True)
        if (quote.get("purchasable") is not False or quote.get("order_created") is not False
                or quote.get("purchase_action") is not None or len(client.sender.requests) != 3):
            return _failure(report, "quote_only_contract_required", attempted=True)
        report.update(status="passed", reason=None, requests=list(client.sender.requests),
            checks={**before, "provider_binding": True, "quote_current": True, "no_order": True},
            quote={"expires_at": b["expires_at"], "currency": b["currency"],
                   "components": b["components"], "grand_total": b["grand_total"],
                   "source_ask": quote["listing"]["ask"], "resolve_price": b["resolve_price"],
                   "resolve_price_differs_from_observation": b["resolve_price_differs_from_observation"],
                   "quote_ref": hashlib.sha256(b["quote_id"].encode()).hexdigest()})
        return report
    except ProbeError as exc:
        return _failure(report, exc.code, attempted=True)
    except Exception:
        return _failure(report, "eligible_bound_quote_unavailable", attempted=True)
    finally:
        report["requests"] = list(client.sender.requests)


def readiness(plan, *, env=None, now=utcnow):
    """Only local JSON, environment-presence checks and optional read-only SQL."""
    env = os.environ if env is None else env
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA or set(plan) - {"schema", "psa", "bns"}:
        raise ValueError("invalid smoke plan")
    psa, bns = plan.get("psa") or {}, plan.get("bns") or {}
    if not isinstance(psa, dict) or not isinstance(bns, dict):
        raise ValueError("invalid smoke plan")
    if (set(psa) - {"certificate_number", "expected"}
            or set(bns) - {"card_id", "offer", "destination", "approved_base_url", "contract_confirmation_reference"}):
        raise ValueError("unsupported smoke plan fields")
    psa_blockers = []
    invalid = _psa_inputs(psa.get("certificate_number"), psa.get("expected"))
    if invalid:
        psa_blockers.append(invalid)
    identity_missing = _psa_inputs("00000000", psa.get("expected"))
    if identity_missing and identity_missing not in psa_blockers:
        psa_blockers.append(identity_missing)
    if not env.get("PSA_API_TOKEN"):
        psa_blockers.append("PSA_API_TOKEN_missing")
    bns_result = bns_preflight(env.get("POKEMON_COMMERCE_QUOTE_DB"), bns.get("card_id"), bns.get("offer"), bns.get("destination"), now=now)
    bns_blockers = [] if bns_result["status"] == "ready" else [bns_result["reason"]]
    for name in ("BNS_PARTNER_BASE_URL", "BNS_PARTNER_CLIENT_ID", "BNS_PARTNER_CLIENT_SECRET", "POKEMON_COMMERCE_QUOTE_DB"):
        if not env.get(name):
            bns_blockers.append(name + "_missing")
    try:
        approved = _base_url(bns.get("approved_base_url"))
        if approved != _base_url(env.get("BNS_PARTNER_BASE_URL")):
            bns_blockers.append("approved_bns_endpoint_differs")
    except (ValueError, TypeError):
        bns_blockers.append("approved_bns_endpoint_required")
    if not _text(bns.get("contract_confirmation_reference"), 1000):
        bns_blockers.append("confirmed_test_contract_and_url_support_required")
    return {"schema": SCHEMA, "mode": "offline_preflight", "network_requests": 0,
            "psa": {"ready": not psa_blockers, "blockers": psa_blockers, "request_budget": 1},
            "bns": {"ready": not bns_blockers, "blockers": bns_blockers,
                    "request_budget": {"oauth": 1, "resolve": 1, "quote": 1}, "checks": bns_result["checks"]},
            "order_created": False, "payments": False, "production_deployment": False}


def _execute(plan, provider):
    preflight = readiness(plan)
    if not preflight[provider]["ready"]:
        return _failure(_report(provider), "preflight_blocked")
    if provider == "psa":
        case = plan["psa"]
        client = PSACertClient(token=os.environ["PSA_API_TOKEN"], allow_live=True,
                               max_requests=1, request_window_seconds=3600)
        return psa_smoke(case["certificate_number"], case["expected"], client=client, authorized=True)
    from .buyship_partner import PartnerClient
    case = plan["bns"]
    sender = OneShotBNSSender(os.environ["BNS_PARTNER_BASE_URL"], authorized=True)
    client = PartnerClient(sender.base_url, os.environ["BNS_PARTNER_CLIENT_ID"],
                           os.environ["BNS_PARTNER_CLIENT_SECRET"], sender=sender, live_authorized=True)
    return bns_smoke(os.environ["POKEMON_COMMERCE_QUOTE_DB"], case["card_id"], case["offer"],
                     case["destination"], client=client, authorized=True)


def _worker():
    try:
        value = json.loads(sys.stdin.read(65537))
        result = _execute(value["plan"], value["provider"])
    except Exception:
        result = {"schema": SCHEMA, "status": "failed", "reason": "provider_probe_unavailable"}
    print(json.dumps(result, allow_nan=False))


def execute_bounded(plan, provider, *, runner=subprocess.run):
    """Future opt-in execution; the worker cannot outlive the wall-time budget."""
    if provider not in {"psa", "bns"}:
        raise ValueError("one provider required")
    try:
        result = runner([sys.executable, "-c", "from pokemon_index.provider_smoke import _worker; _worker()"],
            input=json.dumps({"plan": plan, "provider": provider}), capture_output=True, text=True,
            timeout=25, check=False)
        if result.returncode != 0 or len(result.stdout) > 32768:
            raise ValueError("worker failed")
        value = json.loads(result.stdout)
        allowed = {"schema", "provider", "status", "reason", "live_attempt_authorized", "transport", "checks", "request_budget",
                   "lookup_calls", "order_created", "purchasable", "purchase_action", "physical_authenticity_verified",
                   "certificate_ref", "requests", "quote"}
        if (not isinstance(value, dict) or value.get("schema") != SCHEMA or value.get("provider") != provider
                or value.get("status") not in {"passed", "blocked", "failed"} or set(value) - allowed
                or value.get("order_created") is not False or value.get("purchasable") is not False
                or value.get("purchase_action") is not None or value.get("physical_authenticity_verified") is not False):
            raise ValueError("invalid worker result")
        return value
    except subprocess.TimeoutExpired:
        return _failure(_report(provider, authorized=True), "worker_wall_timeout", attempted=True)
    except Exception:
        return _failure(_report(provider, authorized=True), "provider_worker_unavailable", attempted=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="operator case JSON; never contains credentials")
    parser.add_argument("--execute", choices=("psa", "bns"), help="FUTURE authorized one-provider probe; otherwise strictly offline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with ExitStack() as stack:
        # Reserve the receipt before any optional provider request. Reusing a
        # result path must fail before another live attempt, never afterward.
        handle = stack.enter_context(args.output.open("x", encoding="utf-8")) if args.output else None
        try:
            raw = args.plan.read_bytes()
            if len(raw) > 32768:
                raise ValueError("plan exceeds limit")
            _, plan = _response({"status": 200, "body": raw}, 32768)
            report = readiness(plan)
            if args.execute:
                report = execute_bounded(plan, args.execute) if report[args.execute]["ready"] else _failure(_report(args.execute), "preflight_blocked")
        except Exception:
            report = {"schema": SCHEMA, "status": "blocked", "reason": "invalid_local_plan", "network_requests": 0}
        text = json.dumps(report, indent=2, allow_nan=False) + "\n"
        if handle:
            handle.write(text)
        else:
            print(text, end="")
        if report.get("status") in {"failed", "blocked"}:
            raise SystemExit(2)


if __name__ == "__main__":
    main()

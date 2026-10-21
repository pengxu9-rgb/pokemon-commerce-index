"""Strict BNS quote-only transport shared by chat and operator probes.

Only OAuth, product resolve and one quantity-one quote are permitted. No
redirect/retry/order operation is implemented. Callers enforce a process wall
limit as socket timeouts alone cannot bound DNS and slow response streams.
"""
from __future__ import annotations

import ipaddress
import math
import ssl
import time
from urllib.parse import urlsplit

from .bns_errors import BNSRefusal, refusal, sanitize_provider_error
from .marketplace_crawl import _PinnedHTTPS
from .psa_cert import _response

BNS_PATHS = ("/v1/oauth/token", "/v1/products/resolve", "/v1/quotes")


def _destination(value):
    import re
    if not isinstance(value, dict) or set(value) - {"country", "state"}:
        return False
    return (value.get("country") == "HK" and set(value) == {"country"}
            or value.get("country") == "US" and set(value) == {"country", "state"}
            and isinstance(value["state"], str) and bool(re.fullmatch(r"[A-Z]{2}", value["state"])))


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
        if response.status != 200 and response.status not in {400, 401, 403, 404, 409, 422, 424, 429, 500, 502, 503, 504}:
            # Never consume redirect bodies or follow their locations.
            return {"status": response.status, "body": b""}
        if response.getheader("Content-Type", "").split(";")[0].strip().lower() not in {"application/json", "text/json"}:
            if response.status != 200:
                return {"status": response.status, "body": b""}
            raise ProbeError("bns_response_invalid")
        return {"status": response.status, "body": response.read(max_bytes + 1)}
    finally:
        connection.close()


class OneShotBNSSender:
    """One OAuth, one resolve, one quantity-one quote; no auth retry or redirects.

    Callers additionally kill their workers on a wall deadline, covering DNS,
    slow headers/body and DB waits that per-socket timeouts cannot bound.
    """
    def __init__(self, base_url, *, authorized=False, transport=None, monotonic=time.monotonic,
                 deadline=None, before_request=None):
        self.base_url = _base_url(base_url)
        self.authorized = authorized is True
        self.transport, self.monotonic = transport or _bns_https, monotonic
        self.started = monotonic()
        if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
            raise ProbeError("bns_request_deadline")
        self.deadline = min(self.started + 18, deadline) if deadline is not None else self.started + 18
        self.requests = []
        self.before_request = before_request

    def __call__(self, request):
        if not self.authorized:
            raise ProbeError("live_not_authorized")
        instant = self.monotonic()
        elapsed, remaining = instant - self.started, self.deadline - instant
        if elapsed < 0 or remaining <= 0:
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
        if self.before_request is not None:
            self.before_request()
        # Local permission/DB checks can wait too. Re-evaluate the deadline
        # after the guard so it cannot permit a late provider dispatch.
        remaining = self.deadline - self.monotonic()
        if remaining <= 0:
            raise ProbeError("bns_request_deadline")
        self.requests.append(BNS_PATHS[index])
        reply = self.transport(request, timeout=min(5, remaining), max_bytes=65536)
        status = reply.get("status") if isinstance(reply, dict) else None
        if status != 200:
            if self.monotonic() >= self.deadline:
                raise ProbeError("bns_request_deadline")
            fallback = ("bns_access_rejected" if status in {401, 403} else
                        "bns_rate_limited" if status == 429 else "bns_http_rejected")
            body = reply.get("body") if isinstance(reply, dict) else None
            if body in (None, b"", ""):
                raise BNSRefusal(refusal(fallback))
            try:
                # Reuse the existing byte/depth/duplicate-key/finite-number
                # parser while preserving the original HTTP status separately.
                _, payload = _response({"status": 200, "body": body}, 65536)
            except Exception:
                raise BNSRefusal(refusal("bns_response_invalid")) from None
            raise BNSRefusal(sanitize_provider_error(status, payload, stage=("oauth", "resolve", "quote")[index]))
        try:
            _, payload = _response(reply, 65536)
            if index == 0:
                token = payload.get("access_token")
                if not isinstance(token, str) or not 1 <= len(token) <= 8192 or any(not 33 <= ord(c) <= 126 for c in token):
                    raise ValueError("invalid token")
        except Exception:
            raise ProbeError("bns_response_invalid") from None
        if self.monotonic() >= self.deadline:
            raise ProbeError("bns_request_deadline")
        return 200, payload

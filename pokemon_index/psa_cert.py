"""Bounded, opt-in PSA certificate-record lookup; never physical authentication.

Only the documented single-certificate GET route is reachable. Tokens stay in
the server transport and are never copied into a result, exception, or log.
Seller descriptions may be compared with a returned record, but cannot create
provider evidence. No order, submission, payment or marketplace request exists.
"""
from __future__ import annotations

from collections import OrderedDict, deque
import copy
from datetime import datetime, timedelta, timezone
import json
import re
import ssl
import threading
import unicodedata
from urllib import error, request


SCHEMA = "pokemon.psa-cert.v1"
BASE_URL = "https://api.psacard.com/publicapi/cert/GetByCertNumber/"
CERT_PATTERN = re.compile(r"[0-9]{7,12}\Z")
EXPECTED_FIELDS = ("subject", "card_number", "year", "brand", "variety", "grade")
_RECORD_FIELDS = {"subject": "Subject", "card_number": "CardNumber", "year": "Year",
                  "brand": "Brand", "variety": "Variety", "grade": "CardGrade",
                  "grade_description": "GradeDescription", "item_status": "ItemStatus"}
_DISCLAIMER = "A PSA database record does not authenticate the physical card or slab."
_MESSAGES = {
    "invalid_certificate_number": "Enter a PSA certificate number using 7 to 12 ASCII digits.",
    "invalid_expectation": "Certificate comparison fields are invalid.",
    "live_disabled": "PSA certificate lookup is disabled on this server.",
    "access_unconfigured": "PSA API access is not configured on this server.",
    "lookup_busy": "Another PSA lookup is running. Retry shortly.",
    "lookup_rate_limited": "The server's bounded PSA lookup allowance has been reached. Retry later.",
    "provider_unauthorized": "PSA API access was rejected. An operator must check the server token.",
    "provider_rate_limited": "PSA temporarily limited certificate lookups. Retry later.",
    "provider_timeout": "The PSA certificate lookup timed out.",
    "provider_unavailable": "PSA certificate lookup is temporarily unavailable.",
    "provider_response_invalid": "PSA returned an unsupported certificate response.",
    "provider_invalid_certificate": "PSA rejected the certificate number.",
    "provider_not_found": "PSA returned no record for this certificate number.",
    "certificate_number_mismatch": "The PSA response certificate number differs from the requested number.",
    "record_fields_mismatch": "The PSA record differs from the compared card or seller claims.",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid PSA lookup clock")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("PSA lookup clock requires a timezone")
    return instant.astimezone(timezone.utc)


def _text(value, maximum=256):
    if value is None or value == "":
        return None
    if (not isinstance(value, str) or len(value) > maximum
            or any(unicodedata.category(char).startswith("C") for char in value)):
        raise ValueError("invalid PSA record text")
    return value.strip() or None


def _normalized(value, field):
    value = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    # No fuzzy title, translation, substring, or card-number fraction matching:
    # a partial identity must never become a claimed full record match.
    if field == "grade":
        # PSA may return its label text instead of only the numeric grade.
        # Recognize complete unqualified 9/10 labels; never strip a qualifier
        # or extract an arbitrary number from the surrounding description.
        value = {"gem mt 10": "10", "gem-mt 10": "10", "gem mint 10": "10",
                 "mint 9": "9"}.get(value, value)
        if re.fullmatch(r"(?:10|[1-9])(?:\.0)?", value):
            value = value.removesuffix(".0")
    return value


def _expected(value):
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(EXPECTED_FIELDS):
        raise ValueError("invalid PSA comparison fields")
    result = {}
    for field, item in value.items():
        result[field] = _text(item)
        if result[field] is None:
            raise ValueError("empty PSA comparison field")
    return result


def compare_record(record, expected=None):
    """Compare explicit fields, without proving listing identity or authenticity.

    The caller must derive expected fields from its server-owned offer/catalog
    state. A verbose marketplace title is not the PSA ``Subject`` field.
    """
    expected = _expected(expected)
    compared = {"status": "not_compared", "matched_fields": [],
                "mismatched_fields": [], "missing_fields": []}
    if not expected:
        return compared
    for field in EXPECTED_FIELDS:
        if field not in expected:
            continue
        actual = record.get(field)
        if not actual:
            compared["missing_fields"].append(field)
        elif _normalized(actual, field) == _normalized(expected[field], field):
            compared["matched_fields"].append(field)
        else:
            compared["mismatched_fields"].append(field)
    compared["status"] = ("mismatch" if compared["mismatched_fields"] else
                           "inconclusive" if compared["missing_fields"] else "matched")
    return compared


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def _https_get(url, *, headers, timeout, max_bytes):
    # The URL is constructed internally from fixed HTTPS host/path and ASCII
    # digits. No endpoint override or redirect can forward bearer credentials.
    opener = request.build_opener(_NoRedirect(), request.HTTPSHandler(context=ssl.create_default_context()))
    req = request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(req, timeout=timeout) as response:
            if response.geturl() != url:
                raise ValueError("redirected PSA response")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isascii() or not length.isdecimal()
                                        or int(length) > max_bytes):
                raise ValueError("PSA response exceeds bound")
            content_type = response.headers.get_content_type()
            if content_type not in {"application/json", "text/json"}:
                raise ValueError("PSA response is not JSON")
            return {"status": response.status, "body": response.read(max_bytes + 1)}
    except error.HTTPError as exc:
        # Never propagate or consume an arbitrary error body: it could contain
        # reflected credentials or an HTML challenge.
        status = exc.code
        exc.close()
        return {"status": status, "body": b""}


def _response(response, maximum):
    if not isinstance(response, dict) or type(response.get("status")) is not int:
        raise ValueError("invalid PSA transport response")
    status, body = response["status"], response.get("body")
    if status != 200:
        return status, None
    if isinstance(body, dict):
        body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    if not isinstance(body, bytes) or len(body) > maximum:
        raise ValueError("PSA response exceeds bound")
    text = body.decode("utf-8")
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 8:
                raise ValueError("PSA response nesting exceeds bound")
        elif char in "]}":
            depth -= 1

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate PSA response field")
            result[key] = value
        return result

    def finite(_value):
        raise ValueError("nonfinite PSA response number")

    value = json.loads(text, object_pairs_hook=unique, parse_constant=finite)
    if not isinstance(value, dict):
        raise ValueError("PSA response must be an object")
    return status, value


class PSACertClient:
    """One read-only provider route, bounded cache, serialized calls, no retries.

    ``transport`` is injectable for offline tests. It still requires the explicit
    ``allow_live`` flag and a nonempty token, preventing silent fixture fallback.
    The rolling request allowance applies to cache misses, including failures.
    """
    def __init__(self, *, token=None, allow_live=False, transport=None, now=utcnow,
                 timeout=8, max_bytes=65_536, cache_seconds=300, max_cache_entries=256,
                 max_requests=10, request_window_seconds=60):
        if (token is not None and (not isinstance(token, str) or not 1 <= len(token) <= 8192
                or any(ord(char) < 33 or ord(char) > 126 for char in token))):
            raise ValueError("invalid PSA API token configuration")
        if (type(allow_live) is not bool or not 1 <= timeout <= 15
                or type(max_bytes) is not int or not 1024 <= max_bytes <= 262_144
                or type(cache_seconds) is not int or not 1 <= cache_seconds <= 3600
                or type(max_cache_entries) is not int or not 1 <= max_cache_entries <= 1024
                or type(max_requests) is not int or not 1 <= max_requests <= 60
                or type(request_window_seconds) is not int or not 1 <= request_window_seconds <= 3600):
            raise ValueError("invalid PSA lookup bounds")
        self._token, self.allow_live = token, allow_live
        self._transport, self.now = transport or _https_get, now
        self.timeout, self.max_bytes = timeout, max_bytes
        self.cache_seconds, self.max_cache_entries = cache_seconds, max_cache_entries
        self.max_requests, self.request_window_seconds = max_requests, request_window_seconds
        self._cache, self._requests = OrderedDict(), deque()
        self._lock = threading.Lock()

    def configured(self):
        return self.allow_live and self._token is not None

    def _base(self, cert, instant):
        return {"schema": SCHEMA, "provider": "psa", "status": "unavailable",
                "certificate_number": cert, "checked_at": instant.isoformat(), "expires_at": None,
                "cached": False, "record_found": False, "record": None,
                "comparison": {"status": "not_compared", "matched_fields": [],
                               "mismatched_fields": [], "missing_fields": []},
                "certificate_verified": False, "authenticity_verified": False,
                "physical_authenticity_verified": False, "reason": None, "message": _DISCLAIMER}

    def _failure(self, base, reason, status="unavailable"):
        return base | {"status": status, "reason": reason,
                       "message": _MESSAGES[reason] + " " + _DISCLAIMER}

    def _record(self, payload, cert):
        valid, message = payload.get("IsValidRequest"), payload.get("ServerMessage")
        if valid is not None and type(valid) is not bool:
            raise ValueError("invalid PSA envelope")
        if message is not None and (not isinstance(message, str) or len(message) > 256):
            raise ValueError("invalid PSA envelope")
        normalized_message = (message or "").strip().casefold().rstrip(".")
        # Negative envelopes cannot be combined with a positive record.
        if valid is False:
            if payload.get("PSACert"):
                raise ValueError("conflicting PSA envelope")
            return "invalid", "provider_invalid_certificate", None
        if normalized_message == "no data found":
            if valid is not True or payload.get("PSACert"):
                raise ValueError("conflicting PSA envelope")
            return "not_found", "provider_not_found", None
        if message is not None and (valid is not True or normalized_message != "request successful"):
            raise ValueError("unsupported PSA envelope")
        raw = payload.get("PSACert")
        if not isinstance(raw, dict):
            raise ValueError("missing PSA card record")
        if not isinstance(raw.get("CertNumber"), str) or raw["CertNumber"] != cert:
            return "unavailable", "certificate_number_mismatch", None
        record = {"certificate_number": cert}
        record.update({field: _text(raw.get(provider_field)) for field, provider_field in _RECORD_FIELDS.items()})
        if not record["subject"] or not record["grade"]:
            raise ValueError("incomplete PSA card record")
        if any(self._token in value for value in record.values() if value):
            raise ValueError("PSA response reflected server credentials")
        return "found", None, record

    def _lookup(self, cert, instant):
        base = self._base(cert, instant)
        cutoff = instant - timedelta(seconds=self.request_window_seconds)
        while self._requests and self._requests[0] <= cutoff:
            self._requests.popleft()
        # Reject a clock rollback rather than retaining future cache evidence.
        if self._requests and self._requests[-1] > instant:
            self._cache.clear()
            return self._failure(base, "provider_unavailable")
        if len(self._requests) >= self.max_requests:
            return self._failure(base, "lookup_rate_limited")
        self._requests.append(instant)
        try:
            status, payload = _response(self._transport(BASE_URL + cert,
                headers={"Authorization": "Bearer " + self._token, "Accept": "application/json",
                         "User-Agent": "pokemon-commerce-index/psa-cert-record-v1"},
                timeout=self.timeout, max_bytes=self.max_bytes), self.max_bytes)
            if status in {401, 403}:
                return self._failure(base, "provider_unauthorized")
            if status == 429:
                return self._failure(base, "provider_rate_limited")
            if status != 200:
                return self._failure(base, "provider_unavailable")
            outcome, reason, record = self._record(payload, cert)
            if record is None:
                return self._failure(base, reason, outcome)
            return base | {"status": "found", "record_found": True, "record": record,
                           "expires_at": (instant + timedelta(seconds=self.cache_seconds)).isoformat(),
                           "message": "PSA returned this certificate record. " + _DISCLAIMER}
        except (TimeoutError, error.URLError) as exc:
            reason = "provider_timeout" if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError) else "provider_unavailable"
            return self._failure(base, reason)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return self._failure(base, "provider_response_invalid")
        except Exception:
            # Transport exceptions are not safe browser output; token-bearing
            # request objects and reflected server text must never escape.
            return self._failure(base, "provider_unavailable")

    def lookup(self, certificate_number, *, expected=None):
        instant = _instant(self.now())
        valid = isinstance(certificate_number, str) and CERT_PATTERN.fullmatch(certificate_number)
        base = self._base(certificate_number if valid else None, instant)
        if not valid:
            return self._failure(base, "invalid_certificate_number", "invalid")
        try:
            expected = _expected(expected)
        except (ValueError, TypeError):
            return self._failure(base, "invalid_expectation", "invalid")
        if not self.allow_live:
            return self._failure(base, "live_disabled")
        if not self._token:
            return self._failure(base, "access_unconfigured")
        if not self._lock.acquire(timeout=0.05):
            return self._failure(base, "lookup_busy")
        try:
            cached = self._cache.get(certificate_number)
            if cached and _instant(cached["checked_at"]) <= instant < _instant(cached["expires_at"]):
                result = copy.deepcopy(cached) | {"cached": True}
                self._cache.move_to_end(certificate_number)
            else:
                self._cache.pop(certificate_number, None)
                result = self._lookup(certificate_number, instant)
                if result["record_found"]:
                    self._cache[certificate_number] = copy.deepcopy(result)
                    while len(self._cache) > self.max_cache_entries:
                        self._cache.popitem(last=False)
            if result["record_found"]:
                if not _instant(result["checked_at"]) <= _instant(self.now()) < _instant(result["expires_at"]):
                    self._cache.pop(certificate_number, None)
                    return self._failure(self._base(certificate_number, _instant(self.now())), "provider_unavailable")
                result["comparison"] = compare_record(result["record"], expected)
                if result["comparison"]["status"] == "mismatch":
                    result = self._failure(result, "record_fields_mismatch", "mismatch")
            return result
        finally:
            self._lock.release()

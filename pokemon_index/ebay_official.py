"""Explicitly gated, bounded eBay Browse reads and separately validated EPN links.

No request runs on import or configuration. This module does not grant eBay
content/display rights. Current asks are neither paid sales nor landed quotes.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timedelta, timezone
import http.client
import json
import re
import threading
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

from .ebay_browse import MARKETPLACE, SCOPE
from .dispatch_budget import DispatchBudget, DispatchDenied
from .marketplace_sources import _ebay_item

HOST = "api.ebay.com"
DISCLOSURE = "We may earn a commission from this link."
MAX_BYTES = 2_000_000
CAMPAIGN = re.compile(r"[0-9]{10}")
OPAQUE_REFERENCE = re.compile(r"[A-Za-z0-9_-]{1,64}")
LEGACY_ID = re.compile(r"[0-9]{8,20}")
REST_ID = re.compile(r"v1\|([0-9]{8,20})\|0")
AFFILIATE_QUERY = {"mkevt", "mkcid", "mkrid", "campid", "toolid", "customid",
                   "_trkparms", "_trksid", "hash"}


class OfficialEbayError(ValueError):
    """Safe fixed-code error; never contains provider bodies or credentials."""


def _stamp(value):
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
            raise ValueError()
        return stamp
    except (AttributeError, TypeError, ValueError):
        raise OfficialEbayError("ebay_official_invalid_clock") from None


def _legacy(value):
    if not isinstance(value, str):
        raise OfficialEbayError("ebay_official_invalid_item")
    match = REST_ID.fullmatch(value)
    if match:
        return match.group(1)
    if LEGACY_ID.fullmatch(value):
        return value
    raise OfficialEbayError("ebay_official_invalid_item")


def _item_url(value, *, canonical=False):
    if (not isinstance(value, str) or len(value) > 4096 or "#" in value
            or re.search(r"[\s\\\x00-\x1f\x7f]", value)):
        raise OfficialEbayError("ebay_official_invalid_url")
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc not in {"ebay.com", "www.ebay.com"}
                or parsed.fragment or "%" in parsed.path):
            raise ValueError()
        match = re.fullmatch(r"/itm/(?:[A-Za-z0-9_-]+/)?([0-9]{8,20})", parsed.path)
        if not match:
            raise ValueError()
        legacy = match.group(1)
        if canonical and value != f"https://www.ebay.com/itm/{legacy}":
            raise ValueError()
        return parsed, legacy
    except ValueError:
        raise OfficialEbayError("ebay_official_invalid_url") from None


def validate_purchase_link(value, *, source, native_id, canonical_url, campaign_id=None):
    """Validate a same-listing official EPN link without fetching or redirecting it."""
    if (source not in {"ebay", "ebay_us"} or not isinstance(native_id, str)
            or not REST_ID.fullmatch(native_id) or not isinstance(value, dict)
            or set(value) != {"kind", "url", "disclosure"}
            or value.get("kind") != "epn_affiliate" or value.get("disclosure") != DISCLOSURE):
        raise OfficialEbayError("ebay_official_invalid_affiliate_link")
    _, canonical_id = _item_url(canonical_url, canonical=True)
    parsed, link_id = _item_url(value.get("url"))
    if canonical_id != _legacy(native_id) or link_id != canonical_id:
        raise OfficialEbayError("ebay_official_affiliate_item_mismatch")
    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=12)
    except ValueError:
        raise OfficialEbayError("ebay_official_invalid_affiliate_link") from None
    params = dict(pairs)
    if (len(params) != len(pairs) or set(params) - AFFILIATE_QUERY
            or not CAMPAIGN.fullmatch(params.get("campid", ""))
            or params.get("mkevt") != "1" or params.get("mkcid") != "1"
            or not re.fullmatch(r"[0-9]{1,5}", params.get("toolid", ""))
            or any(not text or len(text) > 1024 or re.search(r"[\x00-\x1f\x7f]", text)
                   for text in params.values())
            or ("customid" in params and not OPAQUE_REFERENCE.fullmatch(params["customid"]))
            or (campaign_id is not None and params["campid"] != campaign_id)):
        raise OfficialEbayError("ebay_official_invalid_affiliate_link")
    return {"kind": "epn_affiliate", "url": value["url"], "disclosure": DISCLOSURE}


def _unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError()
        value[key] = item
    return value


def _https_json(method, path, *, headers, body, timeout, before_dispatch):
    """Fixed host, no redirects/retries, finite response read, no error-body echo."""
    connection = http.client.HTTPSConnection(HOST, timeout=timeout)
    try:
        # Establish DNS/TCP/TLS first: connection setup must not postpone the
        # first credentialed HTTP byte until after the approved read window.
        connection.connect()
        remaining = before_dispatch()
        connection.sock.settimeout(min(timeout, remaining))
        connection.request(method, path, headers=headers, body=body)
        response = connection.getresponse()
        if response.status != 200:
            raise OfficialEbayError("ebay_official_http_error")
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise OfficialEbayError("ebay_official_response_too_large")
        value = json.loads(raw, object_pairs_hook=_unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except OfficialEbayError:
        raise
    except Exception:
        raise OfficialEbayError("ebay_official_transport_failed") from None
    finally:
        connection.close()


class BrowseClient:
    """Production read-only client; all access gates and a window are explicit."""

    def __init__(self, client_id, client_secret, *, allow_network=False,
                 production_approved=False, display_approved=False, read_until=None,
                 request_budget=None, affiliate_campaign_id=None, affiliate_approved=False,
                 affiliate_reference_id=None, transport=None, now=None, dispatch_budget=None):
        if dispatch_budget is not None and not isinstance(dispatch_budget, DispatchBudget): raise OfficialEbayError("invalid_dispatch_budget")
        self.dispatch_budget = dispatch_budget
        self.source_authorized = None
        self.enabled = allow_network is True
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._transport = transport or _https_json
        self._lock = threading.RLock()
        self._remaining = 0
        self._token = None
        self._token_until = None
        self._id, self._secret = client_id, client_secret
        self._campaign, self._reference = None, None
        self._started = _stamp(self._now())
        self._deadline = self._started
        self._monotonic_until = time.monotonic()
        if not self.enabled:
            return
        if production_approved is not True or display_approved is not True:
            raise OfficialEbayError("ebay_official_approval_required")
        if any(not isinstance(v, str) or not 1 <= len(v) <= 4096
               or re.search(r"[\s\x00-\x1f\x7f]", v) for v in (client_id, client_secret)):
            raise OfficialEbayError("ebay_official_credentials_required")
        self._deadline = _stamp(read_until)
        seconds = (self._deadline - self._started).total_seconds()
        if not 0 < seconds <= 90 * 60:
            raise OfficialEbayError("ebay_official_invalid_window")
        if type(request_budget) is not int or not 1 <= request_budget <= 20:
            raise OfficialEbayError("ebay_official_invalid_budget")
        self._remaining = request_budget
        self._monotonic_until = time.monotonic() + seconds
        if affiliate_campaign_id is not None or affiliate_reference_id is not None or affiliate_approved:
            if (affiliate_approved is not True or not isinstance(affiliate_campaign_id, str)
                    or not CAMPAIGN.fullmatch(affiliate_campaign_id)
                    or (affiliate_reference_id is not None and (
                        not isinstance(affiliate_reference_id, str)
                        or not OPAQUE_REFERENCE.fullmatch(affiliate_reference_id)))):
                raise OfficialEbayError("ebay_official_epn_configuration_required")
            self._campaign, self._reference = affiliate_campaign_id, affiliate_reference_id

    def _check(self):
        if not self.enabled:
            raise OfficialEbayError("ebay_official_disabled")
        instant = _stamp(self._now())
        if instant < self._started or instant >= self._deadline or time.monotonic() >= self._monotonic_until:
            raise OfficialEbayError("ebay_official_window_expired")
        return instant

    def _request(self, method, path, *, headers, body=None):
        with self._lock:
            instant = self._check()
            if self._remaining <= 0:
                raise OfficialEbayError("ebay_official_budget_exhausted")
            self._remaining -= 1
            timeout = min(15, (self._deadline - instant).total_seconds(),
                          self._monotonic_until - time.monotonic())
        try:
            self._check()
            if self.dispatch_budget:
                self.dispatch_budget.consume()
                timeout = min(timeout, self.dispatch_budget.check())
            result = self._transport(method, path, headers=headers, body=body, timeout=timeout,
                                     before_dispatch=self._dispatch_timeout)
        except OfficialEbayError:
            raise
        except DispatchDenied:
            raise OfficialEbayError("shared_dispatch_denied") from None
        except Exception:
            raise OfficialEbayError("ebay_official_transport_failed") from None
        self._check()
        try:
            if self.dispatch_budget: self.dispatch_budget.check()
        except DispatchDenied:
            raise OfficialEbayError("shared_dispatch_denied") from None
        try:
            if not isinstance(result, dict) or len(json.dumps(result, allow_nan=False).encode()) > MAX_BYTES:
                raise ValueError()
        except (TypeError, ValueError):
            raise OfficialEbayError("ebay_official_invalid_response") from None
        return result

    def _dispatch_timeout(self):
        if self.source_authorized is not None:
            self.source_authorized()
        instant = self._check()
        remaining = min((self._deadline - instant).total_seconds(),
                        self._monotonic_until - time.monotonic())
        try:
            if self.dispatch_budget: remaining = min(remaining, self.dispatch_budget.check())
        except DispatchDenied:
            raise OfficialEbayError("shared_dispatch_denied") from None
        return remaining

    def _headers(self):
        with self._lock:
            instant = self._check()
            if self._token is None:
                basic = base64.b64encode(f"{self._id}:{self._secret}".encode()).decode()
                token = self._request("POST", "/identity/v1/oauth2/token",
                    body=urlencode({"grant_type": "client_credentials", "scope": SCOPE}).encode(),
                    headers={"Authorization": f"Basic {basic}",
                             "Content-Type": "application/x-www-form-urlencoded"})
                access, ttl = token.get("access_token"), token.get("expires_in")
                if (not isinstance(access, str) or not 1 <= len(access) <= 8192
                        or re.search(r"[\s\x00-\x1f\x7f]", access)
                        or type(ttl) is not int or not 1 <= ttl <= 86400):
                    raise OfficialEbayError("ebay_official_invalid_token_response")
                self._token, self._token_until = access, instant + timedelta(seconds=ttl)
            if _stamp(self._now()) >= self._token_until:
                raise OfficialEbayError("ebay_official_token_expired")
            headers = {"Authorization": f"Bearer {self._token}",
                       "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE, "Accept": "application/json"}
            if self._campaign is not None:
                context = "affiliateCampaignId=" + self._campaign
                if self._reference:
                    context += ",affiliateReferenceId=" + self._reference
                headers["X-EBAY-C-ENDUSERCTX"] = context
            return headers

    def _normalize(self, item, stamp, *, allow_unavailable=False):
        try:
            if not isinstance(item, dict) or not REST_ID.fullmatch(item.get("itemId", "")):
                raise ValueError()
            _, legacy = _item_url(item.get("itemWebUrl"))
            if legacy != _legacy(item["itemId"]):
                raise ValueError()
            value = copy.deepcopy(item)
            value["itemWebUrl"] = f"https://www.ebay.com/itm/{legacy}"
            row = _ebay_item(value, "ebay_us", stamp, False,
                             allow_unavailable=allow_unavailable)
            if row.get("availability") != "unavailable":
                row["availability"] = "available" if value.get("estimatedAvailabilities") else "unknown"
            row["grade_company"] = row["marketplace_quality"]["grade_company"]
            row["grade_value"] = row["marketplace_quality"]["grade_value"]
            row["scope"] = "listing"
            # Admit only explicit item aspects. Titles never supply printing truth.
            from .listing_evidence import extracted_listing_evidence
            names = {"Language": "language", "Set Code": "set_code", "Card Number": "collector_number",
                     "Finish": "finish", "Edition": "edition"}
            properties = [{"name": names[a["name"]], "value": a.get("value")}
                          for a in value.get("localizedAspects", []) if isinstance(a, dict) and a.get("name") in names]
            images = [value.get("image"), *(value.get("additionalImages") or [])]
            image_urls = [image.get("imageUrl") for image in images if isinstance(image, dict)]
            identity, photos = extracted_listing_evidence("ebay_us", row["native_id"], row["url"], stamp, row["evidence_ref"],
                offer={"url": row["url"], "itemOffered": {"url": row["url"], "additionalProperty": properties}, "image": image_urls})
            row["listing_identity"], row["listing_photos"] = identity, photos
            # EPN absence/failure never changes the canonical listing identity.
            if self._campaign and item.get("itemAffiliateWebUrl"):
                try:
                    row["purchase_link"] = validate_purchase_link({"kind": "epn_affiliate",
                        "url": item["itemAffiliateWebUrl"], "disclosure": DISCLOSURE},
                        source="ebay_us", native_id=row["native_id"], canonical_url=row["url"],
                        campaign_id=self._campaign)
                except OfficialEbayError:
                    pass
            return row
        except (TypeError, ValueError, OverflowError):
            raise OfficialEbayError("ebay_official_unsupported_item") from None

    def search(self, query, *, limit=3):
        if (not isinstance(query, str) or not 2 <= len(query.strip()) <= 240
                or re.search(r"[\x00-\x1f\x7f]", query) or type(limit) is not int or not 1 <= limit <= 5):
            raise OfficialEbayError("ebay_official_invalid_query")
        params = urlencode({"q": query.strip(), "limit": limit,
                            "filter": "buyingOptions:{FIXED_PRICE}"})
        payload = self._request("GET", "/buy/browse/v1/item_summary/search?" + params,
                                headers=self._headers())
        items = payload.get("itemSummaries", [] if payload.get("total") == 0 else None)
        if not isinstance(items, list) or len(items) > limit or any(not isinstance(v, dict) for v in items):
            raise OfficialEbayError("ebay_official_invalid_response")
        if (any(not isinstance(v.get("itemId"), str) for v in items)
                or len({v["itemId"] for v in items}) != len(items)):
            raise OfficialEbayError("ebay_official_invalid_response")
        stamp = self._check().isoformat()
        rows = []
        for item in items:
            try:
                rows.append(self._normalize(item, stamp))
            except OfficialEbayError:
                continue
        return {"source": "ebay_us", "status": "researched" if rows else "no_results",
                "listings": rows}

    def detail(self, url):
        _, legacy = _item_url(url, canonical=True)
        payload = self._request("GET", "/buy/browse/v1/item/get_item_by_legacy_id?" +
                                urlencode({"legacy_item_id": legacy}), headers=self._headers())
        row = self._normalize(payload, self._check().isoformat(), allow_unavailable=True)
        if _legacy(row["native_id"]) != legacy:
            raise OfficialEbayError("ebay_official_item_mismatch")
        return row


class EbayOfficialCrawler:
    """Route eBay through approved Browse reads, preserving all other producers."""
    official_ebay_configured = True

    def __init__(self, fallback, client):
        if not isinstance(client, BrowseClient) or not client.enabled:
            raise OfficialEbayError("ebay_official_disabled")
        if getattr(fallback, "read_only_scope", False) or getattr(fallback, "mode", None) == "synthetic_fixture":
            raise OfficialEbayError("ebay_official_scope_conflict")
        self.fallback, self.client = fallback, client

    def __getattr__(self, name):
        return getattr(self.fallback, name)

    @property
    def official_ebay_enabled(self):
        try:
            self.client._check()
            return self.client._remaining > 0
        except OfficialEbayError:
            return False

    def search(self, source, query, limit=3):
        return (self.client.search(query, limit=limit) if source in {"ebay", "ebay_us"}
                else self.fallback.search(source, query, limit=limit))

    def detail(self, url):
        try:
            host = urlsplit(url).hostname
        except (TypeError, ValueError):
            raise OfficialEbayError("ebay_official_invalid_url") from None
        return self.client.detail(url) if host in {"ebay.com", "www.ebay.com"} else self.fallback.detail(url)


def configure_official_ebay(fallback, env, *, allow_network=False, read_until=None,
                            request_budget=None, transport=None, now=None, dispatch_budget=None):
    """Default-off wiring. Merely having credentials never authorizes a request."""
    if allow_network is not True:
        return fallback
    client = BrowseClient(env.get("EBAY_CLIENT_ID"), env.get("EBAY_CLIENT_SECRET"),
        allow_network=True, production_approved=env.get("EBAY_PRODUCTION_APPROVED") == "true",
        display_approved=env.get("EBAY_DISPLAY_APPROVED") == "true", read_until=read_until,
        request_budget=request_budget, affiliate_campaign_id=env.get("EBAY_EPN_CAMPAIGN_ID"),
        affiliate_approved=env.get("EBAY_EPN_APPROVED") == "true",
        affiliate_reference_id=env.get("EBAY_EPN_REFERENCE_ID"), transport=transport, now=now, dispatch_budget=dispatch_budget)
    return EbayOfficialCrawler(fallback, client)

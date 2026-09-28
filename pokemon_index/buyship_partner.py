"""Buy&Ship partner v1 quote preview, bound to one eligible indexed offer.

The partner API is URL-in, not a listing feed. This module deliberately has no
order-creation method: payment and buyer-confirmation semantics are unspecified.
"""

from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import time
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import core

QUOTE_COMPONENTS = ("items", "local_shipping", "international_shipping",
                    "duties", "bns_service_fee")


class PartnerAPIError(ValueError):
    def __init__(self, status: int, payload: dict[str, Any]):
        error = payload.get("error", {})
        if isinstance(error, str):
            error = {"code": error}
        if not isinstance(error, dict):
            error = {}
        self.status = status
        self.code = error.get("code", error.get("error", "unknown_error"))
        self.retryable = error.get("retryable", False)
        self.reason_codes = error.get("reason_codes", [])
        super().__init__(f"Buy&Ship {self.code} (HTTP {status})")


def _json_request(request: Request) -> tuple[int, dict[str, Any]]:
    try:
        with urlopen(request, timeout=20) as response:
            status, body = response.status, response.read(1_000_001)
    except HTTPError as exc:
        status, body = exc.code, exc.read(1_000_001)
    if len(body) > 1_000_000:
        raise ValueError("Buy&Ship response exceeds size limit")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("Buy&Ship returned non-JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Buy&Ship response must be a JSON object")
    return status, payload


class PartnerClient:
    """Server-side OAuth client for resolve and quote; never submits an order."""

    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 *, sender: Callable[[Request], tuple[int, dict[str, Any]]] = _json_request):
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.query:
            raise ValueError("Buy&Ship base URL must be HTTPS without credentials or query")
        if not client_id or not client_secret:
            raise ValueError("Buy&Ship client credentials are required")
        self.base_url = base_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.sender = sender
        self._token = ""
        self._token_expires = 0.0

    def _authenticate(self) -> None:
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        request = Request(self.base_url + "/v1/oauth/token", data=b"grant_type=client_credentials",
                          headers={"Authorization": "Basic " + basic,
                                   "Content-Type": "application/x-www-form-urlencoded",
                                   "Accept": "application/json"}, method="POST")
        status, payload = self.sender(request)
        if status >= 400:
            raise PartnerAPIError(status, payload)
        token, ttl = payload.get("access_token"), payload.get("expires_in")
        if not isinstance(token, str) or not token or type(ttl) is not int or ttl <= 0:
            raise ValueError("invalid Buy&Ship OAuth response")
        self._token = token
        self._token_expires = time.monotonic() + max(1, ttl - 30)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._token or time.monotonic() >= self._token_expires:
            self._authenticate()
        for attempt in range(2):
            request = Request(self.base_url + path,
                              data=json.dumps(body, ensure_ascii=False).encode(),
                              headers={"Authorization": "Bearer " + self._token,
                                       "Content-Type": "application/json",
                                       "Accept": "application/json"}, method="POST")
            status, payload = self.sender(request)
            if status == 401 and attempt == 0:
                self._authenticate()
                continue
            if status >= 400:
                raise PartnerAPIError(status, payload)
            return payload
        raise AssertionError("unreachable")

    def resolve(self, url: str) -> dict[str, Any]:
        _require_product_url(url)
        return self._post("/v1/products/resolve", {"url": url})

    def quote(self, reference_id: str, variant_key: str,
              destination: dict[str, str], currency: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"items": [{"reference_id": reference_id,
                                           "variant_key": variant_key, "quantity": 1}],
                                "destination": destination}
        if currency:
            body["currency"] = currency
        return self._post("/v1/quotes", body)


class FixturePartnerClient:
    """Offline contract fixture; useful before credentials or merchant support exist."""

    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def resolve(self, url: str) -> dict[str, Any]:
        self.calls.append({"endpoint": "resolve", "url": url})
        return self.payload["resolve"]

    def quote(self, reference_id: str, variant_key: str,
              destination: dict[str, str], currency: str | None = None) -> dict[str, Any]:
        self.calls.append({"endpoint": "quote", "reference_id": reference_id,
                           "variant_key": variant_key, "destination": destination,
                           "currency": currency})
        return self.payload["quote"]


def _require_product_url(url: str) -> None:
    if not isinstance(url, str):
        raise ValueError("offer URL must be a string")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("offer URL must be HTTPS with a hostname and no embedded credentials")


def _same_product_url(original: str, resolved: str) -> bool:
    _require_product_url(original)
    _require_product_url(resolved)
    left, right = urlsplit(original), urlsplit(resolved)
    return ((left.hostname or "").lower(), left.port or 443,
            left.path.rstrip("/"), left.query) == (
        (right.hostname or "").lower(), right.port or 443,
        right.path.rstrip("/"), right.query)


def _money(value: Any, currency: str | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Buy&Ship money field is missing")
    amount, code = value.get("subunit_amount"), value.get("currency")
    if type(amount) is not int or amount < 0 or not isinstance(code, str) or len(code) != 3:
        raise ValueError("invalid Buy&Ship money field")
    if currency and code != currency:
        raise ValueError("Buy&Ship quote contains mixed currencies")
    return {"currency": code, "subunit_amount": amount}


def preview_quote(db: sqlite3.Connection, *, card_id: str, unit_id: str,
                  source: str, native_id: str, destination: dict[str, str],
                  client: Any, now: str | None = None,
                  variant_key: str | None = None,
                  currency: str | None = None) -> dict[str, Any]:
    """Quote one current, permitted, exact-unit offer without creating an order."""
    country = destination.get("country") if isinstance(destination, dict) else None
    if country not in {"US", "HK"}:
        raise ValueError("Buy&Ship partner v1 supports US and HK destinations")
    if country == "US" and not destination.get("state"):
        raise ValueError("US destination needs a state")
    if isinstance(client, PartnerClient) and now is not None:
        raise ValueError("live Buy&Ship quotes must use the current clock")
    now = core.parse_time(now or core.utcnow())
    policy = core._policy(db, source, display=True)
    if not policy["partner_handoff_allowed"]:
        raise ValueError("source is not approved for Buy&Ship URL handoff")
    offers = core.offers(db, card_id, country, now.isoformat(), unit_id,
                         source_filter=source)
    matches = [offer for offer in offers if offer["source"] == source
               and offer["native_id"] == native_id]
    if len(matches) != 1:
        raise ValueError("no current, display-permitted offer for this exact card unit")
    offer = matches[0]
    _require_product_url(offer["url"])
    resolved = client.resolve(offer["url"])
    if not isinstance(resolved, dict) or not _same_product_url(offer["url"], resolved.get("url", "")):
        raise ValueError("Buy&Ship resolved a different product URL")
    reference_id, variants = resolved.get("reference_id"), resolved.get("variants")
    if not isinstance(reference_id, str) or not reference_id or not isinstance(variants, list) or not variants:
        raise ValueError("Buy&Ship resolve response lacks reference or variants")
    if variant_key is None:
        if len(variants) != 1:
            raise ValueError("multiple variants require explicit variant_key")
        selected = variants[0]
    else:
        selections = [item for item in variants if isinstance(item, dict)
                      and item.get("variant_key") == variant_key]
        if len(selections) != 1:
            raise ValueError("variant_key is absent or duplicated in resolved product")
        selected = selections[0]
    if not isinstance(selected, dict) or selected.get("availability") != "in_stock":
        raise ValueError("selected variant is not in stock")
    key = selected.get("variant_key")
    if not isinstance(key, str) or not key:
        raise ValueError("selected variant lacks variant_key")
    resolved_price = _money(selected.get("price"))
    quoted = client.quote(reference_id, key, destination, currency)
    received_at = core.parse_time(core.utcnow()) if isinstance(client, PartnerClient) else now
    if not isinstance(quoted, dict) or quoted.get("status") != "OPEN":
        raise ValueError("Buy&Ship quote is not open")
    quote_id, expires_at = quoted.get("quote_id"), quoted.get("expires_at")
    if not isinstance(quote_id, str) or not quote_id or not isinstance(expires_at, str):
        raise ValueError("Buy&Ship quote lacks id or expiry")
    if core.parse_time(expires_at) <= received_at:
        raise ValueError("Buy&Ship quote has expired")
    if quoted.get("destination") != destination:
        raise ValueError("Buy&Ship quote destination differs from request")
    quote_currency, items, totals = quoted.get("currency"), quoted.get("items"), quoted.get("totals")
    if not isinstance(quote_currency, str) or len(quote_currency) != 3:
        raise ValueError("Buy&Ship quote has invalid currency")
    if currency and quote_currency != currency:
        raise ValueError("Buy&Ship quote currency differs from request")
    if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
        raise ValueError("Buy&Ship v1 quote must contain one item")
    quoted_item = items[0]
    if (quoted_item.get("reference_id"), quoted_item.get("variant_key"), quoted_item.get("quantity")) != (
            reference_id, key, 1):
        raise ValueError("Buy&Ship quote item differs from selected variant")
    unit_price = _money(quoted_item.get("unit_price"), quote_currency)
    item_total = _money(quoted_item.get("item_total"), quote_currency)
    if unit_price != item_total:
        raise ValueError("Buy&Ship one-item quote has inconsistent unit and item totals")
    if not isinstance(totals, dict):
        raise ValueError("Buy&Ship quote lacks totals")
    components = {name: _money(totals.get(name), quote_currency) for name in QUOTE_COMPONENTS}
    grand_total = _money(totals.get("grand_total"), quote_currency)
    if components["items"] != item_total or grand_total["subunit_amount"] != sum(
            value["subunit_amount"] for value in components.values()):
        raise ValueError("Buy&Ship quote total does not reconcile")
    observation_price = ({"currency": offer["currency"],
                          "subunit_amount": offer["current_price_minor"]}
                         if offer["current_price_minor"] is not None else None)
    merchant = resolved.get("merchant")
    if merchant is not None and not isinstance(merchant, dict):
        raise ValueError("Buy&Ship merchant field is invalid")
    return {
        "status": "quote_ready_for_review", "purchasable": False,
        "purchase_action": None, "order_created": False,
        "card_id": card_id, "unit_id": unit_id,
        "listing": {"source": source, "native_id": native_id,
                    "url": offer["url"], "title": offer["title"],
                    "observed_at": offer["last_seen"], "ask": observation_price,
                    "identity_basis": offer["resolution_method"]},
        "buyship": {"reference_id": reference_id, "variant_key": key,
                    "canonical_url": resolved["url"],
                    "merchant_domain": (merchant or {}).get("domain"),
                    "resolve_price": resolved_price,
                    "resolve_price_differs_from_observation": (
                        observation_price is not None
                        and resolved_price["currency"] == observation_price["currency"]
                        and resolved_price["subunit_amount"] != observation_price["subunit_amount"]),
                    "quote_id": quote_id, "expires_at": expires_at,
                    "quoted_at": received_at.isoformat(),
                    "destination": destination, "currency": quote_currency,
                    "unit_price": unit_price, "components": components,
                    "grand_total": grand_total},
    }


def rank_quote_previews(previews: list[dict[str, Any]], *, now: str | None = None,
                        db: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Price-only shortlist for the same exact unit; no seller-quality claim."""
    if not previews:
        raise ValueError("at least one quote preview is required")
    checked_at = core.parse_time(now or core.utcnow())
    first = previews[0]
    identity = (first["card_id"], first["unit_id"],
                first["buyship"]["destination"], first["buyship"]["currency"])
    sources = {preview["listing"]["source"] for preview in previews}
    if len(sources) > 1:
        if db is None or any(not core._policy(db, source, display=True)["cross_source_use_allowed"]
                             for source in sources):
            raise ValueError("cross-source quote ranking lacks permission")
    seen: set[tuple[str, str]] = set()
    for preview in previews:
        if (preview.get("status") != "quote_ready_for_review"
                or preview.get("order_created") is not False
                or preview.get("purchasable") is not False
                or preview.get("purchase_action") is not None):
            raise ValueError("shortlist contains a non-preview quote")
        if (preview["card_id"], preview["unit_id"],
                preview["buyship"]["destination"], preview["buyship"]["currency"]) != identity:
            raise ValueError("shortlist mixes card units, destinations or currencies")
        if core.parse_time(preview["buyship"]["expires_at"]) <= checked_at:
            raise ValueError("shortlist contains an expired quote")
        if core.parse_time(preview["buyship"]["quoted_at"]) > checked_at:
            raise ValueError("shortlist contains a future quote")
        listing_key = (preview["listing"]["source"], preview["listing"]["native_id"])
        if listing_key in seen:
            raise ValueError("shortlist repeats a listing")
        seen.add(listing_key)
        _money(preview["buyship"]["grand_total"], identity[3])
    ordered = sorted(previews, key=lambda item: (
        item["buyship"]["grand_total"]["subunit_amount"],
        item["listing"]["source"], item["listing"]["native_id"]))
    return {"recommendation_type": "lowest_landed_quote_for_exact_unit",
            "ranking_basis": "same indexed priceable unit and Buy&Ship quoted total only; "
                             "seller quality, authenticity and visual condition not scored",
            "card_id": identity[0], "unit_id": identity[1],
            "destination": identity[2], "currency": identity[3],
            "best": ordered[0], "alternatives": ordered[1:],
            "purchasable": False, "purchase_action": None}


def _quote_preview_row(db: sqlite3.Connection, preview: dict[str, Any]) -> dict[str, Any]:
    """Prepare one storage row after source, snapshot and quote checks."""
    if (preview.get("status") != "quote_ready_for_review"
            or preview.get("purchasable") is not False
            or preview.get("purchase_action") is not None
            or preview.get("order_created") is not False):
        raise ValueError("only a non-purchasable quote preview can be stored")
    listing, quote = preview["listing"], preview["buyship"]
    source, native_id = listing["source"], listing["native_id"]
    policy = core._policy(db, source, display=True)
    if not policy["partner_handoff_allowed"] or not policy["partner_quote_store_allowed"]:
        raise ValueError("Buy&Ship quote storage is not approved for this source")
    quoted_at = core.parse_time(quote["quoted_at"])
    if core.parse_time(quote["expires_at"]) <= quoted_at:
        raise ValueError("Buy&Ship quote expired before receipt")
    country = quote["destination"]["country"]
    offers = core.offers(db, preview["card_id"], country, quoted_at.isoformat(),
                         preview["unit_id"], source_filter=source)
    matches = [offer for offer in offers if offer["native_id"] == native_id]
    if (len(matches) != 1 or matches[0]["url"] != listing["url"]
            or matches[0]["last_seen"] != listing["observed_at"]
            or matches[0]["current_price_minor"] != (
                listing["ask"]["subunit_amount"] if listing["ask"] else None)
            or matches[0]["currency"] != (
                listing["ask"]["currency"] if listing["ask"] else matches[0]["currency"])):
        raise ValueError("quote preview no longer matches its indexed offer snapshot")
    if not _same_product_url(listing["url"], quote["canonical_url"]):
        raise ValueError("quote preview URL differs from indexed listing")
    for key in ("quote_id", "reference_id", "variant_key"):
        if not isinstance(quote.get(key), str) or not quote[key]:
            raise ValueError(f"Buy&Ship quote lacks {key}")
    currency = quote["currency"]
    components = {name: _money(quote["components"].get(name), currency)["subunit_amount"]
                  for name in QUOTE_COMPONENTS}
    if sum(components.values()) != _money(quote["grand_total"], currency)["subunit_amount"]:
        raise ValueError("Buy&Ship quote total does not reconcile")
    mapped = {"item": components["items"], "domestic": components["local_shipping"],
              "international": components["international_shipping"],
              "tax": components["duties"], "service": components["bns_service_fee"],
              "insurance": 0, "fx_spread": 0, "other": 0}
    assumptions = {
        "provider": "buyship_partner_v1", "quote_id": quote["quote_id"],
        "reference_id": quote["reference_id"], "variant_key": quote["variant_key"],
        "unit_id": preview["unit_id"], "source_url": listing["url"],
        "source_observed_at": listing["observed_at"],
        "source_price_minor": listing["ask"]["subunit_amount"] if listing["ask"] else None,
        "source_currency": listing["ask"]["currency"] if listing["ask"] else None,
        "resolve_price": quote["resolve_price"],
        "resolve_price_differs_from_observation": quote["resolve_price_differs_from_observation"],
    }
    digest = hashlib.sha256(json.dumps({"listing": listing, "buyship": quote},
                                    sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()
    return {
        "source": source, "native_id": native_id, "destination": country,
        "currency": currency, "components": mapped,
        "quoted_at": quoted_at.isoformat(), "expires_at": quote["expires_at"],
        "evidence_ref": "buyship-partner:v1:sha256:" + digest,
        "assumptions": assumptions,
    }


def persist_quote_previews(db: sqlite3.Connection, previews: list[dict[str, Any]]) -> int:
    """Atomically store authorized quote previews for the existing offer index."""
    if not previews:
        raise ValueError("at least one quote preview is required")
    rows = [_quote_preview_row(db, preview) for preview in previews]
    return core.import_quotes(db, rows)


def persist_quote_preview(db: sqlite3.Connection, preview: dict[str, Any]) -> int:
    return persist_quote_previews(db, [preview])

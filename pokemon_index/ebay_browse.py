"""Conservative eBay Browse API pilot adapter and one-call access probe.

Search returns current asks, never verified sales. A search miss does not mean
an item sold. Production use requires eBay approval and a source policy.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode, urlparse

from .core import parse_time

SOURCE = "ebay_us"
MARKETPLACE = "EBAY_US"
SCOPE = "https://api.ebay.com/oauth/api_scope"
ITEM_ID = re.compile(r"^v1\|[0-9]+\|[0-9]+$")


def _digest(item: dict[str, Any]) -> str:
    raw = json.dumps(item, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _usd_cents(price: Any) -> int:
    if not isinstance(price, dict) or price.get("currency") != "USD":
        raise ValueError("eBay US pilot requires a USD price")
    value = price.get("value")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("eBay price is missing or invalid")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("eBay price is not decimal") from exc
    cents = amount * 100
    if not amount.is_finite() or amount < 0 or cents != cents.to_integral_value():
        raise ValueError("eBay price has invalid precision or sign")
    return int(cents)


def normalize_item(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Keep an observed fixed-price item unresolved until photo review."""
    if not isinstance(item, dict):
        raise ValueError("eBay item must be an object")
    native_id = str(item.get("itemId") or "")
    if not ITEM_ID.fullmatch(native_id):
        raise ValueError("eBay item ID is missing or invalid")
    if item.get("listingMarketplaceId", MARKETPLACE) != MARKETPLACE:
        raise ValueError("item belongs to a different eBay marketplace")
    options = item.get("buyingOptions")
    if not isinstance(options, list) or "FIXED_PRICE" not in options:
        raise ValueError("pilot excludes auction-only items")
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("eBay item has no title")
    url = item.get("itemWebUrl")
    parsed = urlparse(url) if isinstance(url, str) else None
    if (not parsed or parsed.scheme != "https" or parsed.hostname not in
            {"www.ebay.com", "ebay.com"} or parsed.username or parsed.password):
        raise ValueError("eBay US item URL is invalid")
    if item.get("itemCreationDate"):
        parse_time(item["itemCreationDate"])
    if item.get("itemEndDate") and parse_time(item["itemEndDate"]) <= parse_time(observed_at):
        raise ValueError("ended eBay item cannot become a current ask")
    seller = item.get("seller") or {}
    if not isinstance(seller, dict):
        raise ValueError("eBay seller must be an object")
    return {"source": SOURCE, "native_id": native_id, "title": title.strip(),
            "url": url, "seller_native_id": seller.get("username"),
            "observed_at": parse_time(observed_at).isoformat(),
            "status": "on_sale", "price_minor": _usd_cents(item.get("price")),
            "currency": "USD", "evidence_ref": f"ebay-browse:sha256:{_digest(item)}",
            "poll_reason": "discovery", "native_created": item.get("itemCreationDate"),
            "resolution_gate": "photo_required"}


def normalize_search(payload: dict[str, Any], observed_at: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise ValueError("eBay search response must be an object")
    items = payload.get("itemSummaries")
    if items is None and payload.get("total") == 0:
        return []
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ValueError("eBay search response lacks itemSummaries")
    if len(items) > 200 or len({item.get("itemId") for item in items}) != len(items):
        raise ValueError("eBay search page is too large or has duplicate item IDs")
    return [normalize_item(item, observed_at) for item in items]


def photo_candidates(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Retain eBay-hosted image refs for a separately authorized visual pass."""
    native_id = str(item.get("itemId") or "")
    if not ITEM_ID.fullmatch(native_id):
        raise ValueError("invalid eBay item ID")
    additional = item.get("additionalImages") or []
    if not isinstance(additional, list):
        raise ValueError("eBay additional images must be an array")
    images = [item.get("image"), *additional]
    if len(images) > 25:
        raise ValueError("too many eBay image refs")
    refs = []
    for image in images:
        if image is None:
            continue
        url = image.get("imageUrl") if isinstance(image, dict) else None
        parsed = urlparse(url) if isinstance(url, str) else None
        if (not parsed or parsed.scheme != "https" or
                not parsed.hostname or
                not (parsed.hostname == "ebayimg.com" or
                     parsed.hostname.endswith(".ebayimg.com")) or
                parsed.username or parsed.password):
            raise ValueError("eBay image ref must use an eBay image host")
        if url not in refs:
            refs.append(url)
    return {"source": SOURCE, "native_id": native_id,
            "observed_at": parse_time(observed_at).isoformat(),
            "photo_refs": refs, "orientation": "unclassified",
            "evidence_ref": f"ebay-browse:sha256:{_digest(item)}"}


class BrowseProbe:
    """One read-only search per invocation; never persists the API payload."""

    def __init__(self, client_id: str, client_secret: str, *,
                 environment: str = "sandbox", production_approved: bool = False,
                 timeout: int = 15):
        if environment not in {"sandbox", "production"}:
            raise ValueError("environment must be sandbox or production")
        if environment == "production" and not production_approved:
            raise ValueError("production Browse access requires explicit eBay approval")
        if not client_id or not client_secret:
            raise ValueError("eBay client credentials are missing")
        self.host = "api.sandbox.ebay.com" if environment == "sandbox" else "api.ebay.com"
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.environment = environment

    def _json(self, method: str, path: str, *, body: bytes | None = None,
              headers: dict[str, str] | None = None) -> dict[str, Any]:
        connection = http.client.HTTPSConnection(self.host, timeout=self.timeout)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("eBay response exceeds probe limit")
            if response.status != 200:
                raise RuntimeError(f"eBay {method} returned HTTP {response.status}")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise ValueError("eBay response is not a JSON object")
            return result
        finally:
            connection.close()

    def search_shape(self, query: str) -> dict[str, Any]:
        if not isinstance(query, str) or not 2 <= len(query.strip()) <= 120:
            raise ValueError("probe query must be 2–120 characters")
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        token = self._json("POST", "/identity/v1/oauth2/token",
                           body=urlencode({"grant_type": "client_credentials",
                                           "scope": SCOPE}).encode(),
                           headers={"Authorization": f"Basic {basic}",
                                    "Content-Type": "application/x-www-form-urlencoded"})
        access = token.get("access_token")
        if not isinstance(access, str) or not access:
            raise ValueError("eBay did not return an application access token")
        params = urlencode({"q": query.strip(), "limit": 5,
                            "filter": "buyingOptions:{FIXED_PRICE}"})
        result = self._json("GET", f"/buy/browse/v1/item_summary/search?{params}",
                            headers={"Authorization": f"Bearer {access}",
                                     "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE})
        items = result.get("itemSummaries", [])
        if not isinstance(items, list):
            raise ValueError("eBay probe search response lacks item list")
        return {"environment": self.environment, "marketplace": MARKETPLACE,
                "item_count": len(items), "response_fields": sorted(result),
                "item_fields": sorted({key for item in items if isinstance(item, dict)
                                       for key in item}),
                "scope": "shape-only access probe; no items or tokens retained"}

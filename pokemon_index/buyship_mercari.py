"""Mercari gateway adapter. Network access is limited to explicit Gate 0 probes.

The response shape is based on the old demo's Postman collection. Buy&Ship must
confirm the current contract and authorize collection before a live probe runs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .core import parse_time

API_PREFIX = "/v1/supplysrv/tanosys/mercari"
ITEM_ID_RE = re.compile(r"^m[0-9]+$", re.I)
KNOWN_STATUSES = {"on_sale", "trading", "sold_out"}


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def normalize_item(item: dict[str, Any], observed_at: str, *,
                   poll_reason: str = "discovery") -> dict[str, Any]:
    """Convert one gateway item to the index's observation contract.

    It deliberately leaves card identity and condition unresolved. Japanese
    marketplace location does not imply Japanese card language or grade.
    """
    if not isinstance(item, dict):
        raise ValueError("item must be an object")
    native_id = str(item.get("id") or "")
    if not ITEM_ID_RE.fullmatch(native_id):
        raise ValueError("missing or invalid Mercari item id")
    status = item.get("status")
    if status not in KNOWN_STATUSES:
        raise ValueError(f"unrecognized Mercari status: {status!r}")
    title = item.get("name")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Mercari item has no title")
    price = item.get("price")
    if price is not None and (type(price) is not int or price < 0):
        raise ValueError("Mercari price must be a nonnegative integer JPY amount")
    seller = item.get("seller") or {}
    if not isinstance(seller, dict):
        raise ValueError("Mercari seller must be an object")
    observed_at = parse_time(observed_at).isoformat()
    if poll_reason not in {"discovery", "tracking", "panel"}:
        raise ValueError("invalid poll reason")
    return {
        "source": "mercari_bns",
        "native_id": native_id,
        "title": title.strip(),
        "url": f"https://jp.mercari.com/item/{native_id}",
        "seller_native_id": str(seller["id"]) if seller.get("id") is not None else None,
        "observed_at": observed_at,
        "status": status,
        "price_minor": price,
        "currency": "JPY",
        "evidence_ref": f"mercari-gateway:sha256:{_digest(item)}",
        "poll_reason": poll_reason,
        "native_created": item.get("created"),
        "native_updated": item.get("updated"),
    }


def response_items(payload: dict[str, Any], endpoint: str) -> list[dict[str, Any]]:
    """Extract raw items without guessing absent or failed batch results."""
    if not isinstance(payload, dict):
        raise ValueError("gateway response must be an object")
    if endpoint == "search":
        items = payload.get("data")
    elif endpoint == "item":
        items = [payload.get("data", payload)]
    elif endpoint == "fetch_items":
        raw = payload.get("items")
        items = list(raw.values()) if isinstance(raw, dict) else raw
    else:
        raise ValueError("endpoint must be search, item, or fetch_items")
    if not isinstance(items, list):
        raise ValueError("gateway response has no expected items array")
    return items


def normalize_response(payload: dict[str, Any], observed_at: str, *,
                       endpoint: str, poll_reason: str = "discovery") -> list[dict[str, Any]]:
    """Accept search, item, or fetch_items response without guessing absent items."""
    items = response_items(payload, endpoint)
    return [normalize_item(item, observed_at, poll_reason=poll_reason) for item in items]


def photo_candidates(item: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Retain ordered photo refs without guessing which image shows the back.

    The older gateway contract exposes an unlabelled `photos` array. A later
    authorized image pass must assign front/back and hash fetched bytes.
    """
    native_id = str(item.get("id") or "")
    if not ITEM_ID_RE.fullmatch(native_id):
        raise ValueError("missing or invalid Mercari item id")
    photos = item.get("photos")
    if not isinstance(photos, list) or len(photos) > 20:
        raise ValueError("Mercari photos must be an array of at most 20 refs")
    refs = []
    for value in photos:
        parsed = urlparse(value) if isinstance(value, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname or parsed.username:
            raise ValueError("Mercari photo ref must be HTTPS")
        if value not in refs:
            refs.append(value)
    return {"source": "mercari_bns", "native_id": native_id,
            "observed_at": parse_time(observed_at).isoformat(),
            "photo_refs": refs,
            "orientation": "unclassified",
            "evidence_ref": f"mercari-gateway:sha256:{_digest(item)}"}


@dataclass(frozen=True)
class ProbeResult:
    check: str
    http_status: int | None
    outcome: str
    item_count: int | None = None
    statuses: tuple[str, ...] = ()
    response_keys: tuple[str, ...] = ()


class GatewayClient:
    """Read-only probe client for the old timestamp-HMAC gateway contract.

    Legacy signing must be explicitly enabled. It is a compatibility probe,
    not approval of the old signing design for production ingestion.
    """

    def __init__(self, base_url: str, secret: str, *, allow_legacy_auth: bool = False,
                 timeout: int = 15):
        if not allow_legacy_auth:
            raise ValueError("legacy timestamp-HMAC requires explicit opt-in and Buy&Ship confirmation")
        if not base_url.startswith("https://"):
            raise ValueError("gateway base URL must use HTTPS")
        if not secret:
            raise ValueError("missing gateway secret")
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.timeout = timeout

    def get(self, path: str, params: dict[str, Any]) -> tuple[int, Any]:
        if path not in {"search", "item", "fetch_items"}:
            raise ValueError("probe endpoint is not allowlisted")
        query = urlencode(params, doseq=True)
        url = f"{self.base_url}{API_PREFIX}/{path}?{query}"
        timestamp = str(int(time.time()))
        signature = hmac.new(self.secret.encode(), timestamp.encode(), hashlib.sha256).hexdigest()
        request = Request(url, headers={"timestamp": timestamp, "hmac": signature,
                                        "Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(2_000_001)
                status = response.status
        except HTTPError as exc:
            body = exc.read(2_000_001)
            status = exc.code
        except URLError as exc:
            raise ValueError(f"gateway transport failed: {exc.reason}") from exc
        if len(body) > 2_000_000:
            raise ValueError("gateway response exceeded probe size limit")
        try:
            return status, json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"gateway returned non-JSON response (HTTP {status})") from exc


def _summarize(check: str, status: int, payload: Any, endpoint: str) -> ProbeResult:
    if status >= 400:
        return ProbeResult(check, status, "http_error")
    try:
        items = normalize_response(payload, "2026-01-01T00:00:00Z", endpoint=endpoint)
    except ValueError:
        return ProbeResult(check, status, "unexpected_contract",
                           response_keys=tuple(sorted(payload)) if isinstance(payload, dict) else ())
    return ProbeResult(check, status, "ok", len(items),
                       tuple(sorted({item["status"] for item in items})),
                       tuple(sorted(payload)) if isinstance(payload, dict) else ())


def gate0_probe(client: GatewayClient, *, historical_item_id: str,
                category_id: str | None = None) -> list[ProbeResult]:
    """Run at most three requests. No wide sweep or continuous polling."""
    if not ITEM_ID_RE.fullmatch(historical_item_id):
        raise ValueError("invalid historical item id")
    checks = [("historical_item", "item", {"item_id": historical_item_id})]
    if category_id:
        checks += [
            ("category_feed", "search", {"category_id": category_id, "sort": "created_time",
                                           "order": "desc", "page": 1, "limit": 5}),
            ("sold_search", "search", {"category_id": category_id, "status": "sold_out",
                                         "sort": "created_time", "order": "desc", "page": 1,
                                         "limit": 5}),
        ]
    results = []
    for name, endpoint, params in checks:
        status, payload = client.get(endpoint, params)
        results.append(_summarize(name, status, payload, endpoint))
    return results

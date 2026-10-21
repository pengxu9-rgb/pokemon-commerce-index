"""On-demand listing research, explicit selection and URL-in forwarder handoff.

Research is transient evidence, never an approval to join a catalog identity or
write marketplace inventory. Producers and quote providers are server-owned
dependencies. No order, checkout or payment operation exists here.
"""
from __future__ import annotations

from contextlib import closing
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import threading
from urllib.parse import urlsplit

SCHEMA = "pokemon.agent-commerce.v1"
SOURCES = ("mercari", "ebay_us", "snkrdunk")
MAX_OFFERS = 2000
RESEARCH_MESSAGES = {
    "network_disabled": "Live research is disabled in this sidecar.",
    "source_access_not_authorized": "This marketplace is not enabled in the server's research configuration.",
    "public_discovery_seed_required": "SNKRDUNK discovery needs configured public seed pages or an allowed sitemap; a product URL can be researched directly.",
    "query_mapping_required": "No matching listing could be established. Include the card number and set, or paste the exact product URL.",
    "public_search_has_no_listing_links": "The public search page did not expose listing links. This does not establish that no listings exist.",
    "robots_disallowed": "The public page's robots policy blocks this research route.",
    "robots_unavailable": "The public page's robots policy could not be checked.",
    "robots_pacing_requires_scheduled_crawl": "This page requires pacing that the on-demand research budget cannot satisfy.",
    "login_required": "This public research route requires login and is unavailable here.",
    "public_page_challenge": "The public page presented an access challenge; research could not continue.",
    "crawl_budget_exhausted": "The bounded research budget ended before this marketplace could be refreshed.",
    "some_public_pages_unavailable": "Some discovered product pages could not be refreshed; the visible results are partial.",
}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid evidence timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("evidence timestamps need a timezone")
    return result.astimezone(timezone.utc)


class CommerceError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _text(value, field, maximum=256):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        raise CommerceError("invalid_request", f"Invalid {field}.")
    return value.strip()


def _request(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise CommerceError("invalid_request", "The request has missing or unsupported fields.")


def _source(value):
    value = "ebay_us" if value == "ebay" else value
    if value not in SOURCES:
        raise CommerceError("invalid_request", "Unsupported marketplace.")
    return value


def _url(value, source, fixture=False):
    """Defense in depth: only marketplace product pages may reach a producer."""
    value = _text(value, "product URL", 2048)
    if not fixture:
        from .marketplace_crawl import canonical_product_url
        try:
            detected, _, canonical = canonical_product_url(value)
        except (ValueError, TypeError) as exc:
            raise CommerceError("invalid_product_url", "This is not a supported marketplace product URL.") from exc
        if detected != source:
            raise CommerceError("invalid_product_url", "Product URL belongs to a different marketplace.")
        return canonical
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CommerceError("invalid_product_url", "Invalid product URL.") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or port not in (None, 443) or parsed.fragment):
        raise CommerceError("invalid_product_url", "A supported HTTPS product URL is required.")
    host, path = parsed.hostname.lower(), parsed.path.rstrip("/")
    valid = host == f"{source}.example.invalid" and not parsed.query and bool(re.fullmatch(r"/item/[a-zA-Z0-9_-]+", path))
    if not valid:
        raise CommerceError("invalid_product_url", "This is not a supported marketplace product URL.")
    return value


def _source_url(value, fixture=False):
    for source in SOURCES:
        try:
            return source, _url(value, source, fixture)
        except CommerceError:
            continue
    raise CommerceError("invalid_product_url", "This is not a supported marketplace product URL.")


def _fingerprint(offer):
    fields = ("source", "native_id", "url", "title", "price_minor", "currency",
              "availability", "listing_status", "grade", "scope", "seller_condition", "certificate_number_claim")
    return hashlib.sha256(json.dumps({key: offer.get(key) for key in fields},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _quote_block_reason(offer):
    if offer.get("scope") != "listing":
        return "exact_listing_not_established"
    if offer.get("availability") != "available" or offer.get("listing_status") != "on_sale":
        return "stock_not_confirmed"
    if (type(offer.get("price_minor")) is not int or not 0 <= offer["price_minor"] < 2**63
            or not isinstance(offer.get("currency"), str) or not re.fullmatch(r"[A-Z]{3}", offer["currency"])):
        return "native_price_unavailable"
    return None


class FixtureCrawler:
    """Explicit synthetic UI/demo producer. It never calls a network or database."""
    mode = "synthetic_fixture"

    def __init__(self, *, now=utcnow):
        self.now = now

    def _listing(self, source, slab=False):
        native = "demo-psa" if slab else "demo-raw"
        return {"source": source, "native_id": native,
            "url": f"https://{source}.example.invalid/item/{native}",
            "title": "Synthetic Pikachu SV2a 173/165" + (" PSA 10 graded card" if slab else ""),
            "price_minor": ({"mercari": 12000, "snkrdunk": 13500, "ebay_us": 9950}[source]
                            if slab else {"mercari": 3800, "snkrdunk": 4200, "ebay_us": 2995}[source]),
            "currency": "USD" if source == "ebay_us" else "JPY",
            "availability": "in_stock", "status": "on_sale", "observed_at": self.now(),
            "scope": "listing", "grade_company": "PSA" if slab else None,
            "grade_value": "10" if slab else None, "identity_status": "unresolved",
            "certificate_number_claim": None, "marketplace_quality": {},
            "evidence_ref": f"synthetic-fixture:{source}:{native}"}

    def search(self, source, query, limit=5):
        return {"source": source, "status": "synthetic_fixture",
            "message": "Synthetic examples; no real marketplace was contacted.",
            "listings": [self._listing(source), self._listing(source, True)][:limit]}

    def detail(self, url):
        source, _ = _source_url(url, True)
        return self._listing(source, url.endswith("demo-psa"))


class BoundBuyShipForwarder:
    """Reuse the existing quote gate against an explicitly configured operator DB.

    Crawled candidates are not imported. A quote additionally needs an existing
    current exact-unit observation, approved source and matching seller evidence.
    """
    id, label = "buyship", "Buy & Ship"

    def __init__(self, database, client):
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise ValueError("an existing operator database is required")
        self.client = client

    @staticmethod
    def _quality_binding(db, card_id, offer, row):
        from . import core, market_tracking
        card = db.execute("SELECT * FROM card WHERE card_id=?", (card_id,)).fetchone()
        metadata, _ = market_tracking._observation_quality(db, row["source"], row["native_id"], row["last_seen"])
        quality = market_tracking._quality(core, row["title"], row, card, metadata)
        claimed = offer["grade"]
        expected = (None, None) if row["grade_company"] == "RAW" else (row["grade_company"], row["grade_value"])
        if (claimed["company"], claimed["value"]) != expected:
            raise ValueError("refreshed seller grade differs from indexed unit")
        for field in ("seller_condition", "certificate_number_claim"):
            if offer.get(field) != quality.get(field):
                raise ValueError("refreshed seller evidence differs from indexed observation")
        return hashlib.sha256(json.dumps(metadata, sort_keys=True, allow_nan=False,
            separators=(",", ":")).encode()).hexdigest()

    def preview(self, card_id, offer, destination):
        from . import buyship_partner, core
        if _quote_block_reason(offer):
            raise ValueError("current research does not establish an available, priced exact listing")
        with closing(core.connect(str(self.database), readonly=True)) as db:
            row = db.execute("""SELECT l.*,u.card_id,u.grade_company,u.grade_value,u.condition_bucket
                FROM listing l JOIN priceable_unit u ON l.unit_id=u.unit_id
                WHERE l.source=? AND l.native_id=? AND u.card_id=?""",
                (offer["source"], offer["native_id"], card_id)).fetchone()
            if row is None or any(row[key] != offer[field] for key, field in (
                    ("url", "url"), ("title", "title"), ("current_price_minor", "price_minor"),
                    ("currency", "currency"))):
                raise ValueError("researched candidate lacks a matching indexed offer")
            quality_binding = self._quality_binding(db, card_id, offer, row)
            quote = buyship_partner.preview_quote(db, card_id=card_id, unit_id=row["unit_id"],
                source=row["source"], native_id=row["native_id"], destination=destination, client=self.client)
        # The frozen quote snapshot does not include the additive marketplace
        # quality table. Reopen it after the provider calls as a separate guard.
        with closing(core.connect(str(self.database), readonly=True)) as validation:
            if self._quality_binding(validation, card_id, offer, row) != quality_binding:
                raise ValueError("observation quality changed during provider quote")
        return quote


class CommerceLoop:
    """Bounded in-memory research state, owned by the authenticated proxy caller.

    A restart discards selections. No user-provided URL is accepted by handoff;
    it re-fetches the URL retained from the selected server-owned research result.
    """
    def __init__(self, crawler, *, forwarders=None, now=utcnow,
                 freshness_seconds=300, selection_seconds=600):
        if not 1 <= freshness_seconds <= 3600 or not 1 <= selection_seconds <= 3600:
            raise ValueError("invalid commerce state bounds")
        self.crawler, self.now = crawler, now
        self.mode = "synthetic_fixture" if getattr(crawler, "mode", None) == "synthetic_fixture" else "on_demand_research"
        self.forwarders = dict(forwarders or {})
        if set(self.forwarders) - {"buyship", "other"}:
            raise ValueError("unsupported forwarder registry key")
        self.freshness_seconds, self.selection_seconds = freshness_seconds, selection_seconds
        self._offers, self._selections, self._lock = {}, {}, threading.RLock()
        # Crawler owns per-call page/robots budgets, so one instance must not be
        # used by two HTTP threads simultaneously.
        self._producer_lock = threading.Lock()

    def _produce(self, callback):
        if not self._producer_lock.acquire(timeout=0.1):
            raise CommerceError("research_busy", "Another research refresh is running. Retry shortly.", 503)
        try:
            return callback()
        finally:
            self._producer_lock.release()

    def _base(self):
        return {"schema": SCHEMA, "mode": self.mode, "checked_at": self.now(),
                "purchasable": False, "purchase_action": None, "order_created": False}

    def _owner(self, owner):
        return _text(owner, "authenticated owner", 128)

    def _purge(self, instant):
        for state in (self._offers, self._selections):
            for key in list(state):
                if state[key]["expires"] <= instant:
                    del state[key]

    def capabilities(self):
        return [{"id": key, "label": label, "quote_available": key in self.forwarders,
                 "manual_handoff_available": True}
                for key, label in (("buyship", "Buy & Ship"), ("other", "Other forwarder"))]

    def _offer(self, raw, source, instant):
        if not isinstance(raw, dict) or _source(raw.get("source")) != source:
            raise ValueError("producer source mismatch")
        observed = _time(raw.get("observed_at"))
        if observed > instant or observed < instant - timedelta(seconds=self.freshness_seconds):
            raise ValueError("producer returned stale or future evidence")
        price, currency = raw.get("price_minor"), raw.get("currency")
        if price is not None and (type(price) is not int or not 0 <= price < 2**63):
            raise ValueError("invalid native ask")
        if currency is not None and (not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency)):
            raise ValueError("invalid native currency")
        if price is not None and currency is None:
            raise ValueError("priced candidate needs a currency")
        availability = {"in_stock": "available", "out_of_stock": "sold_out"}.get(
            raw.get("availability"), raw.get("availability", "unknown"))
        if availability not in {"available", "sold_out", "unknown"}:
            raise ValueError("invalid availability evidence")
        listing_status = raw.get("status", "unknown")
        if listing_status not in {"on_sale", "sold_out", "gone", "trading", "unknown"}:
            raise ValueError("invalid listing status")
        if raw.get("status") in {"sold_out", "gone", "trading"}:
            availability = "sold_out"
        scope = raw.get("scope", "listing")
        if scope not in {"listing", "product_summary"}:
            raise ValueError("unsupported research scope")
        company, grade = raw.get("grade_company"), raw.get("grade_value")
        if company == "RAW":
            company, grade = None, None
        if company not in {None, "PSA", "BGS", "CGC", "ARS", "PGC"}:
            raise ValueError("unsupported grader claim")
        if grade is not None and (not isinstance(grade, str) or not re.fullmatch(r"(?:10|[0-9])(?:\.5)?", grade)
                                  or float(grade) > 10 or company is None):
            raise ValueError("invalid seller grade claim")
        metadata = raw.get("marketplace_quality") or {}
        if not isinstance(metadata, dict):
            raise ValueError("invalid seller quality evidence")
        result = {"source": source, "native_id": _text(raw.get("native_id"), "listing ID", 128),
            "url": _url(raw.get("url"), source, self.mode == "synthetic_fixture"),
            "title": _text(raw.get("title"), "listing title", 2000), "price_minor": price,
            "currency": currency, "availability": availability, "observed_at": observed.isoformat(),
            "listing_status": listing_status,
            "fresh_until": (observed + timedelta(seconds=self.freshness_seconds)).isoformat(),
            "grade": {"company": company, "value": grade, "certificate_verified": False},
            "identity_status": "unverified_candidate", "scope": scope,
            "authenticity_verified": False,
            "seller_condition": metadata.get("seller_condition"),
            "certificate_number_claim": raw.get("certificate_number_claim") or metadata.get("certificate_number_claim"),
            "evidence_ref": raw.get("evidence_ref"), "synthetic": self.mode == "synthetic_fixture"}
        for field in ("seller_condition", "certificate_number_claim", "evidence_ref"):
            if result[field] is not None:
                result[field] = _text(result[field], field, 2048)
        return result

    def research(self, owner, request):
        owner = self._owner(owner)
        _request(request, ("card_id", "query"), ("platforms", "product_urls"))
        card_id = _text(request["card_id"], "card context")
        query = _text(request["query"], "search query", 240)
        sources = request.get("platforms", list(SOURCES))
        if not isinstance(sources, list) or not 1 <= len(sources) <= 3:
            raise CommerceError("invalid_request", "Choose one through three marketplaces.")
        sources = [_source(s) for s in sources]
        if len(set(sources)) != len(sources):
            raise CommerceError("invalid_request", "Duplicate marketplaces are unsupported.")
        urls = request.get("product_urls", [])
        if (not isinstance(urls, list) or len(urls) > 8 or any(not isinstance(url, str) for url in urls)
                or len(set(urls)) != len(urls)):
            raise CommerceError("invalid_request", "Use at most eight distinct product URLs.")
        validated = [_source_url(url, self.mode == "synthetic_fixture") for url in urls]
        if any(source not in sources for source, _ in validated):
            raise CommerceError("invalid_request", "Product URLs must belong to the chosen marketplaces.")
        result = self._base() | {"card_id": card_id, "platforms": [], "offers": [], "forwarders": self.capabilities()}
        for source in sources:
            try:
                chosen = [url for src, url in validated if src == source]
                response = self._produce(lambda: (
                    {"status": "researched", "listings": [self.crawler.detail(url) for url in chosen]}
                    if chosen else self.crawler.search(source, query, limit=3)))
                if not isinstance(response, dict) or not isinstance(response.get("listings", []), list) or len(response.get("listings", [])) > 20:
                    raise ValueError("invalid or oversized producer response")
                instant = _time(self.now())
                offers = [self._offer(raw, source, instant) for raw in response.get("listings", [])]
                if len({(offer["native_id"], offer["url"]) for offer in offers}) != len(offers):
                    raise ValueError("duplicate producer listing")
                with self._lock:
                    self._purge(instant)
                    if len(self._offers) + len(offers) > MAX_OFFERS:
                        raise CommerceError("research_capacity", "Research capacity is temporarily full.", 503)
                    for offer in offers:
                        offer["offer_id"] = secrets.token_urlsafe(24)
                        self._offers[offer["offer_id"]] = {"owner": owner, "card_id": card_id,
                            "offer": copy.deepcopy(offer), "expires": _time(offer["fresh_until"])}
                result["offers"].extend(offers)
                status = str(response.get("status", "researched"))
                if status not in {"researched", "ok", "success", "synthetic_fixture", "blocked", "unavailable", "no_results", "partial"}:
                    status = "researched" if offers else "unavailable"
                message = ("Synthetic examples; no real marketplace was contacted." if self.mode == "synthetic_fixture"
                           else RESEARCH_MESSAGES.get(response.get("message"),
                               "Current page evidence was researched; card identity and seller claims remain unverified." if offers
                               else "No current listing evidence is available from this research route."))
                result["platforms"].append({"source": source, "status": status, "message": message})
            except CommerceError as exc:
                if exc.status == 503:
                    raise
                result["platforms"].append({"source": source, "status": "unavailable", "message": "The research route returned unsupported listing evidence."})
            except Exception:
                result["platforms"].append({"source": source, "status": "unavailable", "message": "This marketplace could not be refreshed. Retry research later."})
        result["checked_at"] = self.now()
        return result

    def select(self, owner, request):
        owner = self._owner(owner)
        _request(request, ("card_id", "offer_id", "expected_observed_at", "expected_price_minor", "currency"))
        if request["expected_price_minor"] is not None and type(request["expected_price_minor"]) is not int:
            raise CommerceError("invalid_request", "Expected price must be an integer or null.")
        instant = _time(self.now())
        with self._lock:
            self._purge(instant)
            record = self._offers.get(_text(request["offer_id"], "offer ID"))
            if not record or record["owner"] != owner:
                raise CommerceError("offer_unavailable", "Research this listing again before selecting it.", 409)
            offer = record["offer"]
            if record["card_id"] != request["card_id"] or any(request[key] != offer[field] for key, field in (
                    ("expected_observed_at", "observed_at"), ("expected_price_minor", "price_minor"), ("currency", "currency"))):
                raise CommerceError("offer_changed", "The selected listing differs from the displayed evidence. Research again.", 409)
            if offer["availability"] == "sold_out":
                raise CommerceError("offer_unavailable", "This listing is not available.", 409)
            if sum(row["owner"] == owner for row in self._selections.values()) >= 20:
                raise CommerceError("selection_capacity", "Too many active selections. Wait for an earlier selection to expire.", 429)
            if len(self._selections) >= MAX_OFFERS:
                raise CommerceError("selection_capacity", "Selection capacity is temporarily full.", 503)
            key = secrets.token_urlsafe(32)
            expires = instant + timedelta(seconds=self.selection_seconds)
            self._selections[key] = {"owner": owner, "card_id": record["card_id"], "offer": copy.deepcopy(offer),
                "fingerprint": _fingerprint(offer), "expires": expires, "busy": False}
        return self._base() | {"selection_id": key, "expires_at": expires.isoformat(), "offer": copy.deepcopy(offer)}

    def handoff(self, owner, request):
        owner = self._owner(owner)
        _request(request, ("selection_id", "forwarder", "destination"))
        forwarder = request["forwarder"]
        if not isinstance(forwarder, str) or forwarder not in {"buyship", "other"}:
            raise CommerceError("invalid_request", "Unsupported forwarder.")
        destination = request["destination"]
        if (not isinstance(destination, dict) or set(destination) - {"country", "state"}
                or not isinstance(destination.get("country"), str) or not re.fullmatch(r"[A-Z]{2}", destination["country"])
                or ("state" in destination and (not isinstance(destination["state"], str) or not re.fullmatch(r"[A-Za-z0-9 -]{1,32}", destination["state"])))):
            raise CommerceError("invalid_request", "Destination accepts a country code and optional state only.")
        key = _text(request["selection_id"], "selection ID")
        with self._lock:
            self._purge(_time(self.now()))
            record = self._selections.get(key)
            if not record or record["owner"] != owner:
                raise CommerceError("selection_expired", "Select a freshly researched listing before handoff.", 409)
            if record["busy"]:
                raise CommerceError("selection_busy", "This selection is already being refreshed.", 409)
            record["busy"] = True
        try:
            try:
                raw = self._produce(lambda: self.crawler.detail(record["offer"]["url"]))
                refreshed = self._offer(raw, record["offer"]["source"], _time(self.now()))
            except Exception as exc:
                raise CommerceError("refresh_unavailable", "The selected product page could not be refreshed. No handoff was prepared.", 503) from exc
            with self._lock:
                if record["expires"] <= _time(self.now()):
                    self._selections.pop(key, None)
                    raise CommerceError("selection_expired", "This selection expired during refresh. Select again.", 409)
                if refreshed["availability"] == "sold_out" or _fingerprint(refreshed) != record["fingerprint"]:
                    self._selections.pop(key, None)
                    raise CommerceError("offer_changed", "The product URL, price, availability or seller evidence changed. Research and select again.", 409)
            result = self._base() | {"status": "manual_handoff_required", "selection_id": key,
                "product_url": refreshed["url"], "offer": refreshed,
                "forwarder": {"id": forwarder, "label": "Buy & Ship" if forwarder == "buyship" else "Other forwarder"},
                "destination": dict(destination), "quote": None, "quote_status": "provider_unconfigured",
                "message": "Copy this product URL into your forwarder. A live shipping quote is unavailable."}
            provider = self.forwarders.get(forwarder)
            blocked_quote = _quote_block_reason(refreshed)
            if blocked_quote:
                result.update(quote_status=blocked_quote,
                    message=("The URL is ready for manual handoff. Current stock is unconfirmed, so no provider quote was requested."
                             if blocked_quote == "stock_not_confirmed" else
                             "The URL is ready for manual handoff. A priced, exact listing is not established, so no provider quote was requested."))
            elif provider is not None:
                try:
                    quote = provider.preview(record["card_id"], refreshed, dict(destination))
                    if not isinstance(quote, dict) or quote.get("status") != "quote_ready_for_review" or quote.get("purchasable") is not False or quote.get("order_created") is not False or quote.get("purchase_action") is not None:
                        raise ValueError("provider did not return a non-purchasable quote preview")
                    result.update(status="quote_ready_for_review", quote=quote, quote_status="ready",
                                  message="Review the provider's current landed quote. No order was created.")
                except Exception:
                    result.update(quote_status="eligible_indexed_quote_unavailable",
                        message="The refreshed URL is ready for manual handoff. An eligible indexed provider quote is unavailable.")
            completed_at = self.now()
            completed = _time(completed_at)
            if record["expires"] <= completed:
                with self._lock:
                    self._selections.pop(key, None)
                raise CommerceError("selection_expired", "This selection expired while preparing the handoff. Select again.", 409)
            if _time(refreshed["fresh_until"]) <= completed:
                with self._lock:
                    self._selections.pop(key, None)
                raise CommerceError("offer_expired", "The refreshed listing evidence expired while preparing the handoff. Research and select again.", 409)
            result["checked_at"] = completed_at
            if self.mode == "synthetic_fixture":
                result["message"] = "Synthetic demonstration only. This example URL cannot be purchased or sent to a real forwarder."
            return result
        finally:
            with self._lock:
                record["busy"] = False

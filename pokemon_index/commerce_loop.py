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
import time
from urllib.parse import urlsplit

from .seller_evidence import seller_for_listing, seller_identity
from .listing_evidence import FIELDS as IDENTITY_FIELDS, identity_evidence, normalized, research_coverage, semantic_binding, validate_photos

SCHEMA = "pokemon.agent-commerce.v1"
SOURCES = ("mercari", "ebay_us", "snkrdunk")
MAX_OFFERS = 2000
HANDOFF_SECONDS = 22
RESEARCH_MESSAGES = {
    "explicit_listing_url_required": "Paste an approved exact SNKRDUNK used-listing URL to research it. General marketplace search is disabled in this test.",
    "public_listing_url_not_authorized": "This exact listing URL is outside this test's approved research scope.",
    "public_listing_source_not_authorized": "This test can research only its approved SNKRDUNK used listings.",
    "public_listing_redirect_not_allowed": "This approved listing redirected, so research stopped without following it.",
    "public_read_window_expired": "This private public-page research window has ended.",
    "public_read_clock_invalid": "The research clock could not be safely checked. This test's public-page access has stopped.",
    "public_request_budget_exhausted": "This process has used its public-page request allowance. No further page was requested.",
    "read_only_scope": "This test supports public-page research only. Selection, certificate lookup and handoff are disabled.",
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
    "public_primary_image_preload": "A public search image hint led to this listing; its product page was checked separately. Identity and stock remain unverified.",
    "query_bound_public_browse_research": "Configured public browse pages supplied candidates; their product pages were checked separately. This is not an exhaustive search.",
    "public_browse_has_no_matching_listing_links": "The configured public browse pages exposed no matching listing links. This does not establish that no listings exist.",
    "http_403": "The marketplace refused this public page request (HTTP 403). No access challenge was bypassed.",
    "http_429": "The marketplace rate-limited this public page request. Research stopped without retrying.",
    "response_too_large": "The public page exceeded the bounded response size and was not used as listing evidence.",
    "public_renderer_failed": "Public browser discovery failed. Paste a supported product URL to check its public page directly.",
    "browser_renderer_dns_unavailable": "Public browser discovery could not establish a safe source DNS address.",
    "browser_renderer_navigation_timeout": "Public browser discovery timed out while loading the search page.",
    "browser_renderer_navigation_failed": "Public browser discovery could not load the search page.",
    "browser_renderer_source_unavailable": "The public search page refused browser discovery or redirected outside the checked route.",
    "browser_renderer_challenge": "The public search page presented an access challenge. Browser discovery stopped.",
    "browser_renderer_no_listing_links": "The rendered public search page exposed no listing links. This does not establish that no listings exist.",
    "browser_renderer_request_budget_exhausted": "Public browser discovery reached its request limit and stopped.",
    "browser_renderer_deadline_exhausted": "Public browser discovery reached its whole-operation deadline and stopped.",
    "browser_renderer_timeout": "Public browser discovery reached its process timeout and stopped.",
    "browser_renderer_unavailable": "The configured public browser discovery runtime is unavailable.",
    "browser_renderer_invalid_response": "Public browser discovery returned unsupported evidence and was rejected.",
    "browser_renderer_failed": "Public browser discovery failed. No listing evidence was accepted from it.",
    "browser_renderer_response_too_large": "Public browser discovery exceeded its bounded response size and stopped.",
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
              "availability", "listing_status", "grade", "scope", "seller_condition", "source_status_text", "certificate_number_claim", "listing_quantity")
    value = {key: offer.get(key) for key in fields}
    provenance = offer.get("source_provenance")
    if provenance is not None:
        value["source_route"] = {key: provenance.get(key) for key in ("source", "method")}
    # A changing capture timestamp is not a different seller. A changed or newly
    # reported seller identity does require a new explicit listing selection.
    value["seller"] = seller_identity(offer.get("seller"))
    value["listing_evidence"] = semantic_binding(offer)
    return hashlib.sha256(json.dumps(value,
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _deduplicate_offers(offers):
    """One canonical platform listing may arrive twice, not become two offers.

    Current marketplace IDs are platform-global. Contradictory identity/price
    observations fail the source rather than choosing a convenient low price.
    Distinct listing IDs/URLs are retained even when their seller is identical.
    """
    by_listing, native_urls, url_natives = {}, {}, {}
    for offer in offers:
        native, url = offer["native_id"], offer["url"]
        if (native in native_urls and native_urls[native] != url
                or url in url_natives and url_natives[url] != native):
            raise ValueError("conflicting canonical listing identity")
        native_urls[native], url_natives[url] = url, native
        key = native, url
        previous = by_listing.get(key)
        if previous is not None and _fingerprint(previous) != _fingerprint(offer):
            raise ValueError("contradictory duplicate producer listing")
        if previous is None or _time(offer["observed_at"]) > _time(previous["observed_at"]):
            by_listing[key] = offer
    return list(by_listing.values())


def _quote_block_reason(offer):
    if offer.get("scope") != "listing":
        return "exact_listing_not_established"
    if offer.get("availability") != "available" or offer.get("listing_status") != "on_sale":
        return "stock_not_confirmed"
    if offer.get("grade", {}).get("review_required"):
        return "grade_review_required"
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
            "scope": "listing", "grade_company": "PSA" if slab else "RAW",
            "grade_value": "10" if slab else "raw", "identity_status": "unresolved",
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

    def _indexed_binding(self, card_id, offer, destination, *, deadline=None):
        """Read the selected unit and its additive quality from one fresh snapshot."""
        from . import buyship_partner, core
        remaining = 5.0 if deadline is None else deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError("indexed validation deadline expired")
        with closing(core.connect(str(self.database), readonly=True, timeout=min(remaining, 0.1) if deadline is not None else remaining)) as db:
            if deadline is not None:
                db.set_progress_handler(lambda: time.monotonic() >= deadline, 1000)
            db.execute("BEGIN")
            row = db.execute("""SELECT l.*,u.card_id,u.grade_company,u.grade_value,u.condition_bucket
                FROM listing l JOIN priceable_unit u ON l.unit_id=u.unit_id
                WHERE l.source=? AND l.native_id=? AND u.card_id=?""",
                (offer["source"], offer["native_id"], card_id)).fetchone()
            if row is None or any(row[key] != offer[field] for key, field in (
                    ("url", "url"), ("title", "title"), ("current_price_minor", "price_minor"),
                    ("currency", "currency"))):
                raise ValueError("researched candidate lacks a matching indexed offer")
            claimed_seller = (offer.get("seller") or {}).get("id")
            indexed_seller = row["seller_native_id"]
            if claimed_seller is not None and indexed_seller is not None and claimed_seller != indexed_seller:
                raise ValueError("refreshed seller identity differs from indexed listing")
            # Missing identity on either side remains unknown. This rejects a
            # known contradiction; it does not verify a seller or expand the
            # frozen provider quote contract with an unsupported seller claim.
            quality = self._quality_binding(db, card_id, offer, row)
            _, snapshot = buyship_partner._offer_snapshot(db, card_id=card_id, unit_id=row["unit_id"],
                source=row["source"], native_id=row["native_id"], country=destination["country"], now=core.utcnow())
            result = row["unit_id"], buyship_partner._digest(snapshot), quality
            if deadline is not None and time.monotonic() >= deadline:
                raise ValueError("indexed validation deadline expired")
            return result

    def preview(self, card_id, offer, destination):
        from . import buyship_partner, core
        if _quote_block_reason(offer):
            raise ValueError("current research does not establish an available, priced exact listing")
        expected = self._indexed_binding(card_id, offer, destination)

        def guard():
            if self._indexed_binding(card_id, offer, destination) != expected:
                raise ValueError("selected indexed offer or observation quality changed during quote")

        # The frozen quote gate reads an independent snapshot. Recheck the
        # selected research before each provider dispatch without holding a DB
        # read lock across network calls. Preserve its supported-client checks.
        client = self.client
        if isinstance(client, buyship_partner.FixturePartnerClient):
            base = buyship_partner.FixturePartnerClient
        elif isinstance(client, buyship_partner.PartnerClient):
            base = buyship_partner.PartnerClient
        else:
            raise ValueError("unsupported Buy&Ship client")

        class SelectionBoundClient(base):
            def __init__(self):
                # Requests and authentication stay on the original client, so
                # its explicit live authorization is never bypassed.
                self.sender = getattr(client, "sender", None)
                self.live_authorized = getattr(client, "live_authorized", False)

            def resolve(self, url):
                guard()
                return client.resolve(url)

            def quote(self, reference_id, variant_key, destination, currency=None):
                guard()
                return client.quote(reference_id, variant_key, destination, currency)

        with closing(core.connect(str(self.database), readonly=True)) as db:
            quote = buyship_partner.preview_quote(db, card_id=card_id, unit_id=expected[0],
                source=offer["source"], native_id=offer["native_id"], destination=destination,
                client=SelectionBoundClient())
        # Always bind the returned gate snapshot to the selected research too:
        # a transient change between its read and our dispatch guard must not
        # return a quote for a different observation or asking price.
        buyship_partner._require_preview_binding(quote)
        listing = quote.get("listing", {})
        if (quote.get("card_id") != card_id or quote.get("unit_id") != expected[0]
                or quote.get("evidence", {}).get("listing_snapshot_sha256") != expected[1]
                or any(listing.get(key) != offer[field] for key, field in (
                    ("source", "source"), ("native_id", "native_id"), ("url", "url"), ("title", "title")))
                or listing.get("ask") != {"currency": offer["currency"], "subunit_amount": offer["price_minor"]}):
            raise ValueError("provider quote differs from selected research")
        guard()
        return quote


class CommerceLoop:
    """Bounded in-memory research state, owned by the authenticated proxy caller.

    A restart discards selections. No user-provided URL is accepted by handoff;
    it re-fetches the URL retained from the selected server-owned research result.
    """
    def __init__(self, crawler, *, forwarders=None, psa_client=None, now=utcnow,
                 freshness_seconds=300, selection_seconds=600, monotonic=time.monotonic, catalog_lookup=None):
        if not 1 <= freshness_seconds <= 3600 or not 1 <= selection_seconds <= 3600:
            raise ValueError("invalid commerce state bounds")
        self.crawler, self.now = crawler, now
        if catalog_lookup is not None and not callable(catalog_lookup):
            raise ValueError("catalog lookup must be a server-owned dependency")
        self.catalog_lookup = catalog_lookup
        self.monotonic = monotonic
        self.mode = "synthetic_fixture" if getattr(crawler, "mode", None) == "synthetic_fixture" else "on_demand_research"
        self.forwarders = dict(forwarders or {})
        if psa_client is None:
            from .psa_cert import PSACertClient
            psa_client = PSACertClient()
        self.psa_client = psa_client
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
        result = {"schema": SCHEMA, "mode": self.mode, "checked_at": self.now(),
                  "purchasable": False, "purchase_action": None, "order_created": False}
        from .approved_sources import ApprovedSources
        if type(self.crawler) is ApprovedSources:
            from .source_readiness import source_readiness
            result["source_readiness"] = source_readiness(self.crawler)
        return result

    def _source_allowed(self, source, *, handoff=False):
        from .approved_sources import ApprovedSources
        if type(self.crawler) is ApprovedSources:
            try:
                self.crawler._guard()
                self.crawler._method(source)
                if handoff:
                    self.crawler.authorize_handoff(source)
            except ValueError as exc:
                raise CommerceError("source_access_unavailable", "This source is no longer approved for this action. Research again after access is restored.", 409) from exc

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

    def _target(self, card_id):
        if self.catalog_lookup is None:
            return None
        try:
            target = self.catalog_lookup(card_id)
            if (not isinstance(target, dict) or set(target) != {"card_id", *IDENTITY_FIELDS, "evidence_ref"}
                    or target["card_id"] != card_id or not isinstance(target["evidence_ref"], str)
                    or not target["evidence_ref"] or len(target["evidence_ref"]) > 2048
                    or target["evidence_ref"].strip() != target["evidence_ref"] or re.search(r"[\x00-\x1f\x7f]", target["evidence_ref"])
                    or any(value is not None and normalized(field, value) != value for field, value in target.items() if field in IDENTITY_FIELDS)):
                return None
            return copy.deepcopy(target)
        except Exception:
            # A missing, held, malformed or unavailable catalog never becomes
            # a target reconstructed from the request/query or a listing title.
            return None

    def _offer(self, raw, source, instant, target=None):
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
        raw_claim = company == "RAW"
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
        quantity = raw.get("listing_quantity")
        if quantity is not None and (type(quantity) is not int or not 1 <= quantity <= 99):
            raise ValueError("invalid listing quantity evidence")
        from .marketplace_quality import grade_details
        details = grade_details(company, grade, title=raw.get("title", ""),
            condition=metadata.get("seller_condition"), evidence=metadata.get("grade_evidence"),
            raw_claim=raw_claim or metadata.get("grade_kind") == "raw" or metadata.get("grade_evidence") == "structured_raw_claim",
            source_review=bool(raw.get("quality_review_required") or metadata.get("grade_review_required")))
        result = {"source": source, "native_id": _text(raw.get("native_id"), "listing ID", 128),
            "url": _url(raw.get("url"), source, self.mode == "synthetic_fixture"),
            "title": _text(raw.get("title"), "listing title", 2000), "price_minor": price,
            "currency": currency, "availability": availability, "observed_at": observed.isoformat(),
            "listing_status": listing_status,
            "fresh_until": (observed + timedelta(seconds=self.freshness_seconds)).isoformat(),
            "grade": details,
            "identity_status": "unverified_candidate", "scope": scope,
            "authenticity_verified": False,
            "seller_condition": metadata.get("seller_condition"),
            "source_status_text": raw.get("source_status_text"),
            "listing_quantity": quantity,
            "certificate_number_claim": raw.get("certificate_number_claim") or metadata.get("certificate_number_claim"),
            "evidence_ref": raw.get("evidence_ref"), "synthetic": self.mode == "synthetic_fixture"}
        from .approved_sources import ApprovedSources
        if type(self.crawler) is ApprovedSources:
            provenance = raw.get("source_provenance")
            if (not isinstance(provenance, dict) or set(provenance) != {"source", "method", "observed_at"}
                    or provenance["source"] != source or provenance["method"] not in {"api", "crawl"}
                    or _time(provenance["observed_at"]) != observed):
                raise ValueError("invalid approved source provenance")
            result["source_provenance"] = copy.deepcopy(provenance)
        for field in ("seller_condition", "source_status_text", "certificate_number_claim", "evidence_ref"):
            if result[field] is not None:
                result[field] = _text(result[field], field, 64 if field == "certificate_number_claim" else 2048)
        result["certificate"] = {"number_claim": result["certificate_number_claim"],
            "status": "not_checked" if result["certificate_number_claim"] else "number_missing",
            "physical_authenticity": "not_verified"}
        result["seller"] = seller_for_listing(raw, source, observed.isoformat())
        result["identity_evidence"] = identity_evidence(raw, source, result["url"], observed.isoformat(), target)
        if _time(result["identity_evidence"]["observed_at"]) < instant - timedelta(seconds=self.freshness_seconds):
            raise ValueError("producer returned stale identity evidence")
        result["card_id"] = target["card_id"] if target else None
        result["listing_photos"] = validate_photos(raw.get("listing_photos"), source, result["url"], observed.isoformat(),
            synthetic=self.mode == "synthetic_fixture") if scope == "listing" else []
        if raw.get("purchase_link") is not None:
            if self.mode == "synthetic_fixture":
                raise ValueError("synthetic fixtures cannot carry affiliate links")
            from .ebay_official import validate_purchase_link
            result["purchase_link"] = validate_purchase_link(raw["purchase_link"], source=source,
                native_id=result["native_id"], canonical_url=result["url"])
        if result["identity_evidence"]["status"] == "conflict":
            result["identity_status"] = "identity_conflict"
        elif result["identity_evidence"]["status"] == "exact_match":
            result["identity_status"] = "exact_match"
        return result

    def _url_quote_offer(self, card_id, offer):
        """Project comparison proof into the unchanged URL-only quote contract.

        A URL quote does not corroborate catalog identity. The actual retained
        offer and outer fingerprint retain the exact-card proof and photos.
        """
        proof = offer.get("identity_evidence") or {}
        if proof.get("status") == "conflict" or offer.get("identity_status") == "identity_conflict":
            raise ValueError("conflicting listing identity cannot reach quote provider")
        projected = copy.deepcopy(offer)
        if offer.get("identity_status") == "exact_match":
            target = self._target(card_id)
            if (not target or offer.get("card_id") != card_id or proof.get("target_card_id") != card_id
                    or proof.get("status") != "exact_match" or proof.get("basis") != "exact_listing_structured"
                    or proof.get("listing_url") != offer.get("url") or not proof.get("evidence_ref")
                    or proof.get("authenticity_verified") is not False or proof.get("missing_fields") != []
                    or proof.get("conflicting_fields") != [] or set(proof.get("matched_fields", [])) != set(IDENTITY_FIELDS)
                    or len(proof["matched_fields"]) != len(IDENTITY_FIELDS)
                    or proof.get("target") != {key: target[key] for key in (*IDENTITY_FIELDS, "evidence_ref")}
                    or any(target[field] is None or proof.get("claims", {}).get(field) != target[field] for field in IDENTITY_FIELDS)
                    or not _time(self.now()) - timedelta(seconds=self.freshness_seconds) <= _time(proof.get("observed_at")) <= _time(offer.get("observed_at")) <= _time(self.now())
                    or _time(offer.get("fresh_until")) <= _time(self.now())):
                raise ValueError("current server-backed comparison proof required")
            projected["identity_status"] = "unverified_candidate"
        elif proof.get("status") == "exact_match":
            raise ValueError("contradictory public identity status")
        for field in ("identity_evidence", "listing_photos", "card_id"):
            projected.pop(field, None)
        return projected

    def research(self, owner, request):
        from .marketplace_crawl import CrawlBlocked
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
        restricted_urls = getattr(self.crawler, "public_listing_urls", None)
        if restricted_urls is not None and any(url not in restricted_urls for url in urls):
            # The normal URL contract canonicalizes harmless variants. This
            # smaller capability must see and authorize the original literal.
            raise CommerceError("public_listing_url_not_authorized",
                                RESEARCH_MESSAGES["public_listing_url_not_authorized"], 403)
        validated = [_source_url(url, self.mode == "synthetic_fixture") for url in urls]
        if any(source not in sources for source, _ in validated):
            raise CommerceError("invalid_request", "Product URLs must belong to the chosen marketplaces.")
        result = self._base() | {"card_id": card_id, "platforms": [], "offers": [], "forwarders": self.capabilities()}
        from .marketplace_connections import marketplace_connections
        result["marketplace_connections"] = marketplace_connections(self.crawler)
        target = self._target(card_id)
        for source in sources:
            try:
                from .approved_sources import ApprovedSources
                chosen = [url for src, url in validated if src == source]
                response = self._produce(lambda: (
                    {"status": "researched", "listings": [(self.crawler.onboard_url(url) if type(self.crawler) is ApprovedSources else self.crawler.detail(url)) for url in chosen]}
                    if chosen else self.crawler.search(source, query, limit=3)))
                if not isinstance(response, dict) or not isinstance(response.get("listings", []), list) or len(response.get("listings", [])) > 20:
                    raise ValueError("invalid or oversized producer response")
                instant = _time(self.now())
                offers = _deduplicate_offers([self._offer(raw, source, instant, target)
                    for raw in response.get("listings", [])])
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
                reason = response.get("message")
                reason = reason if isinstance(reason, str) and reason in RESEARCH_MESSAGES else None
                message = ("Synthetic examples; no real marketplace was contacted." if self.mode == "synthetic_fixture"
                           else RESEARCH_MESSAGES.get(reason,
                               "Current page evidence was researched; card identity and seller claims remain unverified." if offers
                               else "No current listing evidence is available from this research route."))
                platform = {"source": source, "status": status, "message": message}
                if reason is not None:
                    platform["reason_code"] = reason
                if response.get("diagnostics") is not None:
                    # Never echo arbitrary producer diagnostics, URLs, raw
                    # errors, headers or credentials to the browser.
                    from .marketplace_browser import _diagnostics
                    try:
                        platform["diagnostics"] = copy.deepcopy(_diagnostics(response["diagnostics"]))
                    except ValueError:
                        pass
                result["platforms"].append(platform)
            except CommerceError as exc:
                if exc.status == 503:
                    raise
                result["platforms"].append({"source": source, "status": "unavailable", "message": "The research route returned unsupported listing evidence."})
            except CrawlBlocked as exc:
                reason = str(exc)
                restricted_reason = reason in {"public_listing_url_not_authorized", "public_listing_redirect_not_allowed",
                                              "public_read_window_expired", "public_read_clock_invalid",
                                              "public_request_budget_exhausted", "read_only_scope"}
                platform = {"source": source, "status": "unavailable", "message": (
                    RESEARCH_MESSAGES[reason] if restricted_reason
                    else "This marketplace could not be refreshed. Retry research later.")}
                if restricted_reason:
                    platform["reason_code"] = reason
                result["platforms"].append(platform)
            except Exception:
                result["platforms"].append({"source": source, "status": "unavailable", "message": "This marketplace could not be refreshed. Retry research later."})
        from .approved_sources import ApprovedSources
        if type(self.crawler) is ApprovedSources:
            from .source_readiness import source_readiness
            result["source_readiness"] = source_readiness(self.crawler)
        result["checked_at"] = self.now()
        result["coverage"] = research_coverage(result["offers"], search_used=any(not any(src == source for src, _ in validated) for source in sources))
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
            self._source_allowed(offer["source"])
            if record["card_id"] != request["card_id"] or any(request[key] != offer[field] for key, field in (
                    ("expected_observed_at", "observed_at"), ("expected_price_minor", "price_minor"), ("currency", "currency"))):
                raise CommerceError("offer_changed", "The selected listing differs from the displayed evidence. Research again.", 409)
            if offer["availability"] == "sold_out":
                raise CommerceError("offer_unavailable", "This listing is not available.", 409)
            if offer.get("identity_evidence", {}).get("status") == "conflict":
                raise CommerceError("identity_conflict", "The listing's identity claims conflict. Review another listing.", 409)
            if offer["grade"]["review_required"]:
                raise CommerceError("grade_review_required", "Review the listing's grading evidence before selecting it.", 409)
            if sum(row["owner"] == owner for row in self._selections.values()) >= 20:
                raise CommerceError("selection_capacity", "Too many active selections. Wait for an earlier selection to expire.", 429)
            if len(self._selections) >= MAX_OFFERS:
                raise CommerceError("selection_capacity", "Selection capacity is temporarily full.", 503)
            key = secrets.token_urlsafe(32)
            expires = instant + timedelta(seconds=self.selection_seconds)
            self._selections[key] = {"owner": owner, "card_id": record["card_id"], "offer": copy.deepcopy(offer),
                "fingerprint": _fingerprint(offer), "expires": expires, "busy": False}
        return self._base() | {"selection_id": key, "expires_at": expires.isoformat(), "offer": copy.deepcopy(offer)}

    def psa(self, owner, request):
        """Look up one certificate; seller claims never become authentication.

        Optional comparisons use only this owner's retained fresh offer. A
        browser cannot provide its own expected grade or identity assertions.
        """
        owner = self._owner(owner)
        _request(request, ("certificate_number",), ("offer_id",))
        certificate = _text(request["certificate_number"], "PSA certificate number", 32)
        expected, retained = None, None
        if "offer_id" in request:
            key = _text(request["offer_id"], "offer ID")
            with self._lock:
                self._purge(_time(self.now()))
                record = self._offers.get(key)
                if not record or record["owner"] != owner:
                    raise CommerceError("offer_unavailable", "Research this listing again before comparing its PSA claim.", 409)
                offer = record["offer"]
                claim = offer.get("certificate_number_claim")
                if claim and claim != certificate:
                    raise CommerceError("certificate_claim_changed", "The entered certificate differs from this listing's claim.", 409)
                grade = offer["grade"]
                if grade["company"] == "PSA" and grade["value"]:
                    expected = {"grade": grade["value"]}
                retained = copy.deepcopy(record)
        verification = self.psa_client.lookup(certificate, expected=expected)
        if retained is not None:
            # Provider latency must not make an expired or replaced offer look
            # like a current contextual comparison. Do not hold our state lock
            # across network I/O; validate the same owner/evidence afterward.
            with self._lock:
                self._purge(_time(self.now()))
                current = self._offers.get(key)
                if not current or current["owner"] != owner:
                    raise CommerceError("offer_unavailable", "Research this listing again before comparing its PSA claim.", 409)
                if current != retained:
                    raise CommerceError("offer_changed", "The listing evidence changed during PSA lookup. Research it again.", 409)
        return self._base() | {"verification": verification}

    def handoff(self, owner, request):
        # Reserve time for the proxy's 25s deadline. A slow marketplace refresh
        # consumes this budget too; it cannot start a late BNS worker afterward.
        deadline = self.monotonic() + HANDOFF_SECONDS
        owner = self._owner(owner)
        _request(request, ("selection_id", "forwarder", "destination"), ("variant_key",))
        forwarder = request["forwarder"]
        if not isinstance(forwarder, str) or forwarder not in {"buyship", "other"}:
            raise CommerceError("invalid_request", "Unsupported forwarder.")
        destination = request["destination"]
        if (not isinstance(destination, dict) or set(destination) - {"country", "state"}
                or not isinstance(destination.get("country"), str) or not re.fullmatch(r"[A-Z]{2}", destination["country"])
                or ("state" in destination and (not isinstance(destination["state"], str) or not re.fullmatch(r"[A-Za-z0-9 -]{1,32}", destination["state"])))):
            raise CommerceError("invalid_request", "Destination accepts a country code and optional state only.")
        key = _text(request["selection_id"], "selection ID")
        provider = self.forwarders.get(forwarder)
        url_preview = getattr(provider, "url_preview", False) is True
        variant = None
        with self._lock:
            self._purge(_time(self.now()))
            record = self._selections.get(key)
            if not record or record["owner"] != owner:
                raise CommerceError("selection_expired", "Select a freshly researched listing before handoff.", 409)
            if record["busy"]:
                raise CommerceError("selection_busy", "This selection is already being refreshed.", 409)
            if "variant_key" in request:
                variant_key = _text(request["variant_key"], "variant key", 300)
                choices = record.get("variant_choices")
                if (not url_preview or not choices or choices["expires"] <= _time(self.now())
                        or choices["destination"] != destination or choices["forwarder"] != forwarder):
                    raise CommerceError("variant_selection_required", "Request current variants for this selection and destination first.", 409)
                matches = [v for v in choices["variants"] if v["variant_key"] == variant_key and v["availability"] == "in_stock"]
                if len(matches) != 1:
                    raise CommerceError("variant_unavailable", "Choose an available variant from this selection's latest options.", 409)
                variant = copy.deepcopy(matches[0])
            # Choice data is single-attempt context, never a reusable quote or
            # a browser-supplied reference/price. A fresh resolve rechecks it.
            record.pop("variant_choices", None)
            record["busy"] = True
        try:
            try:
                raw = self._produce(lambda: self.crawler.detail(record["offer"]["url"]))
                refreshed = self._offer(raw, record["offer"]["source"], _time(self.now()), self._target(record["card_id"]))
            except Exception as exc:
                raise CommerceError("refresh_unavailable", "The selected product page could not be refreshed. No handoff was prepared.", 503) from exc
            with self._lock:
                if record["expires"] <= _time(self.now()):
                    self._selections.pop(key, None)
                    raise CommerceError("selection_expired", "This selection expired during refresh. Select again.", 409)
                if (refreshed["availability"] == "sold_out" or refreshed.get("identity_evidence", {}).get("status") == "conflict"
                        or _fingerprint(refreshed) != record["fingerprint"]):
                    self._selections.pop(key, None)
                    raise CommerceError("offer_changed", "The product URL, price, availability or seller evidence changed. Research and select again.", 409)
            result = self._base() | {"status": "manual_handoff_required", "selection_id": key,
                "product_url": refreshed["url"], "offer": refreshed,
                "forwarder": {"id": forwarder, "label": "Buy & Ship" if forwarder == "buyship" else "Other forwarder"},
                "destination": dict(destination), "quote": None, "quote_status": "provider_unconfigured",
                "message": "Copy this product URL into your forwarder. A live shipping quote is unavailable."}
            blocked_quote = None if url_preview else _quote_block_reason(refreshed)
            if blocked_quote:
                result.update(quote_status=blocked_quote,
                    message=("The URL is ready for manual handoff. Current stock is unconfirmed, so no provider quote was requested."
                             if blocked_quote == "stock_not_confirmed" else
                             "The URL is ready for manual handoff. A priced, exact listing is not established, so no provider quote was requested."))
            elif provider is not None:
                try:
                    self._source_allowed(refreshed["source"], handoff=True)
                    if url_preview:
                        quote_offer = self._url_quote_offer(record["card_id"], refreshed)
                        quote = provider.preview_before(record["card_id"], quote_offer, dict(destination), deadline=deadline, variant=variant)
                    elif callable(getattr(provider, "preview_before", None)):
                        quote = provider.preview_before(record["card_id"], refreshed, dict(destination), deadline=deadline)
                    else:
                        quote = provider.preview(record["card_id"], refreshed, dict(destination))
                    self._source_allowed(refreshed["source"], handoff=True)
                    if not isinstance(quote, dict) or quote.get("status") != "quote_ready_for_review" or quote.get("purchasable") is not False or quote.get("order_created") is not False or quote.get("purchase_action") is not None:
                        raise ValueError("provider did not return a non-purchasable quote preview")
                    result.update(status="quote_ready_for_review", quote=quote, quote_status="ready",
                                  message="Review the provider's current landed quote. No order was created.")
                except CommerceError:
                    raise
                except Exception as exc:
                    from .bns_errors import BNSRefusal, validate_refusal
                    if isinstance(exc, BNSRefusal):
                        details = validate_refusal(exc.result)
                        result.update(status=("variant_selection_required" if details["status"] == "variant_selection_required"
                                              else "manual_handoff_required"), provider_result=details,
                                      quote_status=details["code"], message=details["message"])
                    else:
                        result.update(quote_status="eligible_indexed_quote_unavailable",
                            message="The refreshed URL is ready for manual handoff. An eligible indexed provider quote is unavailable.")
            if provider is not None and not blocked_quote:
                self._source_allowed(refreshed["source"], handoff=True)
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
            if result["quote"] is not None:
                try:
                    expires_at = _time(result["quote"]["buyship"]["expires_at"])
                    if expires_at <= completed:
                        raise ValueError("provider quote expired before handoff completed")
                except (KeyError, TypeError, ValueError):
                    result.update(status="manual_handoff_required", quote=None,
                        quote_status="eligible_indexed_quote_unavailable",
                        message="The refreshed URL is ready for manual handoff. A current provider quote is unavailable.")
            variants = result.get("provider_result", {}).get("details", {}).get("variants")
            if url_preview and variants:
                with self._lock:
                    record["variant_choices"] = {"variants": copy.deepcopy(variants), "destination": dict(destination),
                        "forwarder": forwarder, "expires": min(record["expires"], completed + timedelta(seconds=300))}
            result["checked_at"] = completed_at
            if self.mode == "synthetic_fixture":
                result["message"] = "Synthetic demonstration only. This example URL cannot be purchased or sent to a real forwarder."
            return result
        finally:
            with self._lock:
                record["busy"] = False

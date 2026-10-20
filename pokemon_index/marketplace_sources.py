"""Offline adapters for saved marketplace captures; no transport or credentials.

Mercari and SNKRDUNK schemas below are project-owned authorized-export contracts,
not claims about either marketplace's native API. eBay tags select saved Browse
response shapes. None of these adapters grants collection or display rights.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
from typing import Any
import unicodedata
from urllib.parse import urlsplit

from . import core, ebay_browse
from .languages import normalize_language
from .marketplace_quality import contradicts_grade

CAPTURE_SCHEMA = "pokemon.marketplace-capture.v1"
EXPORT_SCHEMAS = {"mercari": "pokemon.mercari-authorized-export.v1",
                  "snkrdunk": "pokemon.snkrdunk-authorized-export.v1"}
EBAY_SCHEMAS = {"ebay.browse.search.v1", "ebay.browse.item.v1"}
DOMAINS = {"mercari": {"jp.mercari.com"}, "snkrdunk": {"snkrdunk.com", "www.snkrdunk.com"},
           "ebay_us": {"ebay.com", "www.ebay.com"}}
GRADERS = {"PSA", "BGS", "CGC", "ARS", "PGC"}
VERIFICATION_FIELDS = {"certificate_verified", "authenticity_verified",
                       "physical_inspection_performed", "physical_condition_assessed"}
REQUEST_FIELDS = {"kind", "query", "page", "native_ids", "product_ids", "target_card_ids"}
MAX_BATCH = 100


def _text(value: Any, field: str, maximum: int, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"invalid {field}")
    return value.strip()


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("capture must contain JSON data only") from exc
    if len(encoded) > 2_000_000:
        raise ValueError("capture exceeds offline size bound")
    return hashlib.sha256(encoded).hexdigest()


def _observed_at(value: Any) -> str:
    value = _text(value, "observed_at", 64)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be an explicit UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("observed_at must be an explicit UTC timestamp")
    return parsed.isoformat()


def _request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - REQUEST_FIELDS:
        raise ValueError("capture request accepts discovery coordinates only")
    if not isinstance(value.get("kind"), str) or value["kind"] not in {"search", "detail", "export"}:
        raise ValueError("capture request requires search, detail or export kind")
    result = copy.deepcopy(value)
    for field, item in result.items():
        if field in {"kind", "query"}:
            _text(item, field, 512)
            strings = [item]
        elif field == "page":
            if type(item) is not int or not 1 <= item <= 10000:
                raise ValueError("capture page must be a positive bounded integer")
            strings = []
        else:
            if not isinstance(item, list) or not 1 <= len(item) <= MAX_BATCH:
                raise ValueError(f"invalid capture {field}")
            strings = [_text(text, field, 256) for text in item]
            if len(set(strings)) != len(strings):
                raise ValueError(f"duplicate capture {field}")
        if any(re.search(r"[a-z][a-z0-9+.-]*://", text, re.I) for text in strings):
            raise ValueError("capture request cannot contain arbitrary URLs")
    return result


def _url(value: Any, source: str, fixture: bool) -> str:
    value = _text(value, "listing URL", 2048)
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValueError("listing URL contains unescaped whitespace or controls")
    try:
        parsed = urlsplit(value)
        allowed = ((parsed.hostname or "").endswith(".invalid") if fixture
                   else parsed.hostname in DOMAINS[source])
        invalid = (parsed.scheme != "https" or not allowed or parsed.username or parsed.password
                   or parsed.port not in {None, 443} or parsed.fragment or parsed.path in {"", "/"})
    except ValueError as exc:
        raise ValueError("invalid canonical marketplace URL") from exc
    if invalid:
        raise ValueError("listing URL must use the canonical marketplace domain; fixtures require .invalid")
    return value


def _currency(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z]{3}", value):
        raise ValueError("currency must be three uppercase letters")
    return value


def _minor(value: Any) -> int:
    if type(value) is not int or not 0 <= value < 2**63:
        raise ValueError("native amount_minor must be a nonnegative 63-bit integer")
    return value


def _language(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 32 or normalize_language(value) != value:
        raise ValueError("language must be a canonical lowercase language tag")
    return value


def _quality(item: dict[str, Any], title: str, evidence: str,
             *, supplied: dict[str, Any] | None = None) -> tuple[dict[str, Any], bool]:
    for field in VERIFICATION_FIELDS:
        if field in item and item[field] is not False:
            raise ValueError("captures cannot assert certificate or physical verification")
    fields = supplied or item
    seller_condition = _text(fields.get("seller_condition"), "seller_condition", 512, nullable=True)
    company = fields.get("grade_company")
    grade = fields.get("grade_value")
    if company is not None and not isinstance(company, str):
        raise ValueError("invalid structured seller grade company")
    if company == "RAW":
        if grade is not None and grade != "raw":
            raise ValueError("raw seller claim cannot have a grader score")
        raw_claim, company, grade = True, None, None
    else:
        raw_claim = False
        if (company is None) != (grade is None):
            raise ValueError("structured grade needs company and value together")
        if company is not None and (company not in GRADERS or not isinstance(grade, str)
                                   or not re.fullmatch(r"10|[1-9](?:\.5)?", grade)):
            raise ValueError("unsupported structured seller grade")
    certificate = _text(fields.get("certificate_number_claim"), "certificate_number_claim", 64, nullable=True)
    if raw_claim and certificate:
        raise ValueError("structured raw claim contradicts a certificate claim")
    normalized = unicodedata.normalize("NFKC", title)
    title_grades = {(match.group(1).upper(), match.group(2)) for match in core.GRADE_RE.finditer(normalized)}
    if len(list(core.GRADE_RE.finditer(normalized))) > 1:
        raise ValueError("ambiguous multiple title grade claims")
    unsafe = bool(core.GRADE_UNSAFE_RE.search(normalized))
    if company and (unsafe or (title_grades and title_grades != {(company, grade)})):
        raise ValueError("structured grade contradicts title grade claim")
    if raw_claim and (title_grades or core.GRADER_RE.search(normalized) or core.SLAB_EVIDENCE_RE.search(normalized)):
        raise ValueError("structured raw claim contradicts slab title")
    basis = "structured_seller_claim" if company else "no_grade_claim"
    if company is None and title_grades and not unsafe:
        company, grade = next(iter(title_grades))
        basis = "seller_title_claim"
    needs_review = unsafe or bool(company and not (
        title_grades == {(company, grade)} and core.SLAB_EVIDENCE_RE.search(normalized)))
    if certificate and not company:
        needs_review = True
    if seller_condition:
        if contradicts_grade(seller_condition, company or "RAW", grade or "raw"):
            needs_review = True
    return {"seller_condition": seller_condition, "grade_company": company, "grade_value": grade,
            "grade_evidence": basis, "certificate_number_claim": certificate,
            "evidence_ref": evidence, "certificate_verified": False, "authenticity_verified": False,
            "physical_inspection_performed": False}, needs_review


def _export_item(item: Any, source: str, source_id: str, stamp: str, fixture: bool) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("authorized export listing must be an object")
    if item.get("record_type", "listing") != "listing" or any(
            key in item for key in ("minimum_price", "lowest_price", "tier_price", "price_range")):
        raise ValueError("product/tier summaries are not stable listing observations")
    if item.get("sale_type", "fixed_price") != "fixed_price" or item.get("auction"):
        raise ValueError("auction/bid rows cannot become fixed-price asks")
    if any(field in item for field in ("paid_minor", "paid_price", "settled_at", "sale_price")):
        raise ValueError("paid-price rows require separate verified settlement evidence")
    native = _text(item.get("listing_id"), "stable listing_id", 128)
    if not re.fullmatch(r"m[0-9]+" if source == "mercari" else r"[A-Za-z0-9][A-Za-z0-9_:-]{0,127}", native):
        raise ValueError("invalid stable listing_id")
    title = _text(item.get("title"), "listing title", 2000)
    url = _url(item.get("url"), source, fixture)
    if source == "mercari" and not fixture and urlsplit(url).path.rstrip("/") != "/item/" + native:
        raise ValueError("Mercari URL differs from stable listing_id")
    status = item.get("status")
    if not isinstance(status, str) or status not in core.STATUSES:
        raise ValueError("invalid exported listing status")
    price = item.get("price")
    if price is None:
        if status == "on_sale":
            raise ValueError("on-sale export requires an explicit native price")
        amount, currency = None, _currency(item.get("currency"))
    else:
        if not isinstance(price, dict) or set(price) != {"amount_minor", "currency"}:
            raise ValueError("export price requires explicit amount_minor and currency")
        amount, currency = _minor(price["amount_minor"]), _currency(price["currency"])
        if "currency" in item and item["currency"] != currency:
            raise ValueError("exported price has conflicting currencies")
    evidence = f"marketplace-capture:{source}:sha256:{_digest(item)}"
    quality, needs_review = _quality(item, title, evidence)
    quality["fixture"] = fixture
    row = {"source": source_id, "native_id": native, "title": title, "url": url,
           "seller_native_id": _text(item.get("seller_id"), "seller_id", 128, nullable=True),
           "observed_at": stamp, "status": status, "price_minor": amount, "currency": currency,
           "evidence_ref": evidence, "poll_reason": "discovery", "marketplace_quality": quality}
    language = _language(item.get("language"))
    if language:
        row["language"] = language
    if needs_review:
        row["resolution_gate"] = "photo_required"
    return row


def _ebay_claims(item: dict[str, Any]) -> dict[str, Any]:
    fields = {"seller_condition": item.get("condition"), "grade_company": None,
              "grade_value": None, "certificate_number_claim": None}
    aspects = []
    localized, descriptors = item.get("localizedAspects", []), item.get("conditionDescriptors", [])
    if (not isinstance(localized, list) or not isinstance(descriptors, list)
            or len(localized) > 100 or len(descriptors) > 100):
        raise ValueError("invalid bounded eBay seller aspects")
    for aspect in localized:
        if not isinstance(aspect, dict):
            raise ValueError("invalid eBay localizedAspects")
        aspects.append((aspect.get("name"), aspect.get("value")))
    for descriptor in descriptors:
        if (not isinstance(descriptor, dict) or not isinstance(descriptor.get("values"), list)
                or len(descriptor["values"]) > 100):
            raise ValueError("invalid eBay condition descriptor")
        for value in descriptor["values"]:
            if not isinstance(value, dict):
                raise ValueError("invalid eBay condition descriptor value")
            aspects.append((descriptor.get("name"), value.get("content")))
    labels = {"professional grader": "grade_company", "grade": "grade_value",
              "certification number": "certificate_number_claim", "certification #": "certificate_number_claim"}
    for name, value in aspects:
        if not isinstance(name, str) or name.casefold() not in labels:
            continue
        field = labels[name.casefold()]
        value = _text(value, "eBay seller aspect", 128)
        if field == "grade_company":
            # Only explicit grader names/abbreviations, never "certified" alone.
            aliases = {"Professional Sports Authenticator (PSA)": "PSA", "Beckett Grading Services (BGS)": "BGS",
                       "Certified Guaranty Company (CGC)": "CGC"}
            value = aliases.get(value, value)
        if fields[field] is not None and fields[field] != value:
            raise ValueError("conflicting eBay seller grade aspects")
        fields[field] = value
    return fields


def _ebay_item(item: Any, source_id: str, stamp: str, fixture: bool) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("eBay captured item must be an object")
    options = item.get("buyingOptions")
    if not isinstance(options, list) or "FIXED_PRICE" not in options or "AUCTION" in options:
        raise ValueError("only fixed-price eBay listings are supported; auctions are excluded")
    if item.get("itemGroupType") or "priceRange" in item:
        raise ValueError("eBay product/variation summaries are not exact listing rows")
    if "estimatedAvailabilities" in item:
        availability = item["estimatedAvailabilities"]
        if not isinstance(availability, list) or not 1 <= len(availability) <= 10:
            raise ValueError("unsupported eBay availability evidence")
        for estimate in availability:
            if not isinstance(estimate, dict) or estimate.get("estimatedAvailabilityStatus") not in {
                    "IN_STOCK", "LIMITED_STOCK"}:
                raise ValueError("unavailable or unknown eBay stock cannot become a fresh ask")
            if "estimatedAvailableQuantity" in estimate and (
                    type(estimate["estimatedAvailableQuantity"]) is not int
                    or estimate["estimatedAvailableQuantity"] <= 0):
                raise ValueError("unavailable or unknown eBay quantity cannot become a fresh ask")
    _text(item.get("title"), "eBay title", 2000)
    price = item.get("price")
    if not isinstance(price, dict) or price.get("currency") != "USD":
        raise ValueError("eBay US captured prices require USD")
    value = price.get("value")
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r"\d+(?:\.\d+)?", str(value)) or len(str(value)) > 64:
        raise ValueError("eBay price must be exact decimal text or an integer")
    with localcontext() as context:
        context.prec = 80
        try:
            amount = Decimal(str(value)) * 100
        except InvalidOperation as exc:
            raise ValueError("invalid eBay decimal price") from exc
    if amount != amount.to_integral_value():
        raise ValueError("eBay USD price has unsupported precision")
    cents = _minor(int(amount))
    url = _url(item.get("itemWebUrl"), "ebay_us", fixture)
    native = item.get("itemId")
    if not isinstance(native, str) or not ebay_browse.ITEM_ID.fullmatch(native):
        raise ValueError("eBay stable item ID is invalid")
    legacy_id = native.split("|")[1]
    path = urlsplit(url).path.rstrip("/")
    if not path.startswith("/itm/") or path.rsplit("/", 1)[-1] != legacy_id:
        raise ValueError("eBay URL differs from stable listing ID")
    structural = copy.deepcopy(item)
    # The existing native normalizer requires an eBay host. This fixture-only
    # shim exercises its structural checks, then retains the original .invalid
    # URL. It performs no request and claims no real eBay item exists.
    if fixture:
        structural["itemWebUrl"] = "https://www.ebay.com/itm/synthetic-fixture"
    row = ebay_browse.normalize_item(structural, stamp)
    row["seller_native_id"] = _text(row["seller_native_id"], "eBay seller username", 128, nullable=True)
    evidence = f"marketplace-capture:ebay_us:sha256:{_digest(item)}"
    quality, _ = _quality(item, row["title"], evidence, supplied=_ebay_claims(item))
    quality["fixture"] = fixture
    row.update(source=source_id, url=url, price_minor=cents, evidence_ref=evidence,
               marketplace_quality=quality)
    language = _language(item.get("language"))
    if language:
        row["language"] = language
    return row


def normalize_capture(capture: dict[str, Any]) -> dict[str, Any]:
    """Normalize one bounded saved capture without fetching, importing or granting rights."""
    if not isinstance(capture, dict) or set(capture) != {
            "schema", "source", "observed_at", "request", "payload_schema", "payload"}:
        raise ValueError("capture requires the explicit marketplace-capture envelope")
    if capture["schema"] != CAPTURE_SCHEMA:
        raise ValueError("unsupported marketplace capture schema")
    _digest(capture)
    source_id = capture["source"]
    if not isinstance(source_id, str):
        raise ValueError("unsupported marketplace source")
    fixture = source_id.endswith("_fixture")
    source = source_id.removesuffix("_fixture") if fixture else source_id
    if source not in DOMAINS:
        raise ValueError("unsupported marketplace source")
    stamp, request = _observed_at(capture["observed_at"]), _request(capture["request"])
    payload, schema = capture["payload"], capture["payload_schema"]
    if not isinstance(schema, str):
        raise ValueError("payload_schema must identify an explicit supported schema")
    if not isinstance(payload, dict):
        raise ValueError("marketplace payload must be an object")
    next_cursor, page_complete = None, False
    if source in EXPORT_SCHEMAS:
        if schema != EXPORT_SCHEMAS[source]:
            raise ValueError("unsupported authorized-export schema")
        items = payload.get("listings")
        next_cursor, page_complete = payload.get("next_cursor"), payload.get("page_complete", False)
        adapter = lambda item: _export_item(item, source, source_id, stamp, fixture)
        scope = "authorized_export_listing_batch"
    else:
        if schema not in EBAY_SCHEMAS:
            raise ValueError("unsupported saved eBay Browse schema")
        if schema == "ebay.browse.search.v1":
            items = payload.get("itemSummaries", [] if payload.get("total") == 0 else None)
            total = payload.get("total")
            if total is not None and (type(total) is not int or total < 0):
                raise ValueError("eBay total must be a nonnegative integer")
            next_cursor = payload.get("next")
            page_complete = (next_cursor is None and isinstance(items, list)
                             and total is not None and total <= len(items))
            scope = "captured_browse_search_page"
        else:
            items = [payload]
            scope, page_complete = "captured_browse_item_detail", True
        adapter = lambda item: _ebay_item(item, source_id, stamp, fixture)
    if not isinstance(items, list) or len(items) > MAX_BATCH:
        raise ValueError("capture requires a bounded listing batch of at most 100 rows")
    if next_cursor is not None:
        next_cursor = _text(next_cursor, "next_cursor", 2048)
    if type(page_complete) is not bool:
        raise ValueError("page_complete must be an explicit boolean")
    observations = [adapter(item) for item in items]
    if len({row["native_id"] for row in observations}) != len(observations):
        raise ValueError("capture repeats a stable listing ID")
    return {"source": source_id, "observed_at": stamp, "request": request,
            "observations": observations,
            "coverage": {"scope": scope, "returned_count": len(observations),
                         "next_cursor": next_cursor, "page_complete": page_complete,
                         "nonappearance_is_not_sold": True, "fixture": fixture,
                         "live_collection_verified": False}}

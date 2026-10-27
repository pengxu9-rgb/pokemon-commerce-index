"""Listing-bound seller claims, without invented trust scores or network access.

Public extraction may omit malformed fields. The normalized commerce contract
is strict, so untrusted links/metrics cannot leak through a custom producer.
Seller observations never establish card authenticity or platform guarantees.
"""
from __future__ import annotations

from datetime import datetime
import copy
from decimal import Decimal, InvalidOperation
import math
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

MAX_INTEGER = 2**53 - 1
SELLER_KEYS = {"id", "display_name", "url", "evidence_ref", "observed_at", "reputation"}
REPUTATION_KEYS = {"rating", "review_count", "positive_feedback_percent", "feedback_score",
                   "evidence_ref", "observed_at"}
PROFILE_HOSTS = {"mercari": {"jp.mercari.com"}, "ebay_us": {"ebay.com", "www.ebay.com"},
                 "snkrdunk": {"snkrdunk.com", "www.snkrdunk.com"}}
PROFILE_PATHS = {"mercari": r"/user/profile/[A-Za-z0-9_-]+/?",
                 "ebay_us": r"/(?:usr|str)/[A-Za-z0-9_][A-Za-z0-9_.-]*/?",
                 "snkrdunk": r"/users/[A-Za-z0-9_-]+/?"}
ORIGINS = {"mercari": "https://jp.mercari.com", "ebay_us": "https://www.ebay.com",
           "snkrdunk": "https://snkrdunk.com"}
PLATFORM_NAMES = {"mercari": {"mercari", "メルカリ"}, "ebay_us": {"ebay"},
                  "snkrdunk": {"snkrdunk", "スニダン"}}


def _text(value, maximum):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and value == value.strip()
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _stamp(value):
    if (not _text(value, 40) or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})", value) is None):
        raise ValueError("invalid seller evidence timestamp")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("seller evidence timestamp needs a timezone")
    return stamp


def profile_url(value, source):
    if not _text(value, 2048):
        return False
    try:
        p = urlsplit(value)
        return (p.scheme == "https" and p.hostname in PROFILE_HOSTS.get(source, ())
                and not p.username and not p.password and p.port in (None, 443)
                and not p.query and not p.fragment
                and re.fullmatch(PROFILE_PATHS.get(source, r"(?!)"), p.path) is not None)
    except ValueError:
        return False


def _number(value, minimum=0, maximum=MAX_INTEGER):
    return type(value) in (int, float) and minimum <= value <= maximum and math.isfinite(value)


def _platform_only(source, identifier, name, url):
    return url is None and any(isinstance(v, str)
        and unicodedata.normalize("NFKC", v).casefold() in PLATFORM_NAMES.get(source, ())
        for v in (identifier, name))


def validate_seller(value, source, listing_observed_at):
    """Validate a normalized seller DTO; unknown is null, never a made-up zero."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != SELLER_KEYS:
        raise ValueError("invalid seller evidence fields")
    if (value["id"] is not None and not _text(value["id"], 128)
            or value["display_name"] is not None and not _text(value["display_name"], 160)
            or value["url"] is not None and not profile_url(value["url"], source)
            or not any(value[k] is not None for k in ("id", "display_name", "url"))
            or _platform_only(source, value["id"], value["display_name"], value["url"])
            or not _text(value["evidence_ref"], 2048)
            or _stamp(value["observed_at"]) > _stamp(listing_observed_at)):
        raise ValueError("invalid seller identity or provenance")
    rep = value["reputation"]
    if rep is not None:
        if (not isinstance(rep, dict) or set(rep) != REPUTATION_KEYS
                or not _text(rep["evidence_ref"], 2048)
                or _stamp(rep["observed_at"]) > _stamp(value["observed_at"])):
            raise ValueError("invalid seller reputation provenance")
        rating = rep["rating"]
        if rating is not None and (not isinstance(rating, dict) or set(rating) != {"value", "scale"}
                or not _number(rating["scale"], 0, 1000) or rating["scale"] <= 0
                or not _number(rating["value"], 0, rating["scale"])):
            raise ValueError("invalid seller rating scale")
        for key in ("review_count", "feedback_score"):
            if rep[key] is not None and (type(rep[key]) is not int or not 0 <= rep[key] <= MAX_INTEGER):
                raise ValueError("invalid seller reputation count")
        if rep["positive_feedback_percent"] is not None and not _number(rep["positive_feedback_percent"], 0, 100):
            raise ValueError("invalid seller feedback percentage")
        if not any(rep[k] is not None for k in ("rating", "review_count", "positive_feedback_percent", "feedback_score")):
            raise ValueError("empty seller reputation is unknown")
    return value


def seller_identity(value):
    """Stable selection identity, excluding changing capture times and metrics."""
    return None if value is None else {key: value[key] for key in ("id", "display_name", "url")}


def _decimal(value):
    if type(value) not in (str, int, float) or isinstance(value, str) and len(value) > 64:
        return None
    try:
        number = Decimal(str(value))
        return float(number) if number.is_finite() and 0 <= number <= MAX_INTEGER else None
    except InvalidOperation:
        return None


def _count(value):
    if type(value) not in (str, int, float) or isinstance(value, str) and len(value) > 64:
        return None
    try:
        number = Decimal(str(value))
        return int(number) if (number.is_finite() and 0 <= number <= MAX_INTEGER
            and number == number.to_integral_value()) else None
    except InvalidOperation:
        return None


def extracted_seller(value, source, evidence_ref, observed_at):
    """Read only a caller's exact-listing seller object, never a page-wide graph.

    Supports JSON-LD seller fields and explicit eBay seller feedback fields.
    Missing bestRating does not imply a five-star scale. Unknown fields stay
    absent; a review count of zero is preserved only when explicitly supplied.
    """
    if not isinstance(value, dict) or not _text(evidence_ref, 2048):
        return None
    identifier = value.get("identifier", value.get("id", value.get("username")))
    if isinstance(identifier, dict):
        identifier = identifier.get("value")
    if type(identifier) is int and 0 <= identifier <= MAX_INTEGER:
        identifier = str(identifier)
    identifier = identifier.strip() if isinstance(identifier, str) else identifier
    identifier = identifier if _text(identifier, 128) else None
    name = value.get("name", value.get("display_name"))
    name = name.strip() if isinstance(name, str) else name
    name = name if _text(name, 160) else None
    url = value.get("url")
    if isinstance(url, str) and url.startswith("/") and not url.startswith("//"):
        url = urljoin(ORIGINS.get(source, ""), url)
    url = url if profile_url(url, source) else None
    # Generic marketplace merchant metadata is not an individual seller. An
    # actual reported user/store profile is needed to disambiguate a seller
    # using the platform's own name or identifier.
    if _platform_only(source, identifier, name, url):
        return None
    if not any(v is not None for v in (identifier, name, url)):
        return None
    aggregate = value.get("aggregateRating")
    aggregate = aggregate if isinstance(aggregate, dict) else {}
    rating_value, scale = _decimal(aggregate.get("ratingValue")), _decimal(aggregate.get("bestRating"))
    rating = {"value": rating_value, "scale": scale} if (
        rating_value is not None and scale is not None and 0 < scale <= 1000 and rating_value <= scale) else None
    review_count = _count(aggregate.get("reviewCount"))
    percent = _decimal(value.get("feedbackPercentage")) if source == "ebay_us" else None
    percent = percent if percent is not None and percent <= 100 else None
    score = _count(value.get("feedbackScore")) if source == "ebay_us" else None
    reputation = {"rating": rating, "review_count": review_count,
        "positive_feedback_percent": percent, "feedback_score": score,
        "evidence_ref": evidence_ref, "observed_at": observed_at}
    if all(reputation[k] is None for k in ("rating", "review_count", "positive_feedback_percent", "feedback_score")):
        reputation = None
    result = {"id": identifier, "display_name": name, "url": url,
        "evidence_ref": evidence_ref, "observed_at": observed_at, "reputation": reputation}
    return validate_seller(result, source, observed_at)


def seller_for_listing(raw, source, observed_at):
    """Carry normalized public claims or existing explicit export seller fields."""
    if raw.get("scope", "listing") != "listing":
        return None
    if "seller" in raw:
        return copy.deepcopy(validate_seller(raw["seller"], source, observed_at))
    legacy = {"id": raw.get("seller_native_id"), "name": raw.get("seller_name"), "url": raw.get("seller_url")}
    return extracted_seller(legacy, source, raw.get("evidence_ref"), observed_at)

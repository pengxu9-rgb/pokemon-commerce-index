"""Offline listing/photo completeness; no fetch, approval, order or payment.

Consumes retained normalized CommerceLoop observations. Counts describe supplied
evidence, never market-wide coverage or physical authenticity. Complete equal
identity/grade/condition claims may form *claimed* product-price groups; they
do not become approved card matches. An absent inventory is unknown, not zero.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .listing_evidence import FIELDS, normalized, validate_photos
from .marketplace_crawl import canonical_product_url
from .seller_evidence import validate_seller
from .coverage_snapshot import strict_json

SCHEMA = "pokemon.offer-photo-coverage.v1"
METRICS = ("distinct_listings", "current_active_listings", "unique_sellers",
           "listings_with_price", "listings_with_grade_claim", "listings_with_reviewed_comparison_grade", "certificate_claims_present",
           "bound_photo_reference_listings", "authorized_copy_photo_listings",
           "front_back_photo_listings", "claimed_product_price_groups",
           "comparable_product_price_groups",
           "multi_seller_claim_groups", "photo_supported_multi_seller_claim_groups",
           "front_back_supported_multi_seller_claim_groups", "listings_needing_review")
PHOTO_METRICS = {"authorized_copy_photo_listings", "front_back_photo_listings",
                 "photo_supported_multi_seller_claim_groups", "front_back_supported_multi_seller_claim_groups"}
SOURCES = {"mercari", "ebay_us", "snkrdunk"}
# A deliberately narrow rollout set, grounded in the existing reviewed 9/10
# PSA flows. This is not a taxonomy of every grader's valid grade scale.
# Other company/grade pairs remain reported claims requiring review.
REVIEWED_COMPARISON_GRADE_PAIRS = {("PSA", "9"), ("PSA", "10")}
PHOTO_AUDIT_FIELDS = {"source", "native_id", "listing_url", "offer_observed_at", "photo_url",
                      "evidence_ref", "observed_at", "sha256", "rights_reference", "expires_at",
                      "view", "depiction", "authorized"}


def _time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("timezone-aware observation time required")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone-aware observation time required")
    return result.astimezone(timezone.utc)


def _text(value, length=2048):
    return (isinstance(value, str) and 0 < len(value) <= length and value == value.strip()
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _native(source, identifier, url):
    platform, url_id, canonical = canonical_product_url(url)
    if platform != source or canonical != url:
        return False
    if source == "ebay_us" and re.fullmatch(r"v1\|[0-9]{8,20}\|0", identifier):
        identifier = identifier.split("|")[1]
    return identifier == url_id


def _identity(offer):
    proof = offer.get("identity_evidence")
    if (not isinstance(proof, dict) or proof.get("conflicting_fields") or proof.get("status") not in {"candidate", "exact_match"}
            or proof.get("basis") != "exact_listing_structured" or proof.get("authenticity_verified") is not False):
        return None
    claims = proof.get("claims")
    if (not isinstance(claims, dict) or set(claims) != set(FIELDS)
            or proof.get("listing_url") != offer["url"] or not _text(proof.get("evidence_ref"))
            or proof.get("evidence_ref") != offer.get("evidence_ref")
            or _time(proof.get("observed_at")) != _time(offer["observed_at"])):
        return None
    if any(claims[k] is None or normalized(k, claims[k]) != claims[k] for k in FIELDS):
        return None
    return tuple(claims[k] for k in FIELDS)


def _grade(offer):
    value = offer.get("grade")
    if not isinstance(value, dict) or value.get("review_required") is not False or value.get("certificate_verified") is not False:
        return None
    if value.get("special_label") is not None:
        return None  # retain for manual review; black/pristine labels cannot collapse
    if value.get("kind") == "slab":
        company, grade = value.get("company"), value.get("value")
        if not isinstance(company, str) or not isinstance(grade, str) or (company, grade) not in REVIEWED_COMPARISON_GRADE_PAIRS:
            return None
        return "slab", company, grade
    if value.get("kind") == "raw" and value.get("company") is None and value.get("value") is None:
        return "raw", None, None
    return None


def _grade_claim_present(offer):
    value = offer.get("grade")
    if not isinstance(value, dict):
        return False
    return (value.get("kind") == "raw" or value.get("kind") == "slab"
            and _text(value.get("company"), 80) and _text(value.get("value"), 80))


def _seller(offer):
    seller = validate_seller(offer.get("seller"), offer["source"], offer["observed_at"])
    if seller is None:
        return None
    if (seller.get("evidence_ref") != offer.get("evidence_ref")
            or _time(seller.get("observed_at")) != _time(offer["observed_at"])):
        return None
    # Keep this denominator conservative. Mixing native IDs, display names and
    # profile-only aliases can count one seller twice without an alias authority.
    stable = seller.get("id")
    return (offer["source"], stable) if stable else None


def _price(offer):
    return (type(offer.get("price_minor")) is int and 0 <= offer["price_minor"] <= 2**53 - 1
            and isinstance(offer.get("currency"), str) and bool(re.fullmatch(r"[A-Z]{3}", offer["currency"])))


def _photo_counts(offer, reviews, now):
    """Match local operator-audited byte/rights records to exact photo evidence.

    A rights reference and digest are attestations supplied by the offline audit,
    not independently checked here. The report says so; no image is fetched and
    no display grant is created. View is explicit, never inferred from position.
    """
    photos = validate_photos(offer.get("listing_photos"), offer["source"], offer["url"],
                             offer["observed_at"], synthetic=offer.get("synthetic") is True)
    bound = [p for p in photos if p["evidence_ref"] == offer.get("evidence_ref")
             and _time(p["observed_at"]) == _time(offer["observed_at"])]
    if reviews is None:
        return bool(bound), None, None
    candidates = defaultdict(list)
    for review in reviews:
        if not isinstance(review, dict):
            raise ValueError("invalid offline photo audit")
        exact = (review.get("source") == offer["source"] and review.get("native_id") == offer["native_id"]
                 and review.get("listing_url") == offer["url"]
                 and review.get("offer_observed_at") == offer["observed_at"])
        if not exact:
            continue
        candidates[review.get("photo_url")].append(review)
    accepted = {}
    for photo_url, records in candidates.items():
        # A denial/revocation, changed digest or conflicting view must not be
        # ignored in favor of another row that claims the same image is allowed.
        signatures = {json.dumps(r, sort_keys=True, separators=(",", ":"), allow_nan=False) for r in records}
        if len(signatures) != 1:
            continue
        review = records[0]
        matched = next((p for p in bound if all(review.get(k) == p[k]
                       for k in ("evidence_ref", "observed_at")) and review.get("photo_url") == p["url"]), None)
        if (set(review) != PHOTO_AUDIT_FIELDS or not matched or review.get("depiction") != "actual_copy"
                or review.get("authorized") is not True or not _text(review.get("rights_reference"))
                or not isinstance(review.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", review["sha256"])
                or review.get("view") not in {"front", "back", "slab_label", "other", "unknown"}
                or _time(review.get("expires_at")) <= now):
            continue
        accepted[photo_url] = review
    fronts = {r["sha256"] for r in accepted.values() if r["view"] == "front"}
    backs = {r["sha256"] for r in accepted.values() if r["view"] == "back"}
    front_back = any(front != back for front in fronts for back in backs)
    return bool(bound), bool(accepted), front_back


def build_scorecard(offers=None, *, now, photo_audits=None, input_kind="retained_observations", freshness_seconds=300):
    """Build an offline scorecard from observations and optional operator audits.

    None inventory/audits are not evaluated; [] is an evaluated empty set.
    Duplicate observations cannot inflate coverage. The newest observation for a
    native listing wins; conflicting observations at the same time quarantine
    that listing. No payload has authority to authorize live access or purchase.
    """
    instant = _time(now)
    if type(freshness_seconds) is not int or not 1 <= freshness_seconds <= 900:
        raise ValueError("bounded report freshness between 1 and 900 seconds required")
    if input_kind not in {"retained_observations", "synthetic_fixture"}:
        raise ValueError("unsupported input kind")
    if offers is not None and not isinstance(offers, list) or photo_audits is not None and not isinstance(photo_audits, list):
        raise ValueError("offline inventory and photo audits must be arrays or null")
    report = {"schema": SCHEMA, "checked_at": instant.isoformat(), "input_kind": input_kind, "freshness_seconds": freshness_seconds,
              "inventory_status": "not_ingested" if offers is None else "evaluated_empty" if not offers else "evaluated",
              "input_status": "not_ingested" if offers is None else "evaluated_empty" if not offers else "evaluated",
              "metrics": {k: None for k in METRICS}, "observations_evaluated": None,
              "certificate_statuses": {}, "source_method_statuses": {},
              "availability_statuses": {}, "groups": [], "listing_gaps": [], "rejected_records": [],
              "photo_audit_status": "not_evaluated" if photo_audits is None else "evaluated",
              "live_coverage_verified": False, "authenticity_verified": False,
              "source_access_authorized": False, "orders_enabled": False, "payments_enabled": False,
              "scope": "Completeness of supplied offline observations; no card-match approval, provider verification, live availability or market-wide completeness.",
              "photo_scope": "Local operator-attested byte hash, depiction and rights evidence only; not independently authenticated or fetched.",
              "seller_scope": "Source-scoped native seller IDs; not deduplicated people across platforms. Display-name/profile-only aliases do not count.",
              "price_scope": "Same-currency product asking prices only; no shipping, fees, taxes, FX or final quote."}
    report["comparison_basis"] = "Equal complete seller identity/grade/condition claims only; no approved catalog match. comparable_product_price_groups is an alias of claimed_product_price_groups."
    if offers is None:
        return report
    metrics = {k: 0 for k in METRICS}
    for key in PHOTO_METRICS:
        if photo_audits is None:
            metrics[key] = None
    report["metrics"] = metrics
    report["observations_evaluated"] = len(offers)
    selected, conflicts = {}, set()
    for index, original in enumerate(offers):
        try:
            offer = deepcopy(original)
            if (not isinstance(offer, dict) or offer.get("source") not in SOURCES
                    or not _text(offer.get("native_id"), 128) or offer.get("scope") != "listing"
                    or not _native(offer["source"], offer["native_id"], offer.get("url"))
                    or "synthetic" in offer and type(offer["synthetic"]) is not bool
                    or not _text(offer.get("evidence_ref"))):
                raise ValueError()
            stamp = _time(offer.get("observed_at"))
            fresh = _time(offer.get("fresh_until"))
            if stamp > instant or fresh <= stamp:
                raise ValueError()
            # Canonical IDs collapse the plain eBay ID and its v1|id|0 alias.
            key = offer["source"], canonical_product_url(offer["url"])[1]
            serialized = json.dumps(offer, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if key in selected:
                old = selected[key]
                if old["url"] != offer["url"]:
                    conflicts.add(key)
                old_at = _time(old["observed_at"])
                if stamp == old_at and serialized != json.dumps(old, sort_keys=True, separators=(",", ":"), allow_nan=False):
                    conflicts.add(key)
                if stamp <= old_at:
                    continue
            selected[key] = offer
        except (ValueError, TypeError, KeyError, AttributeError):
            report["rejected_records"].append({"index": index, "reason": "invalid_listing_observation"})
    groups = defaultdict(list)
    certs, availability, methods = Counter(), Counter(), Counter()
    for key, offer in sorted(selected.items()):
        gaps = []
        if key in conflicts:
            gaps.append("conflicting_listing_observations")
        synthetic = input_kind == "synthetic_fixture" or offer.get("synthetic") is True
        if synthetic:
            gaps.append("synthetic_not_real_inventory")
        provenance = offer.get("source_provenance")
        if provenance is None:
            methods["unknown"] += 1
            gaps.append("source_method_missing")
        elif (isinstance(provenance, dict) and provenance.get("source") == offer["source"]
              and provenance.get("observed_at") == offer["observed_at"] and isinstance(provenance.get("method"), str)
              and provenance.get("method") in {"api", "crawl"}):
            methods[provenance["method"]] += 1
        else:
            methods["invalid"] += 1
            gaps.append("source_method_binding_invalid")
        available = offer.get("availability")
        state = offer.get("listing_status")
        availability[available if isinstance(available, str) and available in {"available", "sold_out", "unknown"} else "invalid"] += 1
        stamp, fresh_until = _time(offer["observed_at"]), _time(offer["fresh_until"])
        bounded = fresh_until <= stamp + timedelta(seconds=freshness_seconds)
        active = (available == "available" and state == "on_sale" and fresh_until > instant
                  and instant - stamp <= timedelta(seconds=freshness_seconds) and bounded)
        if not bounded:
            gaps.append("freshness_window_exceeds_report_limit")
        if not active:
            gaps.append("not_currently_observed_active")
        try:
            seller = _seller(offer)
        except (ValueError, TypeError, KeyError, AttributeError):
            seller = None
        if seller is None:
            gaps.append("seller_not_identified")
        price = _price(offer)
        grade = _grade(offer)
        if not price:
            gaps.append("product_price_unknown")
        if grade is None:
            gaps.append("grade_claim_needs_review")
        try:
            identity = _identity(offer)
        except (ValueError, TypeError, KeyError, AttributeError):
            identity = None
        if identity is None:
            gaps.append("identity_claims_incomplete_or_conflicting")
        condition = offer.get("seller_condition")
        condition = unicodedata.normalize("NFKC", condition).casefold() if _text(condition, 2048) else None
        if condition is None:
            gaps.append("condition_claim_unknown")
        single = type(offer.get("listing_quantity")) is int and offer["listing_quantity"] == 1
        if not single:
            gaps.append("quantity_unknown_or_not_single")
        cert = offer.get("certificate")
        cert = cert if isinstance(cert, dict) else {}
        number = cert.get("number_claim")
        certificate_status = cert.get("status")
        # The CommerceLoop DTO records claims, not certificate provider results.
        if not isinstance(certificate_status, str) or certificate_status not in {"number_missing", "not_checked"} or cert.get("physical_authenticity") != "not_verified":
            certificate_status = "unsupported_verification_claim"
            gaps.append("certificate_status_needs_review")
        certs[certificate_status] += 1
        if number is not None and not (isinstance(number, str) and bool(re.fullmatch(r"[0-9]{7,12}", number))):
            number = None
            gaps.append("certificate_number_malformed")
        if cert.get("number_claim") != offer.get("certificate_number_claim"):
            gaps.append("certificate_claim_conflict")
        if (certificate_status == "not_checked") != (number is not None):
            gaps.append("certificate_status_conflict")
        try:
            bound, copies, front_back = _photo_counts(offer, photo_audits, instant)
        except (ValueError, TypeError, KeyError, AttributeError):
            bound, copies, front_back = False, False if photo_audits is not None else None, False if photo_audits is not None else None
            gaps.append("invalid_photo_binding")
        if not bound:
            gaps.append("listing_photo_reference_missing")
        if copies is not True:
            gaps.append("authorized_copy_photos_missing_or_not_evaluated")
        # Only real, nonconflicting observations contribute to real coverage.
        real = not synthetic and key not in conflicts
        if real:
            metrics["distinct_listings"] += 1
            metrics["current_active_listings"] += int(active)
            metrics["listings_with_price"] += int(price)
            metrics["listings_with_grade_claim"] += int(_grade_claim_present(offer))
            metrics["listings_with_reviewed_comparison_grade"] += int(grade is not None)
            metrics["certificate_claims_present"] += int(number is not None)
            metrics["bound_photo_reference_listings"] += int(bound)
            if photo_audits is not None:
                metrics["authorized_copy_photo_listings"] += int(copies)
                metrics["front_back_photo_listings"] += int(front_back)
            if active and single and seller is not None and price and grade is not None and identity is not None and condition is not None and not any(x.startswith(("certificate_", "source_method_")) for x in gaps):
                group_key = identity, grade, condition, offer["currency"]
                groups[group_key].append({"source":key[0],"native_id":key[1],"price_minor":offer["price_minor"],"seller_key":seller,
                                          "authorized_copy_photos":copies,"front_back_photos":front_back})
        metrics["listings_needing_review"] += int(bool(gaps) and real)
        report["listing_gaps"].append({"source":key[0],"native_id":key[1],"gaps":sorted(set(gaps))})
    # Unknown or synthetic sellers cannot increase real seller breadth.
    real_sellers = set()
    for key, offer in selected.items():
        if key in conflicts or input_kind == "synthetic_fixture" or offer.get("synthetic") is True:
            continue
        try:
            seller = _seller(offer)
            if seller: real_sellers.add(seller)
        except (ValueError,TypeError,KeyError,AttributeError):
            pass
    metrics["unique_sellers"] = len(real_sellers)
    for key, rows in sorted(groups.items(), key=lambda pair: repr(pair[0])):
        if len(rows) < 2:
            continue
        identity, grade, condition, currency = key
        gid = hashlib.sha256(json.dumps(key,separators=(",",":")).encode()).hexdigest()
        distinct_sellers = len({r["seller_key"] for r in rows})
        photo_sellers = {r["seller_key"] for r in rows if r["authorized_copy_photos"] is True}
        front_back_sellers = {r["seller_key"] for r in rows if r["front_back_photos"] is True}
        report["groups"].append({"group_id":gid,"basis":"equal_complete_seller_claims_only",
            "identity_claims":dict(zip(FIELDS,identity)),"grade_claim":{"kind":grade[0],"company":grade[1],"value":grade[2]},
            "condition_claim":condition,"currency":currency,"listing_count":len(rows),"seller_count":distinct_sellers,
            "listings": [{k:v for k,v in r.items() if k != "seller_key"} for r in sorted(rows,key=lambda r:(r['price_minor'],r['source'],r['native_id']))],
            "catalog_match_approved":False,"authenticity_verified":False})
        metrics["claimed_product_price_groups"] += 1
        metrics["multi_seller_claim_groups"] += int(distinct_sellers > 1)
        if photo_audits is not None:
            metrics["photo_supported_multi_seller_claim_groups"] += int(len(photo_sellers) > 1)
            metrics["front_back_supported_multi_seller_claim_groups"] += int(len(front_back_sellers) > 1)
    report["certificate_statuses"] = dict(sorted(certs.items()))
    report["availability_statuses"] = dict(sorted(availability.items()))
    report["source_method_statuses"] = dict(sorted(methods.items()))
    metrics["comparable_product_price_groups"] = metrics["claimed_product_price_groups"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="local normalized observation array; omitted means inventory not ingested")
    parser.add_argument("--photo-audits", type=Path, help="optional local operator-attested photo audit array")
    parser.add_argument("--now", required=True, help="explicit timezone-aware scorecard time")
    parser.add_argument("--synthetic", action="store_true", help="diagnose fixture inputs; never count as real inventory")
    parser.add_argument("--freshness-seconds", type=int, default=300, help="explicit report window, 1 to 900 seconds")
    args = parser.parse_args()
    offers = strict_json(args.input.read_text()) if args.input else None
    photos = strict_json(args.photo_audits.read_text()) if args.photo_audits else None
    print(json.dumps(build_scorecard(offers, now=args.now, photo_audits=photos,
                                    input_kind="synthetic_fixture" if args.synthetic else "retained_observations",
                                    freshness_seconds=args.freshness_seconds), indent=2))


if __name__ == "__main__":
    main()

"""Disposable BNS previews bound to one selected public URL, never catalog stock.

This path is explicitly enabled separately from the frozen indexed adapter.
It neither imports a candidate nor approves its card identity or seller claims.
Each attempt has a fresh OAuth client and at most one resolve and one quote.
"""
from __future__ import annotations

import copy
from datetime import timedelta
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
from urllib.parse import urlsplit

from .bns_errors import BNSRefusal, normalize_variants, refusal, validate_refusal
from .bns_transport import BNS_PATHS, OneShotBNSSender, ProbeError, _base_url, _destination
from .bounded_buyship import _ACTIVE_WORKER
from .buyship_partner import PartnerClient, QUOTE_COMPONENTS
from .commerce_loop import _time, utcnow
from .marketplace_crawl import canonical_product_url
from .psa_cert import _response

REQUEST_SCHEMA = "pokemon.bns-url-preview-request.v1"
RESULT_SCHEMA = "pokemon.bns-url-preview-result.v1"
EVIDENCE_SCHEMA = "pokemon.bns-url-preview-evidence.v1"
BINDING_SCOPE = "selected marketplace URL and BNS reference/variant only; catalog identity and seller grade remain unverified"
WORKER_SECONDS = 18
MAX_BYTES = 65536
MAX_MONEY = 2**53 - 1
LISTING_FIELDS = ("source", "native_id", "url", "title", "observed_at", "grade", "identity_status",
                  "seller_condition", "source_status_text", "listing_status", "evidence_ref", "certificate_number_claim",
                  "certificate", "listing_quantity")


def _fail(code="invalid_provider_response", **kwargs):
    raise BNSRefusal(refusal(code, **kwargs))


def _text(value, maximum=300):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
            and all(ord(c) >= 32 and ord(c) != 127 for c in value))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def _binding(quote):
    value = copy.deepcopy(quote)
    value["evidence"].pop("binding_sha256", None)
    return _hash(value)


def _money(value, currency=None):
    if (not isinstance(value, dict) or set(value) != {"currency", "subunit_amount"}
            or not isinstance(value["currency"], str) or not re.fullmatch(r"[A-Z]{3}", value["currency"])
            or type(value["subunit_amount"]) is not int or not 0 <= value["subunit_amount"] <= MAX_MONEY
            or currency is not None and value["currency"] != currency):
        _fail()
    return dict(value)


def _ask(offer):
    if offer["price_minor"] is None:
        return None
    return _money({"currency": offer["currency"], "subunit_amount": offer["price_minor"]})


def _research(card_id, offer, destination):
    if not _destination(destination):
        _fail("invalid_destination")
    if not _text(card_id, 256) or not isinstance(offer, dict):
        _fail()
    source, native, url = canonical_product_url(offer.get("url"))
    if (source != offer.get("source") or native != offer.get("native_id") or url != offer.get("url")
            or offer.get("scope") != "listing" or source == "snkrdunk" and "/used/" not in url
            or offer.get("synthetic") is not False or offer.get("identity_status") != "unverified_candidate"
            or offer.get("authenticity_verified") is not False or not _text(offer.get("title"), 2000)):
        _fail("product_mismatch")
    if (offer.get("availability") not in {"available", "unknown"}
            or offer.get("listing_status") not in {"on_sale", "unknown"}):
        _fail("variant_unavailable")
    grade = offer.get("grade")
    legacy_grade = {"company", "value", "certificate_verified"}
    evidence_grade = legacy_grade | {"kind", "evidence", "review_required", "review_reasons", "special_label"}
    if (not isinstance(grade, dict) or set(grade) not in (legacy_grade, evidence_grade)
            or grade["certificate_verified"] is not False
            or grade["company"] not in {None, "PSA", "BGS", "CGC", "ARS", "PGC"}
            or grade["value"] is not None and (grade["company"] is None or not isinstance(grade["value"], str)
                or not re.fullmatch(r"(?:10|[0-9])(?:\.5)?", grade["value"]) or float(grade["value"]) > 10)):
        _fail()
    if set(grade) == evidence_grade:
        from .marketplace_quality import GRADE_EVIDENCE, REVIEW_REASONS
        if (not isinstance(grade["kind"], str) or grade["kind"] not in {"slab", "raw", "unknown"}
                or not isinstance(grade["evidence"], str) or grade["evidence"] not in GRADE_EVIDENCE
                or type(grade["review_required"]) is not bool
                or not isinstance(grade["review_reasons"], list)
                or any(not isinstance(reason, str) or reason not in REVIEW_REASONS for reason in grade["review_reasons"])
                or len(set(grade["review_reasons"])) != len(grade["review_reasons"])
                or grade["special_label"] not in (None, "black_label", "pristine")
                or (grade["kind"] == "slab") != bool(grade["company"] and grade["value"])
                or grade["kind"] == "raw" and (grade["company"] is not None or grade["value"] is not None)):
            _fail()
        if (grade["review_required"] or grade["review_reasons"]
                or grade["kind"] == "unknown" or grade["special_label"] is not None):
            _fail("product_mismatch")
    if "certificate" in offer:
        certificate = offer["certificate"]
        if (not isinstance(certificate, dict)
                or set(certificate) != {"number_claim", "status", "physical_authenticity"}
                or certificate["physical_authenticity"] != "not_verified"
                or certificate["number_claim"] is not None and not _text(certificate["number_claim"], 64)
                or certificate["number_claim"] != offer.get("certificate_number_claim")
                or certificate["status"] != ("not_checked" if certificate["number_claim"] else "number_missing")):
            _fail()
    _ask(offer)
    instant, observed, expires = _time(utcnow()), _time(offer.get("observed_at")), _time(offer.get("fresh_until"))
    if not instant - timedelta(seconds=300) <= observed <= instant < expires <= observed + timedelta(seconds=300):
        _fail("quote_expired")


def _identity_text(value):
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"(?<=\d)\s*/\s*(?=\d)", "/", value)


def _grade_number(value):
    whole, _, fraction = value.partition(".")
    fraction = fraction.rstrip("0")
    return str(int(whole)) + ("." + fraction if fraction else "")


def _identity(name, offer, card_id):
    """Explicit contradictions reject; absence of one never verifies a card."""
    from . import core
    from .marketplace_quality import NUMERIC_GRADE, contradicts_grade
    if not _text(name, 2000):
        _fail()
    name = _identity_text(name)
    source_title = _identity_text(offer["title"])
    card_id = _identity_text(card_id)
    numbers = {core.normalize_collector_number(v) for v in core.NUMBER_RE.findall(name)}
    expected = {core.normalize_collector_number(v) for v in core.NUMBER_RE.findall(source_title)}
    if re.fullmatch(r"(?:ja|en):[^:]+:[^:]+:[^:]+", card_id):
        expected.add(core.normalize_collector_number(card_id.split(":")[2]))
    grade = offer["grade"]
    if numbers and expected and numbers != expected:
        _fail("product_mismatch")
    # Conventional grader punctuation and equivalent decimal scores carry the
    # same explicit evidence as PSA 9; keep this normalization local to previews.
    grade_text = re.sub(r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)[\s:_-]*"
                        r"(?:grading|grade|鑑定評価|鑑定)\s*[:=_/\-(]?\s*(?=\d)",
                        r"\1 ", name, flags=re.I)
    grade_text = re.sub(r"(?<![A-Za-z])(PSA|BGS|CGC|ARS|PGC)\s*[:=_/\-(]\s*(?=\d)",
                        r"\1 ", grade_text, flags=re.I)
    grade_text = NUMERIC_GRADE.sub(lambda match: f"{match[1]} {_grade_number(match[2])}", grade_text)
    if grade["company"] and grade["value"] and contradicts_grade(grade_text, grade["company"], _grade_number(grade["value"])):
        _fail("product_mismatch")


def _variant_identity(options, offer, card_id):
    """Check selected option evidence without turning ordinary choices into identity."""
    for key, value in options.items():
        key, value = (_identity_text(text) for text in (key, value))
        # Check each part independently so repeated compatible evidence does not
        # look like multiple conflicting grades to the shared grade checker.
        _identity(key, offer, card_id)
        _identity(value, offer, card_id)
        for label, description in ((key, value), (value, key)):
            grade_label = r"(?:grading|grade|鑑定評価|鑑定)"
            company_label = r"(PSA|BGS|CGC|ARS|PGC)"
            context = re.fullmatch(rf"\s*(?:{company_label}(?:[\s:_-]*{grade_label})?"
                                   rf"|{grade_label}[\s:_-]*{company_label})\s*", label, re.I)
            graders = {company.upper() for company in context.groups() if company} if context else set()
            if not graders and re.fullmatch(r"\s*(?:grade|grading|鑑定|鑑定評価)\s*", label, re.I):
                graders = {offer["grade"]["company"]} - {None}
            # Grade-labelled descriptions such as PSA:9 Mint or grade:Mint9
            # are explicit evidence. Numeric fractions remain card evidence,
            # and unrelated size:9 Mint says nothing about the retained grade.
            # A labelled certificate serial is metadata, not another grade.
            # Original per-part identity checks above still see every byte.
            grade_description = re.sub(r"(?<![A-Za-z])cert(?:ificate)?(?:\s*(?:no\.?|number|id))?"
                                       r"\s*[:#-]?\s*\d{1,32}(?![\d./])", " ", description, flags=re.I)
            for company in graders:
                for number in re.findall(r"(?<![\d./])(\d+(?:\.\d+)?)(?![\d./])", grade_description):
                    _identity(f"{company} {_grade_number(number)}", offer, card_id)


def _no_secrets(value, secrets):
    retained = [v for v in secrets if isinstance(v, str) and v]

    def contains(item):
        if isinstance(item, str):
            return any(secret in item for secret in retained)
        if isinstance(item, dict):
            return any(contains(key) or contains(value) for key, value in item.items())
        if isinstance(item, (list, tuple)):
            return any(contains(value) for value in item)
        return False

    # Search decoded values, not their JSON representation: escaping a quote
    # or backslash in a credential must not hide an echoed secret from us.
    if contains(value):
        _fail()


def validate_quote(quote, card_id, offer, destination, variant=None):
    """Validate worker output independently against the retained selection."""
    if (not isinstance(quote, dict) or set(quote) != {"status", "purchasable", "purchase_action", "order_created",
            "card_id", "listing", "buyship", "evidence"} or quote["status"] != "quote_ready_for_review"
            or quote["purchasable"] is not False or quote["order_created"] is not False
            or quote["purchase_action"] is not None or quote["card_id"] != card_id):
        _fail("quote_binding_invalid")
    expected_listing = {key: offer[key] for key in LISTING_FIELDS if key in offer}
    expected_listing["ask"] = _ask(offer)
    if quote["listing"] != expected_listing:
        _fail("quote_binding_invalid")
    b = quote["buyship"]
    fields = {"reference_id", "variant_key", "canonical_url", "merchant_domain", "resolve_price",
              "resolve_price_differs_from_observation", "quote_id", "expires_at", "quoted_at", "destination",
              "currency", "unit_price", "components", "grand_total", "variant_options", "resolved_availability"}
    if (not isinstance(b, dict) or set(b) != fields or b["canonical_url"] != offer["url"]
            or b["destination"] != destination or b["resolved_availability"] != "in_stock"
            or not all(_text(b[key]) for key in ("reference_id", "variant_key", "quote_id"))
            or not isinstance(b["merchant_domain"], str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", b["merchant_domain"])
            or not isinstance(b["currency"], str) or not re.fullmatch(r"[A-Z]{3}", b["currency"])):
        _fail("quote_binding_invalid")
    current_variant = normalize_variants([{"variant_key": b["variant_key"], "options": b["variant_options"],
        "availability": b["resolved_availability"], "price": b["resolve_price"]}])[0]
    _variant_identity(current_variant["options"], offer, card_id)
    if variant is not None and normalize_variants([variant])[0] != current_variant:
        _fail("quote_binding_invalid")
    _money(b["resolve_price"])
    total, unit = _money(b["grand_total"], b["currency"]), _money(b["unit_price"], b["currency"])
    if (not isinstance(b["components"], dict) or set(b["components"]) != set(QUOTE_COMPONENTS)
            or b["components"]["items"] != unit
            or sum(_money(b["components"][k], b["currency"])["subunit_amount"] for k in QUOTE_COMPONENTS) != total["subunit_amount"]):
        _fail("quote_binding_invalid")
    ask = _ask(offer)
    differs = bool(ask is not None and ask["currency"] == b["resolve_price"]["currency"] and ask != b["resolve_price"])
    if type(b["resolve_price_differs_from_observation"]) is not bool or b["resolve_price_differs_from_observation"] != differs:
        _fail("quote_binding_invalid")
    now, quoted, expiry = _time(utcnow()), _time(b["quoted_at"]), _time(b["expires_at"])
    if not quoted <= now < expiry <= quoted + timedelta(minutes=16) or now - quoted > timedelta(seconds=60):
        _fail("quote_expired")
    e = quote["evidence"]
    hashes = {"selected_offer_sha256", "resolve_response_sha256", "quote_response_sha256", "binding_sha256"}
    if (not isinstance(e, dict) or set(e) != hashes | {"schema", "mode", "identity_status", "certificate_verified",
            "authenticity_verified", "binding_scope"} or e["schema"] != EVIDENCE_SCHEMA or e["mode"] != "url_quote_preview"
            or e["identity_status"] != "unverified_candidate" or e["certificate_verified"] is not False
            or e["authenticity_verified"] is not False or e["binding_scope"] != BINDING_SCOPE
            or any(not isinstance(e[k], str) or not re.fullmatch(r"[0-9a-f]{64}", e[k]) for k in hashes)
            or e["selected_offer_sha256"] != _hash(offer) or e["binding_sha256"] != _binding(quote)):
        _fail("quote_binding_invalid")
    return quote


def _preview(payload, *, env=None, transport=None):
    env = os.environ if env is None else env
    client = None
    secrets = [env.get("BNS_PARTNER_CLIENT_ID"), env.get("BNS_PARTNER_CLIENT_SECRET")]
    try:
        fields = {"schema", "card_id", "offer", "destination", "variant", "deadline"}
        if (not isinstance(payload, dict) or set(payload) != fields or payload["schema"] != REQUEST_SCHEMA
                or type(payload["deadline"]) not in (int, float) or not math.isfinite(payload["deadline"])
                or time.monotonic() >= payload["deadline"]):
            _fail("provider_timeout")
        card_id, offer, destination, expected_variant = (payload[k] for k in ("card_id", "offer", "destination", "variant"))
        _research(card_id, offer, destination)
        if expected_variant is not None:
            expected_variant = normalize_variants([expected_variant])[0]
        sender = OneShotBNSSender(env["BNS_PARTNER_BASE_URL"], authorized=True, transport=transport,
                                 deadline=payload["deadline"])
        client = PartnerClient(sender.base_url, env["BNS_PARTNER_CLIENT_ID"], env["BNS_PARTNER_CLIENT_SECRET"],
                               sender=sender, live_authorized=True)
        resolved = client.resolve(offer["url"])
        _research(card_id, offer, destination)
        if (not isinstance(resolved, dict) or canonical_product_url(resolved.get("url"))[2] != offer["url"]
                or not _text(resolved.get("reference_id")) or not isinstance(resolved.get("product"), dict)):
            _fail("product_mismatch")
        _identity(resolved["product"].get("name"), offer, card_id)
        variants = normalize_variants(resolved.get("variants"))
        if expected_variant is None:
            if len(variants) != 1:
                _fail("variant_selection_required", details={"variants": variants})
            selected = variants[0]
        else:
            matches = [v for v in variants if v["variant_key"] == expected_variant["variant_key"]]
            if len(matches) != 1 or matches[0] != expected_variant:
                _fail("variant_changed", details={"variants": variants})
            selected = matches[0]
        if selected["availability"] != "in_stock":
            _fail("variant_unavailable", details={"variants": variants})
        _variant_identity(selected["options"], offer, card_id)
        merchant = resolved.get("merchant")
        if not isinstance(merchant, dict) or not isinstance(merchant.get("domain"), str) or not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", merchant["domain"]):
            _fail()
        quoted = client.quote(resolved["reference_id"], selected["variant_key"], destination)
        received_at = utcnow()
        if (not isinstance(quoted, dict) or quoted.get("status") != "OPEN" or not _text(quoted.get("quote_id"))
                or quoted.get("destination") != destination or not isinstance(quoted.get("items"), list)
                or len(quoted["items"]) != 1 or not isinstance(quoted["items"][0], dict)):
            _fail("quote_binding_invalid")
        item = quoted["items"][0]
        if (type(item.get("quantity")) is not int or item["quantity"] != 1
                or item.get("reference_id") != resolved["reference_id"] or item.get("variant_key") != selected["variant_key"]
                or item.get("variant_options") != selected["options"] or item.get("availability", "in_stock") != "in_stock"):
            _fail("quote_binding_invalid")
        if "name" in item:
            _identity(item["name"], offer, card_id)
        for response in (quoted, item):
            if "url" in response and canonical_product_url(response["url"])[2] != offer["url"]:
                _fail("product_mismatch")
        currency = quoted.get("currency")
        unit, item_total = _money(item.get("unit_price"), currency), _money(item.get("item_total"), currency)
        totals = quoted.get("totals")
        if unit != item_total or not isinstance(totals, dict):
            _fail("quote_binding_invalid")
        components = {k: _money(totals.get(k), currency) for k in QUOTE_COMPONENTS}
        listing = {k: copy.deepcopy(offer[k]) for k in LISTING_FIELDS if k in offer}
        listing["ask"] = _ask(offer)
        quote = {"status": "quote_ready_for_review", "purchasable": False, "purchase_action": None, "order_created": False,
            "card_id": card_id, "listing": listing, "buyship": {"reference_id": resolved["reference_id"],
                "variant_key": selected["variant_key"], "canonical_url": offer["url"], "merchant_domain": merchant["domain"],
                "resolve_price": selected["price"], "resolve_price_differs_from_observation": bool(listing["ask"] is not None
                    and listing["ask"]["currency"] == selected["price"]["currency"] and listing["ask"] != selected["price"]),
                "quote_id": quoted["quote_id"], "expires_at": quoted.get("expires_at"), "quoted_at": received_at,
                "destination": dict(destination), "currency": currency, "unit_price": unit, "components": components,
                "grand_total": _money(totals.get("grand_total"), currency), "variant_options": selected["options"],
                "resolved_availability": "in_stock"},
            "evidence": {"schema": EVIDENCE_SCHEMA, "mode": "url_quote_preview", "identity_status": "unverified_candidate",
                "certificate_verified": False, "authenticity_verified": False, "selected_offer_sha256": _hash(offer),
                "resolve_response_sha256": _hash(resolved), "quote_response_sha256": _hash(quoted), "binding_scope": BINDING_SCOPE}}
        quote["evidence"]["binding_sha256"] = _binding(quote)
        if sender.requests != list(BNS_PATHS) or time.monotonic() >= payload["deadline"]:
            _fail("provider_timeout")
        _research(card_id, offer, destination)
        validate_quote(quote, card_id, offer, destination, expected_variant)
        _no_secrets(quote, secrets + [client._token])
        return quote
    except BNSRefusal as exc:
        _no_secrets(exc.result, secrets + ([client._token] if client else []))
        raise


def _worker():
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        _, payload = _response({"status": 200, "body": raw}, MAX_BYTES)
        result = {"schema": RESULT_SCHEMA, "quote": _preview(payload)}
    except BNSRefusal as exc:
        result = {"schema": RESULT_SCHEMA, "refusal": exc.result}
    except ProbeError as exc:
        result = {"schema": RESULT_SCHEMA, "refusal": refusal(exc.code)}
    except Exception:
        result = {"schema": RESULT_SCHEMA, "refusal": refusal("invalid_provider_response")}
    encoded = json.dumps(result, allow_nan=False)
    if len(encoded.encode()) > MAX_BYTES:
        encoded = json.dumps({"schema": RESULT_SCHEMA, "refusal": refusal("invalid_provider_response")})
    print(encoded)


class URLBuyShipForwarder:
    id, label, url_preview = "buyship", "Buy & Ship", True

    def __init__(self, base_url, client_id, client_secret, *, live_authorized=False,
                 runner=None, monotonic=time.monotonic):
        self.base_url = _base_url(base_url)
        if not _text(client_id, 1024) or not _text(client_secret, 8192):
            raise ValueError("server-owned BNS configuration required")
        self.client_id, self.client_secret = client_id, client_secret
        self.live_authorized, self.runner, self.monotonic = live_authorized is True, runner or subprocess.run, monotonic

    def preview_before(self, card_id, offer, destination, *, deadline, variant=None):
        if not self.live_authorized:
            _fail("live_not_authorized")
        if type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= self.monotonic():
            _fail("provider_timeout")
        _research(card_id, offer, destination)
        if variant is not None:
            variant = normalize_variants([variant])[0]
        if not _ACTIVE_WORKER.acquire(blocking=False):
            _fail("provider_busy")
        try:
            payload = {"schema": REQUEST_SCHEMA, "card_id": card_id, "offer": offer, "destination": destination,
                       "variant": variant, "deadline": deadline}
            raw = json.dumps(payload, allow_nan=False)
            if len(raw.encode()) > MAX_BYTES:
                _fail()
            env = dict(os.environ)
            env.update(BNS_PARTNER_BASE_URL=self.base_url, BNS_PARTNER_CLIENT_ID=self.client_id,
                       BNS_PARTNER_CLIENT_SECRET=self.client_secret)
            remaining = min(WORKER_SECONDS, deadline - self.monotonic())
            if remaining <= 0:
                _fail("provider_timeout")
            result = self.runner([sys.executable, "-c", "from pokemon_index.bns_url_preview import _worker; _worker()"],
                input=raw, env=env, capture_output=True, text=True, timeout=remaining, check=False)
            if self.monotonic() >= deadline:
                _fail("provider_timeout")
            if result.returncode != 0:
                _fail()
            _, value = _response({"status": 200, "body": result.stdout}, MAX_BYTES)
            if value.get("schema") != RESULT_SCHEMA:
                _fail()
            if set(value) == {"schema", "refusal"}:
                dto = validate_refusal(value["refusal"])
                _no_secrets(dto, [self.client_id, self.client_secret])
                raise BNSRefusal(dto)
            if set(value) != {"schema", "quote"}:
                _fail()
            quote = validate_quote(value["quote"], card_id, offer, destination, variant)
            _research(card_id, offer, destination)
            _no_secrets(quote, [self.client_id, self.client_secret])
            return quote
        except BNSRefusal:
            raise
        except subprocess.TimeoutExpired:
            # subprocess.run kills and reaps its child before this exception.
            _fail("provider_timeout")
        except Exception:
            _fail()
        finally:
            _ACTIVE_WORKER.release()

"""Closed, credential-free BNS refusal DTOs for the quote-only boundary.

Provider messages and arbitrary details are never displayed. Only documented
codes and normalized variant/currency/field hints cross the worker boundary.
"""
from __future__ import annotations

import re

SCHEMA = "pokemon.bns-refusal.v1"

# These messages are part of the public DTO, rather than text from a provider.
MESSAGES = {
    "invalid_request": "Buy & Ship could not accept the quote request. Check the highlighted fields.",
    "unsupported_grant_type": "Buy & Ship authentication configuration needs attention.",
    "invalid_client": "Buy & Ship client access was rejected. Check the configured credentials.",
    "server_error": "Buy & Ship could not issue an access token. Try again later.",
    "not_found": "Buy & Ship no longer recognizes this product reference. Resolve the product again.",
    "quote_expired": "The Buy & Ship quote has expired. Request a new preview.",
    "currency_unsupported": "Buy & Ship does not support the requested currency for this account.",
    "destination_unsupported": "Buy & Ship does not support this destination.",
    "variant_unavailable": "The selected Buy & Ship variant is unavailable. Review the current variants.",
    "product_not_eligible": "Buy & Ship cannot ship this product under the current restrictions.",
    "quote_limit_exceeded": "The item value exceeds the Buy & Ship quote limit.",
    "product_not_quotable": "Buy & Ship could not read enough product information to provide a quote.",
    "merchant_unreachable": "Buy & Ship could not reach the merchant. You can try a new preview later.",
    "variant_selection_required": "Choose a Buy & Ship variant before requesting a quote preview.",
    "variant_changed": "The Buy & Ship variants changed. Review them and choose again.",
    "product_mismatch": "Buy & Ship product evidence conflicts with the selected listing. No quote preview was accepted.",
    "quote_binding_invalid": "Buy & Ship returned a quote that did not match the selected product and destination.",
    "invalid_destination": "Choose Hong Kong or a supported US destination with a state code.",
    "provider_unconfigured": "Buy & Ship quote preview is not configured.",
    "provider_busy": "A Buy & Ship preview is already running. Wait before trying again.",
    "provider_timeout": "The Buy & Ship preview reached its time limit. You can try again later.",
    "provider_unavailable": "Buy & Ship quote preview is unavailable. You can try again later.",
    "invalid_provider_response": "Buy & Ship returned a response that could not be safely verified.",
    "bns_unavailable": "Buy & Ship quote preview is unavailable. You can try again later.",
    "bns_disabled": "Buy & Ship quote preview is disabled.",
    "bns_not_configured": "Buy & Ship quote preview is not configured.",
    "bns_access_rejected": "Buy & Ship access was rejected. Check the configured client access.",
    "bns_rate_limited": "Buy & Ship is limiting requests. Try a new preview later.",
    "bns_http_rejected": "Buy & Ship could not complete this preview request.",
    "bns_response_invalid": "Buy & Ship returned a response that could not be safely verified.",
    "bns_request_deadline": "The Buy & Ship preview reached its time limit. You can try again later.",
    "bns_request_budget_or_route": "The Buy & Ship preview exceeded its permitted request scope.",
    "approved_bns_endpoint_required": "An approved Buy & Ship endpoint is required.",
    "live_not_authorized": "Buy & Ship live quote preview is not authorized.",
    "single_quote_only": "Buy & Ship preview supports one item with quantity one.",
}

_REFUSED = {"invalid_request", "not_found", "currency_unsupported", "destination_unsupported",
            "variant_unavailable", "product_not_eligible", "quote_limit_exceeded", "product_not_quotable",
            "product_mismatch", "invalid_destination"}
_SELECTION = {"variant_selection_required", "variant_changed"}
_RETRYABLE = {"server_error", "merchant_unreachable", "provider_busy", "provider_timeout",
              "provider_unavailable", "bns_unavailable", "bns_rate_limited", "bns_request_deadline"}

# Codes are valid only at the documented endpoint and HTTP status.
_PROVIDER = {
    "oauth": {"invalid_request": 400, "unsupported_grant_type": 400, "invalid_client": 401, "server_error": 500},
    "resolve": {"product_not_eligible": 422},
    "quote": {"invalid_request": 400, "not_found": 404, "quote_expired": 409,
              "currency_unsupported": 422, "destination_unsupported": 422, "variant_unavailable": 422,
              "product_not_eligible": 422, "quote_limit_exceeded": 422, "product_not_quotable": 422,
              "merchant_unreachable": 424},
}
_REASONS = {
    "product_not_eligible": {"MERCHANT_NOT_SUPPORTED", "CATEGORY_PROHIBITED", "SELLER_BLACKLISTED",
                             "UNABLE_TO_ASSESS", "DESTINATION_PROHIBITED", "PREORDER_NOT_SUPPORTED"},
    "currency_unsupported": {"CURRENCY_UNSUPPORTED"},
    "destination_unsupported": {"DESTINATION_UNSUPPORTED"},
    "variant_unavailable": {"OUT_OF_STOCK", "VARIANT_NOT_FOUND"},
    "quote_limit_exceeded": {"VALUE_EXCEEDS_CEILING"},
}
_FIELDS = {
    "url": "Use a supported product URL.",
    "items": "Use one item with quantity one.",
    "items[0].reference_id": "Resolve the selected product again.",
    "items[0].variant_key": "Choose a current product variant.",
    "items[0].quantity": "Use quantity one.",
    "destination": "Choose a supported destination.",
    "destination.country": "Choose Hong Kong or the United States.",
    "destination.state": "Choose a two-letter US state code.",
    "currency": "Choose a supported account currency.",
    "client_id": "Check the configured client credentials.",
    "client_secret": "Check the configured client credentials.",
    "grant_type": "Use client credentials authentication.",
}


def _status(code):
    return "variant_selection_required" if code in _SELECTION else "refused" if code in _REFUSED else "unavailable"


def _label(value, maximum, *, key=False):
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum or value != value.strip()
            or not all(char.isalnum() or char in ("._:-" if key else " ._:/()+%&,-") for char in value)):
        raise ValueError("invalid BNS variant label")
    return value


def normalize_variants(value):
    """Normalize bounded quote choices; a malformed or duplicate choice fails closed."""
    if not isinstance(value, list) or not 1 <= len(value) <= 25:
        raise ValueError("invalid BNS variants")
    result, keys = [], set()
    for variant in value:
        if not isinstance(variant, dict) or set(variant) != {"variant_key", "options", "availability", "price"}:
            raise ValueError("invalid BNS variant")
        key = _label(variant["variant_key"], 128, key=True)
        if key in keys:
            raise ValueError("duplicate BNS variant")
        keys.add(key)
        options = variant["options"]
        if not isinstance(options, dict) or len(options) > 8:
            raise ValueError("invalid BNS variant options")
        options = {_label(name, 40): _label(option, 80) for name, option in options.items()}
        availability, price = variant["availability"], variant["price"]
        if not isinstance(availability, str) or availability not in {"in_stock", "out_of_stock", "unknown"}:
            raise ValueError("invalid BNS variant availability")
        if (not isinstance(price, dict) or set(price) != {"currency", "subunit_amount"}
                or not isinstance(price["currency"], str) or not re.fullmatch(r"[A-Z]{3}", price["currency"])
                or type(price["subunit_amount"]) is not int or not 0 <= price["subunit_amount"] <= 10**12):
            raise ValueError("invalid BNS variant price")
        result.append({"variant_key": key, "options": dict(sorted(options.items())), "availability": availability,
                       "price": dict(price)})
    return result


def _details(code, value, *, provider=False):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("invalid BNS refusal details")
    if not value:
        return {}
    if code in {"variant_unavailable", "variant_selection_required", "variant_changed"} and set(value) == {"variants"}:
        return {"variants": normalize_variants(value["variants"])}
    if code == "currency_unsupported" and set(value) == {"supported_currencies"}:
        currencies = value["supported_currencies"]
        if (not isinstance(currencies, list) or not 1 <= len(currencies) <= 20
                or any(not isinstance(c, str) or not re.fullmatch(r"[A-Z]{3}", c) for c in currencies)
                or len(set(currencies)) != len(currencies)):
            raise ValueError("invalid BNS supported currencies")
        return {"supported_currencies": currencies[:]}
    if code == "invalid_request" and set(value) == {"field_errors"}:
        errors = value["field_errors"]
        if not isinstance(errors, list) or not 1 <= len(errors) <= 12:
            raise ValueError("invalid BNS field errors")
        result, seen = [], set()
        for error in errors:
            if (not isinstance(error, dict) or set(error) != {"field", "message"}
                    or not isinstance(error["field"], str) or error["field"] not in _FIELDS
                    or error["field"] in seen or not isinstance(error["message"], str)
                    or len(error["message"]) > 1024):
                raise ValueError("invalid BNS field error")
            field = error["field"]
            seen.add(field)
            if not provider and error["message"] != _FIELDS[field]:
                raise ValueError("invalid BNS field message")
            result.append({"field": field, "message": _FIELDS[field]})
        return {"field_errors": result}
    raise ValueError("invalid BNS refusal details")


def refusal(code="bns_unavailable", *, reason_codes=(), retryable=None, details=None, status=None):
    """Construct a local refusal; invalid caller input becomes a fixed unavailable DTO."""
    try:
        if code not in MESSAGES:
            raise ValueError("invalid BNS refusal code")
        result = {"schema": SCHEMA, "status": _status(code) if status is None else status, "code": code,
                  "reason_codes": list(reason_codes), "retryable": code in _RETRYABLE if retryable is None else retryable,
                  "message": MESSAGES[code], "details": _details(code, details)}
        return validate_refusal(result)
    except (ValueError, TypeError, KeyError):
        return {"schema": SCHEMA, "status": "unavailable", "code": "bns_unavailable", "reason_codes": [],
                "retryable": True, "message": MESSAGES["bns_unavailable"], "details": {}}


def validate_refusal(value):
    """Return the canonical DTO, or reject any unknown field, code or mutable text."""
    if (not isinstance(value, dict)
            or set(value) != {"schema", "status", "code", "reason_codes", "retryable", "message", "details"}
            or value["schema"] != SCHEMA or not isinstance(value["code"], str) or value["code"] not in MESSAGES):
        raise ValueError("invalid BNS refusal")
    code, reasons = value["code"], value["reason_codes"]
    if (value["status"] != _status(code) or value["message"] != MESSAGES[code]
            or type(value["retryable"]) is not bool or value["retryable"] != (code in _RETRYABLE)
            or not isinstance(reasons, list) or len(reasons) > 6
            or any(not isinstance(reason, str) or reason not in _REASONS.get(code, set()) for reason in reasons)
            or len(set(reasons)) != len(reasons)):
        raise ValueError("invalid BNS refusal")
    return {"schema": SCHEMA, "status": value["status"], "code": code, "reason_codes": reasons[:],
            "retryable": value["retryable"], "message": MESSAGES[code], "details": _details(code, value["details"])}


class BNSRefusal(ValueError):
    def __init__(self, result):
        self.result = validate_refusal(result)
        self.code = self.result["code"]
        super().__init__(self.code)


def sanitize_provider_error(http_status, payload, *, stage):
    """Read only the documented shape, discarding all provider-authored messages."""
    try:
        if type(http_status) is not int or stage not in _PROVIDER or not isinstance(payload, dict):
            raise ValueError("invalid BNS provider error")
        if stage == "oauth":
            if set(payload) - {"error", "error_description", "error_uri"} or not isinstance(payload.get("error"), str):
                raise ValueError("invalid BNS OAuth error")
            code, reasons, details = payload["error"], [], {}
            if any(key in payload and not isinstance(payload[key], str) for key in {"error_description", "error_uri"}):
                raise ValueError("invalid BNS OAuth error")
        else:
            error = payload.get("error")
            if (set(payload) != {"error"} or not isinstance(error, dict)
                    or set(error) - {"code", "message", "reason_codes", "retryable", "details"}
                    or not isinstance(error.get("code"), str)):
                raise ValueError("invalid BNS API error")
            code, reasons = error["code"], error.get("reason_codes", [])
            if ("message" in error and not isinstance(error["message"], str)
                    or type(error.get("retryable")) is not bool
                    or error["retryable"] != (code in _RETRYABLE)):
                raise ValueError("invalid BNS API error")
            details = _details(code, error.get("details"), provider=True)
            if not isinstance(reasons, list):
                raise ValueError("invalid BNS API reasons")
            if code == "product_not_eligible":
                allowed = ({"MERCHANT_NOT_SUPPORTED", "CATEGORY_PROHIBITED", "SELLER_BLACKLISTED", "UNABLE_TO_ASSESS"}
                           if stage == "resolve" else {"DESTINATION_PROHIBITED", "PREORDER_NOT_SUPPORTED"})
                if not reasons or any(reason not in allowed for reason in reasons):
                    raise ValueError("invalid BNS API reasons")
            elif code in _REASONS and not reasons:
                raise ValueError("missing BNS API reasons")
        if _PROVIDER[stage].get(code) != http_status:
            raise ValueError("invalid BNS provider status")
        return validate_refusal({"schema": SCHEMA, "status": _status(code), "code": code,
                                 "reason_codes": reasons, "retryable": code in _RETRYABLE,
                                 "message": MESSAGES[code], "details": details})
    except (ValueError, TypeError, KeyError):
        return refusal("bns_response_invalid")

"""Offline refusal and quote-only error transport coverage; no business calls."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

from pokemon_index import bns_transport
from pokemon_index.bns_errors import (BNSRefusal, MESSAGES, normalize_variants, refusal,
                                      sanitize_provider_error, validate_refusal)

BASE = "https://bns.partner.example.com"
SECRET = "private-fixture-secret-never-display"
VARIANT = {"variant_key": "sku_884213", "availability": "in_stock",
           "options": {"color": "Black", "size": "M"}, "price": {"currency": "KRW", "subunit_amount": 129000}}


def error(code, *, reasons=None, retryable=False, details=None):
    result = {"code": code, "message": SECRET, "retryable": retryable}
    if reasons is not None:
        result["reason_codes"] = reasons
    if details is not None:
        result["details"] = details
    return {"error": result}


class BNSRefusalTests(unittest.TestCase):
    def setUp(self):
        self.no_connect = patch("socket.socket.connect", side_effect=AssertionError("offline tests"))
        self.no_connect.start()
        self.addCleanup(self.no_connect.stop)

    def test_all_local_codes_are_fixed_valid_dtos(self):
        for code, message in MESSAGES.items():
            with self.subTest(code=code):
                result = refusal(code)
                self.assertEqual(validate_refusal(result), result)
                self.assertEqual(result["code"], code)
                self.assertEqual(result["message"], message)
                exc = BNSRefusal(result)
                self.assertEqual(str(exc), code)
                self.assertEqual(exc.result, result)

    def test_documented_oauth_errors_ignore_provider_text(self):
        for code, status in (("invalid_request", 400), ("unsupported_grant_type", 400),
                             ("invalid_client", 401), ("server_error", 500)):
            result = sanitize_provider_error(status, {"error": code, "error_description": SECRET,
                                                      "error_uri": "https://example.com/" + SECRET}, stage="oauth")
            self.assertEqual(result["code"], code)
            self.assertNotIn(SECRET, json.dumps(result))
            self.assertEqual(result["retryable"], code == "server_error")

    def test_documented_resolve_refusals_preserve_only_known_reasons(self):
        for reason in ("MERCHANT_NOT_SUPPORTED", "CATEGORY_PROHIBITED", "SELLER_BLACKLISTED", "UNABLE_TO_ASSESS"):
            result = sanitize_provider_error(422, error("product_not_eligible", reasons=[reason]), stage="resolve")
            self.assertEqual(result["status"], "refused")
            self.assertEqual(result["reason_codes"], [reason])
            self.assertNotIn(SECRET, json.dumps(result))

    def test_all_documented_quote_codes_preserve_safe_action_hints(self):
        cases = [(400, "invalid_request", []), (404, "not_found", []), (409, "quote_expired", []),
                 (422, "currency_unsupported", ["CURRENCY_UNSUPPORTED"]),
                 (422, "destination_unsupported", ["DESTINATION_UNSUPPORTED"]),
                 (422, "variant_unavailable", ["VARIANT_NOT_FOUND", "OUT_OF_STOCK"]),
                 (422, "product_not_eligible", ["DESTINATION_PROHIBITED", "PREORDER_NOT_SUPPORTED"]),
                 (422, "quote_limit_exceeded", ["VALUE_EXCEEDS_CEILING"]),
                 (422, "product_not_quotable", []), (424, "merchant_unreachable", [])]
        for status, code, reasons in cases:
            with self.subTest(code=code):
                result = sanitize_provider_error(status, error(code, reasons=reasons,
                                                               retryable=code == "merchant_unreachable"), stage="quote")
                self.assertEqual(result["code"], code)
                self.assertEqual(result["reason_codes"], reasons)
                self.assertEqual(result["retryable"], code == "merchant_unreachable")
                self.assertNotIn(SECRET, json.dumps(result))

    def test_supported_currency_and_current_variant_hints(self):
        payload = error("currency_unsupported", reasons=["CURRENCY_UNSUPPORTED"],
                        details={"supported_currencies": ["HKD", "USD", "JPY"]})
        result = sanitize_provider_error(422, payload, stage="quote")
        self.assertEqual(result["details"], {"supported_currencies": ["HKD", "USD", "JPY"]})
        payload = error("variant_unavailable", reasons=["VARIANT_NOT_FOUND"], details={"variants": [VARIANT]})
        result = sanitize_provider_error(422, payload, stage="quote")
        self.assertEqual(result["details"], {"variants": [VARIANT]})
        self.assertEqual(result["status"], "refused")
        result["details"]["variants"][0]["options"]["size"] = "L"
        self.assertEqual(payload["error"]["details"]["variants"][0]["options"]["size"], "M")

    def test_field_messages_are_replaced_with_static_messages(self):
        payload = error("invalid_request", details={"field_errors": [
            {"field": "destination.state", "message": SECRET},
            {"field": "items[0].quantity", "message": "Do something unsafe: " + SECRET}]})
        result = sanitize_provider_error(400, payload, stage="quote")
        self.assertEqual(result["code"], "invalid_request")
        self.assertEqual(result["details"]["field_errors"], [
            {"field": "destination.state", "message": "Choose a two-letter US state code."},
            {"field": "items[0].quantity", "message": "Use quantity one."}])
        self.assertNotIn(SECRET, json.dumps(result))

    def test_unknown_malformed_and_wrong_stage_errors_fail_closed(self):
        cases = [None, [], SECRET, {}, {"error": SECRET}, error("unknown_provider_code"),
                 error("merchant_unreachable", retryable=False), error("invalid_request", retryable=True),
                 error("variant_unavailable", reasons=[SECRET]), error("variant_unavailable", reasons=[]),
                 error("product_not_eligible", reasons=["MERCHANT_NOT_SUPPORTED"]),
                 error("invalid_request", details={"unknown": SECRET}),
                 error("invalid_request", details={"field_errors": [{"field": SECRET, "message": SECRET}]}),
                 error("currency_unsupported", reasons=["CURRENCY_UNSUPPORTED"],
                       details={"supported_currencies": ["USD", "USD"]}),
                 {**error("invalid_request"), "debug": SECRET},
                 {"error": {**error("invalid_request")["error"], "debug": SECRET}}]
        for payload in cases:
            with self.subTest(payload=payload):
                result = sanitize_provider_error(422, payload, stage="quote")
                self.assertEqual(result["code"], "bns_response_invalid")
                self.assertEqual(result["status"], "unavailable")
                self.assertNotIn(SECRET, json.dumps(result))
        result = sanitize_provider_error(400, error("invalid_request"), stage="resolve")
        self.assertEqual(result["code"], "bns_response_invalid")

    def test_strict_dto_rejects_new_fields_provider_messages_and_mutated_flags(self):
        valid = refusal("variant_selection_required", details={"variants": [VARIANT]})
        self.assertEqual(valid["status"], "variant_selection_required")
        for change in ({"debug": SECRET}, {"message": SECRET}, {"retryable": True}, {"status": "refused"},
                       {"reason_codes": [SECRET]}, {"code": SECRET}, {"schema": "unknown"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_refusal(valid | change)
        self.assertEqual(refusal(SECRET)["code"], "bns_unavailable")

    def test_variant_choices_are_bounded_unique_and_strict(self):
        self.assertEqual(normalize_variants([VARIANT]), [VARIANT])
        bad = [[], [VARIANT] * 26, [VARIANT, VARIANT], [VARIANT | {"debug": SECRET}],
               [VARIANT | {"variant_key": "https://example.com/unsafe"}],
               [VARIANT | {"options": {"size": "M\n"}}], [VARIANT | {"options": {str(i): "X" for i in range(9)}}],
               [VARIANT | {"availability": {}}], [VARIANT | {"availability": "PREORDER"}],
               [VARIANT | {"price": {"currency": "JPY", "subunit_amount": True}}],
               [VARIANT | {"price": {"currency": "JPY", "subunit_amount": -1}}],
               [VARIANT | {"price": {"currency": "JPY", "subunit_amount": 10**12 + 1}}],
               [VARIANT | {"price": {"currency": "usd", "subunit_amount": 1}}]]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_variants(value)

    def _sender(self, status, body, *, stage="quote"):
        wire = []
        index = ("oauth", "resolve", "quote").index(stage)
        def transport(request, **bounds):
            wire.append((request.full_url, bounds))
            if len(wire) - 1 == index:
                return {"status": status, "body": body}
            return {"status": 200, "body": {"access_token": "fixture-token"}}
        sender = bns_transport.OneShotBNSSender(BASE, authorized=True, transport=transport)
        for path in bns_transport.BNS_PATHS[:index]:
            sender(Request(BASE + path, data=b"{}", method="POST"))
        data = (json.dumps({"items": [{"quantity": 1}], "destination": {"country": "HK"}}).encode()
                if index == 2 else b"{}")
        return sender, Request(BASE + bns_transport.BNS_PATHS[index], data=data, method="POST"), wire

    def test_sender_preserves_documented_refusal_and_does_not_retry(self):
        sender, request, wire = self._sender(424, error("merchant_unreachable", retryable=True))
        with self.assertRaises(BNSRefusal) as caught:
            sender(request)
        self.assertEqual(caught.exception.result["code"], "merchant_unreachable")
        self.assertEqual(len(wire), 3)
        self.assertEqual(sender.requests, list(bns_transport.BNS_PATHS))
        self.assertTrue(all(bounds["max_bytes"] == 65536 and bounds["timeout"] <= 5 for _, bounds in wire))
        with self.assertRaises(bns_transport.ProbeError):
            sender(request)
        self.assertEqual(len(wire), 3)

    def test_oauth_401_stops_without_token_refresh_or_resolve(self):
        sender, request, wire = self._sender(401, {"error": "invalid_client", "error_description": SECRET}, stage="oauth")
        with self.assertRaises(BNSRefusal) as caught:
            sender(request)
        self.assertEqual(caught.exception.code, "invalid_client")
        self.assertEqual(len(wire), 1)
        self.assertNotIn(SECRET, str(caught.exception))

    def test_malformed_oversized_duplicate_or_deep_json_is_not_propagated(self):
        bodies = [SECRET, b"<html>" + SECRET.encode(), b"x" * 65537,
                  b'{"error":{},"error":{}}', b'{"error":' + b'[' * 9 + b'0' + b']' * 9 + b'}',
                  b'{"error":{"code":"merchant_unreachable","retryable":NaN}}']
        for body in bodies:
            with self.subTest(size=len(body)):
                sender, request, wire = self._sender(424, body)
                with self.assertRaises(BNSRefusal) as caught:
                    sender(request)
                self.assertEqual(caught.exception.code, "bns_response_invalid")
                self.assertNotIn(SECRET, json.dumps(caught.exception.result))
                self.assertEqual(len(wire), 3)

    def test_empty_auth_rate_limit_and_redirect_refusals_are_safe(self):
        for status, expected in ((401, "bns_access_rejected"), (403, "bns_access_rejected"),
                                 (429, "bns_rate_limited"), (302, "bns_http_rejected")):
            sender, request, wire = self._sender(status, b"", stage="oauth")
            with self.assertRaises(BNSRefusal) as caught:
                sender(request)
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(len(wire), 1)

    def test_https_reads_bounded_json_error_only_and_never_redirect_body(self):
        for status, content_type, expected_read in ((422, "application/json; charset=utf-8", True),
                                                    (403, "text/html", False), (302, "application/json", False)):
            with self.subTest(status=status):
                body = json.dumps(error("product_not_eligible", reasons=["MERCHANT_NOT_SUPPORTED"])).encode()
                response = SimpleNamespace(status=status, getheader=Mock(return_value=content_type), read=Mock(return_value=body))
                connection = SimpleNamespace(request=Mock(), getresponse=lambda: response, close=Mock())
                with patch.object(bns_transport, "_PinnedHTTPS", return_value=connection):
                    result = bns_transport._bns_https(Request(BASE + "/v1/products/resolve", data=b"{}", method="POST"),
                                                      timeout=5, max_bytes=65536)
                self.assertEqual(result, {"status": status, "body": body if expected_read else b""})
                if expected_read:
                    response.read.assert_called_once_with(65537)
                else:
                    response.read.assert_not_called()
                connection.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()

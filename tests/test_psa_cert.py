"""PSA fixtures exercise record lookup without querying a real certificate."""
import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from urllib import error

from pokemon_index.psa_cert import BASE_URL, PSACertClient, _NoRedirect, _https_get, compare_record


CERT = "00001234"
TOKEN = "offline-fixture-token-do-not-expose"
PAYLOAD = {"PSACert": {"CertNumber": CERT, "Year": "2023", "Brand": "POKEMON JAPANESE SV2a",
    "Subject": "PIKACHU", "CardNumber": "173", "Variety": "ART RARE", "CardGrade": "10",
    "GradeDescription": "GEM MT 10", "ItemStatus": ""}}


class Clock:
    def __init__(self):
        self.instant = datetime(2026, 10, 21, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.instant.isoformat()

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)


class PSACertificateTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.payload = copy.deepcopy(PAYLOAD)
        self.calls = []
        self.network = patch("socket.create_connection", side_effect=AssertionError("no real network"))
        self.network.start()
        self.connect = patch("socket.socket.connect", side_effect=AssertionError("no real network"))
        self.connect.start()

    def tearDown(self):
        self.connect.stop()
        self.network.stop()

    def transport(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return {"status": 200, "body": copy.deepcopy(self.payload)}

    def client(self, **kwargs):
        return PSACertClient(token=TOKEN, allow_live=True, transport=self.transport, now=self.clock, **kwargs)

    def test_disabled_and_unconfigured_are_explicit_without_transport(self):
        for token, live, reason in ((TOKEN, False, "live_disabled"), (None, True, "access_unconfigured")):
            with self.subTest(reason=reason):
                client = PSACertClient(token=token, allow_live=live, transport=self.transport, now=self.clock)
                result = client.lookup(CERT)
                self.assertFalse(client.configured())
                self.assertEqual((result["status"], result["reason"]), ("unavailable", reason))
        self.assertEqual(self.calls, [])

    def test_certificate_input_is_bounded_ascii_string_and_never_coerced(self):
        client = self.client()
        for cert in (None, 12345678, True, {}, [], "", "123456", "1" * 13, " 12345678", "12345678\n",
                     "１２３４５６７８", "1234567/", "12345678?next=https://evil.invalid"):
            with self.subTest(cert=cert):
                result = client.lookup(cert)
                self.assertEqual((result["status"], result["reason"]), ("invalid", "invalid_certificate_number"))
                self.assertIsNone(result["certificate_number"])
        self.assertEqual(self.calls, [])

    def test_exact_documented_get_preserves_zeros_and_exposes_no_credentials(self):
        client = self.client()
        result = client.lookup(CERT)
        self.assertTrue(client.configured())
        self.assertEqual(result["schema"], "pokemon.psa-cert.v1")
        self.assertEqual(result["status"], "found")
        self.assertTrue(result["record_found"])
        self.assertEqual(result["record"]["certificate_number"], CERT)
        self.assertEqual(result["comparison"]["status"], "not_compared")
        self.assertEqual(self.calls[0][0], BASE_URL + CERT)
        self.assertEqual(self.calls[0][1]["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assertEqual(self.calls[0][1]["timeout"], 8)
        self.assertEqual(self.calls[0][1]["max_bytes"], 65_536)
        for key in ("certificate_verified", "authenticity_verified", "physical_authenticity_verified"):
            self.assertIs(result[key], False)
        self.assertNotIn(TOKEN, json.dumps(result))
        self.assertNotIn("Authorization", json.dumps(result))

    def test_documented_success_and_negative_envelopes_check_body_not_http_only(self):
        self.payload |= {"IsValidRequest": True, "ServerMessage": "Request successful"}
        self.assertEqual(self.client().lookup(CERT)["status"], "found")
        for valid, message, expected in ((False, "Invalid CertNo", "invalid"),
                                          (True, "No data found", "not_found")):
            self.payload = {"IsValidRequest": valid, "ServerMessage": message, "PSACert": None}
            result = self.client().lookup(CERT)
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["record_found"])
            self.assertIsNone(result["record"])

    def test_success_requires_exact_certificate_and_real_psa_card_record(self):
        for cert in ("00001235", 1234, "1234", None):
            with self.subTest(cert=cert):
                self.payload = copy.deepcopy(PAYLOAD)
                self.payload["PSACert"]["CertNumber"] = cert
                result = self.client().lookup(CERT)
                self.assertEqual((result["status"], result["reason"]), ("unavailable", "certificate_number_mismatch"))
                self.assertIsNone(result["record"])
                self.assertFalse(result["record_found"])
        for payload in ({}, {"DNACert": {"CertNumber": CERT}}, {"PSACert": None},
                        {"PSACert": {"CertNumber": CERT, "CardGrade": "10"}},
                        {"PSACert": {"CertNumber": CERT, "Subject": "PIKACHU"}}):
            with self.subTest(payload=payload):
                self.payload = payload
                self.assertEqual(self.client().lookup(CERT)["reason"], "provider_response_invalid")

    def test_envelope_conflicts_and_unknown_messages_fail_closed(self):
        for fields in ({"IsValidRequest": False}, {"IsValidRequest": "true"},
                       {"IsValidRequest": True, "ServerMessage": "No data found"},
                       {"ServerMessage": "Request successful"},
                       {"IsValidRequest": True, "ServerMessage": "Token expired: " + TOKEN}):
            with self.subTest(fields=fields):
                self.payload = copy.deepcopy(PAYLOAD) | fields
                result = self.client().lookup(CERT)
                self.assertEqual(result["reason"], "provider_response_invalid")
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_compare_fields_separately_and_do_not_claim_authenticity(self):
        client = self.client()
        expected = {"subject": " Pikachu ", "grade": "10.0", "year": "2023", "card_number": "173"}
        result = client.lookup(CERT, expected=expected)
        self.assertEqual(result["comparison"]["status"], "matched")
        self.assertEqual(set(result["comparison"]["matched_fields"]), set(expected))
        self.assertFalse(result["certificate_verified"])
        result = client.lookup(CERT, expected={"subject": "CHARIZARD", "grade": "9"})
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["comparison"]["mismatched_fields"], ["subject", "grade"])
        self.assertTrue(result["record_found"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(client.lookup(CERT)["comparison"]["status"], "not_compared")

    def test_comparisons_are_explicit_no_fuzzy_title_fraction_or_qualifier_matching(self):
        for actual, expected, match in (("GEM MT 10", "10", True), ("GEM-MT 10", "10", True),
                                        ("MINT 9", "9", True), ("GEM MT 10 (OC)", "10", False),
                                        ("Authentic", "10", False), ("10", "9", False)):
            with self.subTest(actual=actual):
                result = compare_record({"grade": actual}, {"grade": expected})
                self.assertEqual(result["status"], "matched" if match else "mismatch")
        result = compare_record({"card_number": "173", "subject": "PIKACHU"},
                                {"card_number": "173/165", "subject": "Pikachu PSA 10"})
        self.assertEqual(result["mismatched_fields"], ["subject", "card_number"])
        result = self.client().lookup(CERT, expected={"variety": "ART RARE", "item_status": "valid"})
        self.assertEqual(result["reason"], "invalid_expectation")

    def test_missing_compared_fields_are_inconclusive_not_matched(self):
        self.payload["PSACert"]["Year"] = None
        result = self.client().lookup(CERT, expected={"year": "2023", "grade": "10"})
        self.assertEqual(result["status"], "found")
        self.assertEqual(result["comparison"], {"status": "inconclusive", "matched_fields": ["grade"],
                          "mismatched_fields": [], "missing_fields": ["year"]})

    def test_invalid_expected_fields_do_not_fetch(self):
        for expected in ("PIKACHU", [], {"access_token": TOKEN}, {"grade": 10}, {"subject": ""},
                         {"subject": "a" * 257}, {"subject": "PIKA\nCHU"}):
            with self.subTest(expected=expected):
                result = self.client().lookup(CERT, expected=expected)
                self.assertEqual(result["reason"], "invalid_expectation")
        self.assertEqual(self.calls, [])

    def test_cache_is_expiring_bounded_and_does_not_share_comparison_or_mutable_results(self):
        client = self.client(cache_seconds=5, max_cache_entries=1)
        first = client.lookup(CERT, expected={"grade": "9"})
        first["record"]["grade"] = "99"
        first["comparison"]["mismatched_fields"].append("subject")
        self.clock.advance(4)
        cached = client.lookup(CERT, expected={"grade": "10"})
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["record"]["grade"], "10")
        self.assertEqual(cached["comparison"]["status"], "matched")
        self.assertEqual(cached["checked_at"], first["checked_at"])
        self.clock.advance(1)
        self.assertFalse(client.lookup(CERT)["cached"])
        self.assertEqual(len(self.calls), 2)
        self.payload["PSACert"]["CertNumber"] = "00001235"
        client.lookup("00001235")
        self.assertEqual(len(client._cache), 1)
        self.payload["PSACert"]["CertNumber"] = CERT
        client.lookup(CERT)
        self.assertEqual(len(self.calls), 4)

    def test_request_rate_is_bounded_including_failed_lookups_and_cached_records_are_allowed(self):
        client = self.client(max_requests=1, request_window_seconds=5)
        self.assertEqual(client.lookup(CERT)["status"], "found")
        self.assertTrue(client.lookup(CERT)["cached"])
        self.assertEqual(client.lookup("00001235")["reason"], "lookup_rate_limited")
        self.assertEqual(len(self.calls), 1)
        self.clock.advance(5)
        self.payload = {"IsValidRequest": True, "ServerMessage": "No data found"}
        self.assertEqual(client.lookup("00001235")["status"], "not_found")
        self.assertEqual(client.lookup("00001235")["reason"], "lookup_rate_limited")

    def test_no_stale_cache_on_clock_rollback_or_provider_delay(self):
        client = self.client(cache_seconds=5)
        client.lookup(CERT)
        self.clock.advance(-1)
        result = client.lookup(CERT)
        self.assertFalse(result["record_found"])
        self.assertFalse(result["cached"])
        self.clock.advance(1)
        def slow(*args, **kwargs):
            self.clock.advance(6)
            return {"status": 200, "body": PAYLOAD}
        client = self.client(cache_seconds=5)
        client._transport = slow
        self.assertFalse(client.lookup(CERT)["record_found"])

    def test_busy_lookup_fails_bounded_without_second_transport(self):
        client = self.client()
        client._lock.acquire()
        try:
            result = client.lookup(CERT)
            self.assertEqual(result["reason"], "lookup_busy")
            self.assertEqual(self.calls, [])
        finally:
            client._lock.release()

    def test_malformed_oversized_deep_or_unsafe_responses_are_redacted(self):
        bodies = ["not json", b"\xff", [], '[]', 'null', '{"PSACert":{},"PSACert":{}}',
                  '{"x":NaN}', '[' * 10 + '0' + ']' * 10, 'x' * 1025]
        for body in bodies:
            with self.subTest(body=repr(body)[:80]):
                client = self.client(max_bytes=1024)
                client._transport = lambda *a, **k: {"status": 200, "body": body}
                self.assertEqual(client.lookup(CERT)["reason"], "provider_response_invalid")
        for field in ("Subject", "CardGrade", "Brand"):
            for value in (42, True, [], "x" * 257, "secret\n" + TOKEN):
                with self.subTest(field=field, value=type(value).__name__):
                    self.payload = copy.deepcopy(PAYLOAD)
                    self.payload["PSACert"][field] = value
                    result = self.client().lookup(CERT)
                    self.assertEqual(result["reason"], "provider_response_invalid")
                    self.assertNotIn(TOKEN, json.dumps(result))

    def test_http_errors_timeouts_and_unexpected_exceptions_are_redacted(self):
        for status, reason in ((401, "provider_unauthorized"), (403, "provider_unauthorized"),
                               (429, "provider_rate_limited"), (500, "provider_unavailable"),
                               (302, "provider_unavailable"), (204, "provider_unavailable")):
            with self.subTest(status=status):
                client = self.client()
                client._transport = lambda *a, **k: {"status": status, "body": TOKEN}
                result = client.lookup(CERT)
                self.assertEqual(result["reason"], reason)
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_success_record_reflecting_token_fails_closed_without_exposing_it(self):
        for field in ("Subject", "CardNumber", "Year", "Brand", "Variety", "CardGrade", "GradeDescription", "ItemStatus"):
            with self.subTest(field=field):
                self.payload = copy.deepcopy(PAYLOAD)
                self.payload["PSACert"][field] = "Reflected " + TOKEN
                client = self.client()
                result = client.lookup(CERT)
                self.assertEqual(result["reason"], "provider_response_invalid")
                self.assertIsNone(result["record"])
                self.assertNotIn(TOKEN, json.dumps(result))
                self.assertEqual(len(client._cache), 0)

    def test_transport_exceptions_never_expose_token(self):
        for exc, reason in ((TimeoutError(TOKEN), "provider_timeout"),
                            (error.URLError(TimeoutError(TOKEN)), "provider_timeout"),
                            (error.URLError(TOKEN), "provider_unavailable"),
                            (RuntimeError(TOKEN), "provider_unavailable")):
            with self.subTest(exception=type(exc).__name__):
                def fail(*args, **kwargs):
                    raise exc
                client = self.client()
                client._transport = fail
                result = client.lookup(CERT)
                self.assertEqual(result["reason"], reason)
                self.assertNotIn(TOKEN, json.dumps(result))

    def test_redirect_handler_never_forwards_bearer_token(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.invalid/"))

    def test_transport_constructs_get_and_enforces_content_type_length_and_url(self):
        class Headers:
            length = None
            content_type = "application/json"
            def get(self, _key):
                return self.length
            def get_content_type(self):
                return self.content_type
        class Response:
            status = 200
            headers = Headers()
            url = BASE_URL + CERT
            read_size = None
            def geturl(self):
                return self.url
            def read(self, size):
                self.read_size = size
                return b'{}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        response = Response()
        class Opener:
            def open(self, req, timeout):
                self.req, self.timeout = req, timeout
                return response
        opener = Opener()
        with patch("pokemon_index.psa_cert.request.build_opener", return_value=opener):
            result = _https_get(BASE_URL + CERT, headers={"Authorization": "Bearer " + TOKEN}, timeout=3, max_bytes=1024)
            self.assertEqual(result["status"], 200)
            self.assertEqual(opener.req.get_method(), "GET")
            self.assertEqual(response.read_size, 1025)
            for change in ({"url": "https://evil.invalid/"}, {"length": "1025"},
                           {"length": "bad"}, {"content_type": "text/html"}):
                with self.subTest(change=change):
                    response.url = BASE_URL + CERT
                    response.headers.length, response.headers.content_type = None, "application/json"
                    for field, value in change.items():
                        setattr(response if field == "url" else response.headers, field, value)
                    with self.assertRaises(ValueError):
                        _https_get(BASE_URL + CERT, headers={}, timeout=3, max_bytes=1024)

    def test_bounds_and_header_injection_token_fail_at_configuration(self):
        for changes in ({"token": "x\r\nAuthorization: other"}, {"token": ""}, {"token": 1},
                        {"token": "x" * 8193}, {"allow_live": 1}, {"timeout": 30},
                        {"max_bytes": 10}, {"max_cache_entries": 0}, {"cache_seconds": 0},
                        {"max_requests": 100}, {"request_window_seconds": 0}):
            with self.subTest(changes={key: type(value).__name__ for key, value in changes.items()}):
                config = {"token": TOKEN, "allow_live": True} | changes
                with self.assertRaises(ValueError):
                    PSACertClient(**config)


if __name__ == "__main__":
    unittest.main()

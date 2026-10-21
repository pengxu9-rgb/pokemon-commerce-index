"""One-certificate smoke preparation, entirely offline and network denied."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from pokemon_index.provider_smoke import psa_smoke
from pokemon_index.psa_cert import BASE_URL, PSACertClient, compare_record


CERT = "00001234"  # Synthetic only; never submitted to PSA by these tests.
TOKEN = "offline-smoke-token-never-log"
EXPECTED = {"subject": "PIKACHU", "card_number": "173", "year": "2023",
            "brand": "POKEMON JAPANESE SV2a", "grade": "10", "variety": "ART RARE"}


class Clock:
    def __init__(self):
        self.instant = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.instant.isoformat()


class RecordingClient:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def lookup(self, certificate_number, *, expected):
        self.calls.append((certificate_number, copy.deepcopy(expected)))
        return copy.deepcopy(self.result)


class ProviderSmokePSATests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.no_connection = patch("socket.create_connection", side_effect=AssertionError("network prohibited"))
        self.no_connect = patch("socket.socket.connect", side_effect=AssertionError("network prohibited"))
        self.no_connection.start()
        self.no_connect.start()
        self.addCleanup(self.no_connection.stop)
        self.addCleanup(self.no_connect.stop)

    def evidence(self):
        record = {"certificate_number": CERT} | EXPECTED
        return {"schema": "pokemon.psa-cert.v1", "provider": "psa", "status": "found",
                "certificate_number": CERT, "record_found": True, "record": record,
                "cached": False, "checked_at": self.clock(),
                "expires_at": (self.clock.instant + timedelta(seconds=300)).isoformat(),
                "comparison": compare_record(record, EXPECTED), "certificate_verified": False,
                "authenticity_verified": False, "physical_authenticity_verified": False}

    def run_smoke(self, client, *, expected=None, certificate=CERT, authorized=True):
        return psa_smoke(certificate, EXPECTED if expected is None else expected,
                         client=client, authorized=authorized, now=self.clock)

    def assert_redacted(self, report):
        encoded = json.dumps(report)
        for secret in (CERT, TOKEN, EXPECTED["subject"], EXPECTED["brand"], "Authorization", "Bearer "):
            self.assertNotIn(secret, encoded)
        self.assertNotIn("record", report)
        self.assertFalse(report["order_created"])
        self.assertFalse(report["purchasable"])
        self.assertIsNone(report["purchase_action"])
        self.assertFalse(report["physical_authenticity_verified"])

    def test_default_and_non_boolean_authorization_never_touch_client(self):
        class UntouchableClient:
            def __getattribute__(self, _name):
                raise AssertionError("unauthorized smoke must not inspect client")
        for authorization in (False, None, 1, "true"):
            with self.subTest(authorization=authorization):
                report = self.run_smoke(UntouchableClient(), authorized=authorization)
                self.assertEqual((report["status"], report["reason"]), ("blocked", "live_not_authorized"))
                self.assertEqual(report["lookup_calls"], 0)
                self.assertEqual(report["request_budget"], 1)
                self.assert_redacted(report)

    def test_preflight_requires_one_ascii_cert_and_full_expected_identity(self):
        client = RecordingClient(self.evidence())
        for certificate in (None, 12345678, "123456", "1" * 13, "１２３４５６７８", "12345678/", " 12345678"):
            with self.subTest(certificate=certificate):
                report = self.run_smoke(client, certificate=certificate)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["lookup_calls"], 0)
        for field in ("subject", "card_number", "year", "brand", "grade"):
            with self.subTest(missing_field=field):
                expected = dict(EXPECTED)
                del expected[field]
                self.assertEqual(self.run_smoke(client, expected=expected)["status"], "blocked")
        for expected in ({}, [], "Pikachu", EXPECTED | {"expected_verified": True},
                         EXPECTED | {"grade": 10}, EXPECTED | {"subject": ""},
                         EXPECTED | {"brand": "a" * 257}, EXPECTED | {"subject": "PIKA\nCHU"}):
            with self.subTest(expected=type(expected).__name__):
                report = self.run_smoke(client, expected=expected)
                self.assertEqual(report["status"], "blocked")
                self.assertEqual(report["lookup_calls"], 0)
        self.assertEqual(client.calls, [])

    def test_one_known_record_is_compared_locally_without_second_lookup(self):
        client = RecordingClient(self.evidence())
        report = self.run_smoke(client)
        self.assertEqual(report["status"], "passed")
        self.assertIsNone(report["reason"])
        self.assertEqual(client.calls, [(CERT, EXPECTED)])
        self.assertEqual((report["request_budget"], report["lookup_calls"]), (1, 1))
        self.assertEqual(report["certificate_ref"], hashlib.sha256(CERT.encode()).hexdigest())
        self.assertEqual(set(report["checks"]["matched_fields"]), set(EXPECTED))
        self.assertTrue(report["checks"]["local_repeat"])
        self.assertTrue(report["checks"]["local_grade_mismatch"])
        self.assert_redacted(report)

    def test_optional_variety_and_recognized_grade_labels_can_pass(self):
        for grade in ("10", "10.0", "GEM MT 10", "9", "MINT 9"):
            with self.subTest(grade=grade):
                expected = {key: value for key, value in EXPECTED.items() if key != "variety"}
                expected["grade"] = grade
                result = self.evidence()
                result["record"]["grade"] = "9" if grade in {"9", "MINT 9"} else "10"
                result["comparison"] = compare_record(result["record"], expected)
                client = RecordingClient(result)
                self.assertEqual(self.run_smoke(client, expected=expected)["status"], "passed")
                self.assertEqual(len(client.calls), 1)

    def test_exact_certificate_provider_status_and_fresh_non_cached_evidence_are_required(self):
        changes = ({"schema": "different"}, {"provider": "seller"}, {"status": "not_found"},
                   {"status": "mismatch"}, {"status": "unavailable"}, {"record_found": False},
                   {"cached": True}, {"certificate_number": "00001235"},
                   {"record": {"certificate_number": "00001235"}}, {"record": None})
        for change in changes:
            with self.subTest(change=change):
                client = RecordingClient(self.evidence() | change)
                report = self.run_smoke(client)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(report["lookup_calls"], 1)
                self.assertEqual(len(client.calls), 1)
                self.assert_redacted(report)

    def test_all_authentication_claims_must_stay_explicitly_false(self):
        for field in ("certificate_verified", "authenticity_verified", "physical_authenticity_verified"):
            for value in (True, None, 0, "false"):
                with self.subTest(field=field, value=value):
                    client = RecordingClient(self.evidence() | {field: value})
                    report = self.run_smoke(client)
                    self.assertEqual(report["status"], "failed")
                    self.assert_redacted(report)

    def test_expired_future_or_malformed_record_times_fail_once(self):
        for changes in ({"expires_at": self.clock()},
                        {"expires_at": (self.clock.instant - timedelta(seconds=1)).isoformat()},
                        {"checked_at": (self.clock.instant + timedelta(seconds=1)).isoformat()},
                        {"checked_at": (self.clock.instant - timedelta(seconds=301)).isoformat()},
                        {"expires_at": (self.clock.instant + timedelta(seconds=301)).isoformat()},
                        {"expires_at": "not a date"}, {"checked_at": "2026-10-21T00:00:00"},
                        {"expires_at": None}):
            with self.subTest(changes=changes):
                client = RecordingClient(self.evidence() | changes)
                report = self.run_smoke(client)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(len(client.calls), 1)
                self.assert_redacted(report)

    def test_full_identity_is_recomputed_instead_of_trusting_provider_comparison(self):
        for field in EXPECTED:
            with self.subTest(field=field):
                result = self.evidence()
                result["record"][field] = "different"
                client = RecordingClient(result)
                report = self.run_smoke(client)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(len(client.calls), 1)
                self.assert_redacted(report)
        result = self.evidence()
        result["comparison"] = {"status": "matched"}
        self.assertEqual(self.run_smoke(RecordingClient(result))["status"], "failed")

    def test_transport_receives_only_one_documented_get_and_no_negative_cert_probe(self):
        calls = []
        def transport(url, **kwargs):
            calls.append((url, kwargs))
            return {"status": 200, "body": {"IsValidRequest": True, "ServerMessage": "Request successful",
                    "PSACert": {"CertNumber": CERT, "Subject": EXPECTED["subject"],
                                "CardNumber": EXPECTED["card_number"], "Year": EXPECTED["year"],
                                "Brand": EXPECTED["brand"], "CardGrade": EXPECTED["grade"],
                                "Variety": EXPECTED["variety"]}}}
        client = PSACertClient(token=TOKEN, allow_live=True, transport=transport, now=self.clock, max_requests=1)
        report = self.run_smoke(client)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], BASE_URL + CERT)
        self.assertLessEqual(calls[0][1]["timeout"], 8)
        self.assertLessEqual(calls[0][1]["max_bytes"], 65536)
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer " + TOKEN)
        self.assert_redacted(report)

    def test_unconfigured_disabled_and_negative_provider_outcomes_do_not_retry(self):
        for token, enabled, expected_calls in ((None, True, 0), (TOKEN, False, 0), (TOKEN, True, 1)):
            calls = []
            def transport(*args, **kwargs):
                calls.append((args, kwargs))
                return {"status": 401, "body": TOKEN}
            client = PSACertClient(token=token, allow_live=enabled,
                                   transport=transport, now=self.clock, max_requests=1)
            report = self.run_smoke(client)
            self.assertIn(report["status"], {"failed", "blocked"})
            self.assertEqual(len(calls), expected_calls)
            self.assert_redacted(report)
        outcomes = ({"status": 429, "body": TOKEN},
                    {"status": 200, "body": {"IsValidRequest": True, "ServerMessage": "No data found"}},
                    {"status": 200, "body": {"IsValidRequest": False, "ServerMessage": "Invalid CertNo"}})
        for outcome in outcomes:
            with self.subTest(status=outcome["status"]):
                calls = []
                def transport(*args, **kwargs):
                    calls.append((args, kwargs))
                    return outcome
                client = PSACertClient(token=TOKEN, allow_live=True, transport=transport, now=self.clock, max_requests=1)
                self.assertEqual(self.run_smoke(client)["status"], "failed")
                self.assertEqual(len(calls), 1)

    def test_unexpected_results_and_exceptions_are_redacted_and_never_retried(self):
        for result in (None, [], TOKEN, {"reason": TOKEN}):
            with self.subTest(result_type=type(result).__name__):
                client = RecordingClient(result)
                report = self.run_smoke(client)
                self.assertEqual(report["status"], "failed")
                self.assertEqual(len(client.calls), 1)
                self.assert_redacted(report)
        class BrokenClient:
            calls = 0
            def lookup(self, *_args, **_kwargs):
                self.calls += 1
                raise TimeoutError(TOKEN + " " + CERT)
        client = BrokenClient()
        report = self.run_smoke(client)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(client.calls, 1)
        self.assert_redacted(report)


if __name__ == "__main__":
    unittest.main()

"""Owner-bound certificate comparison through the commerce service, offline."""
from datetime import datetime, timedelta, timezone
import threading
import unittest

from pokemon_index.commerce_loop import CommerceError, CommerceLoop, FixtureCrawler


class RecordingPSA:
    def __init__(self):
        self.calls = []
        self.on_lookup = lambda: None

    def lookup(self, certificate, expected=None):
        self.calls.append((certificate, expected))
        self.on_lookup()
        return {"status": "unavailable", "certificate_verified": False,
                "authenticity_verified": False}


class Clock:
    def __init__(self):
        self.instant = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def __call__(self):
        return self.instant.isoformat()

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)


class CommercePSATests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.client = RecordingPSA()
        self.loop = CommerceLoop(FixtureCrawler(now=self.clock), psa_client=self.client, now=self.clock)

    def offer(self):
        return self.loop.research("owner", {"card_id": "ja:SV2A:173/165:standard", "query": "Pikachu",
                                            "platforms": ["mercari"]})["offers"][1]

    def test_lookup_is_separate_from_seller_verification(self):
        result = self.loop.psa("owner", {"certificate_number": "12345678"})
        self.assertEqual(self.client.calls, [("12345678", None)])
        self.assertFalse(result["verification"]["certificate_verified"])
        self.assertFalse(result["purchasable"])
        self.assertFalse(result["order_created"])

    def test_expected_grade_comes_from_fresh_server_owned_offer(self):
        report = self.loop.research("owner", {"card_id": "ja:SV2A:173/165:standard", "query": "Pikachu", "platforms": ["mercari"]})
        offer = report["offers"][1]
        self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]})
        self.assertEqual(self.client.calls, [("12345678", {"grade": "10"})])
        self.assertFalse(self.loop._offers[offer["offer_id"]]["offer"]["grade"]["certificate_verified"])

    def test_other_owner_and_client_invented_expectations_are_rejected_before_lookup(self):
        report = self.loop.research("owner", {"card_id": "ja:SV2A:173/165:standard", "query": "Pikachu"})
        for owner, request in (("other", {"certificate_number": "12345678", "offer_id": report["offers"][0]["offer_id"]}),
                               ("owner", {"certificate_number": "12345678", "expected": {"grade": "10"}})):
            with self.subTest(owner=owner, request=request), self.assertRaises(CommerceError):
                self.loop.psa(owner, request)
        self.assertEqual(self.client.calls, [])

    def test_conflicting_listing_certificate_never_reaches_provider(self):
        report = self.loop.research("owner", {"card_id": "ja:SV2A:173/165:standard", "query": "Pikachu"})
        key = report["offers"][0]["offer_id"]
        self.loop._offers[key]["offer"]["certificate_number_claim"] = "87654321"
        with self.assertRaises(CommerceError) as error:
            self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": key})
        self.assertEqual(error.exception.code, "certificate_claim_changed")
        self.assertEqual(self.client.calls, [])

    def test_offer_expired_before_lookup_never_reaches_provider(self):
        offer = self.offer()
        self.clock.advance(300)
        with self.assertRaises(CommerceError) as error:
            self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]})
        self.assertEqual((error.exception.code, error.exception.status), ("offer_unavailable", 409))
        self.assertEqual(self.client.calls, [])

    def test_offer_expiring_during_provider_call_cannot_return_contextual_comparison(self):
        offer = self.offer()
        self.client.on_lookup = lambda: self.clock.advance(300)
        with self.assertRaises(CommerceError) as error:
            self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]})
        self.assertEqual((error.exception.code, error.exception.status), ("offer_unavailable", 409))
        self.assertEqual(self.client.calls, [("12345678", {"grade": "10"})])

    def test_claim_or_offer_binding_changed_during_provider_call_requires_research(self):
        changes = [lambda record: record["offer"]["grade"].update(value="9"),
                   lambda record: record["offer"].update(certificate_number_claim="87654321"),
                   lambda record: record["offer"].update(price_minor=123456),
                   lambda record: record.update(card_id="different-card"),
                   lambda record: record.update(expires=record["expires"] + timedelta(seconds=1))]
        for change in changes:
            with self.subTest(change=change):
                offer = self.offer()
                self.client.on_lookup = lambda: change(self.loop._offers[offer["offer_id"]])
                with self.assertRaises(CommerceError) as error:
                    self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]})
                self.assertEqual((error.exception.code, error.exception.status), ("offer_changed", 409))

    def test_owner_offer_removed_or_reassigned_during_provider_call_is_unavailable(self):
        for reassign in (False, True):
            with self.subTest(reassign=reassign):
                offer = self.offer()
                def change():
                    if reassign:
                        self.loop._offers[offer["offer_id"]]["owner"] = "other"
                    else:
                        del self.loop._offers[offer["offer_id"]]
                self.client.on_lookup = change
                with self.assertRaises(CommerceError) as error:
                    self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]})
                self.assertEqual((error.exception.code, error.exception.status), ("offer_unavailable", 409))

    def test_two_threads_cannot_publish_comparison_after_context_changes(self):
        offer = self.offer()
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def delayed():
            entered.set()
            if not release.wait(2):
                raise AssertionError("test lookup was never released")
        self.client.on_lookup = delayed
        def lookup():
            try:
                outcomes.append(self.loop.psa("owner", {"certificate_number": "12345678", "offer_id": offer["offer_id"]}))
            except CommerceError as exc:
                outcomes.append(exc)
        worker = threading.Thread(target=lookup)
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with self.loop._lock:
                self.loop._offers[offer["offer_id"]]["offer"]["grade"]["value"] = "9"
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], CommerceError)
        self.assertEqual(outcomes[0].code, "offer_changed")

    def test_slow_standalone_lookup_does_not_require_an_offer(self):
        self.client.on_lookup = lambda: self.clock.advance(301)
        result = self.loop.psa("owner", {"certificate_number": "12345678"})
        self.assertEqual(self.client.calls, [("12345678", None)])
        self.assertIn("verification", result)


if __name__ == "__main__":
    unittest.main()

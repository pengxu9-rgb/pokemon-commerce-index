"""No live marketplace, provider, filesystem or history operation is used."""
import contextlib
import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from pokemon_index.ebay_price_pilot import main, run_memory_price_pilot

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
ENV = {"EBAY_CLIENT_ID": "synthetic-client", "EBAY_CLIENT_SECRET": "synthetic-secret",
       "EBAY_PRODUCTION_APPROVED": "true", "EBAY_DISPLAY_APPROVED": "true"}
CARD = "ja:SV2A:173/165:standard"


def item(number):
    native = str(123456789010 + number)
    return {"itemId": f"v1|{native}|0", "itemWebUrl": f"https://www.ebay.com/itm/{native}",
        "title": "Synthetic Pikachu SV2a 173/165 PSA 10", "buyingOptions": ["FIXED_PRICE"],
        "price": {"value": f"{10 + number}.25", "currency": "USD"},
        "seller": {"username": f"synthetic_seller_{number}"},
        "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}],
        "localizedAspects": [{"name": "Professional Grader", "value": "PSA"},
            {"name": "Grade", "value": "10"}, {"name": "Certification Number", "value": "99900194"}]}


class Fake:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [item(n) for n in range(5)]
        self.calls, self.detail_change = [], {}

    def __call__(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "POST":
            return {"access_token": "synthetic-token", "expires_in": 3600}
        if "/search?" in path:
            return {"total": len(self.rows), "itemSummaries": copy.deepcopy(self.rows)}
        native = parse_qs(urlsplit(path).query)["legacy_item_id"][0]
        return copy.deepcopy(next(r for r in self.rows if r["itemId"].split("|")[1] == native)) | self.detail_change


def run(fake, **changes):
    config = dict(card_id=CARD, query="Pikachu 173/165 PSA 10", execute=True,
                  read_until=NOW + timedelta(minutes=10), transport=fake, now=lambda: NOW)
    config.update(changes)
    return run_memory_price_pilot(ENV, **config)


class EbayMemoryPricePilotTests(unittest.TestCase):
    def setUp(self):
        self.network = patch("socket.socket.connect", side_effect=AssertionError("external I/O forbidden"))
        self.network.start()

    def tearDown(self):
        self.network.stop()

    def test_default_plan_cannot_read_provider_even_with_credentials(self):
        fake = Fake()
        result = run_memory_price_pilot(ENV, transport=fake)
        self.assertEqual(result.receipt["status"], "prepared")
        self.assertIsNone(result.report)
        self.assertEqual(fake.calls, [])

    def test_five_asks_use_one_token_search_and_five_refreshes_in_memory(self):
        fake = Fake()
        with patch.object(Path, "write_text", side_effect=AssertionError("no persistence")), \
                patch.object(Path, "write_bytes", side_effect=AssertionError("no persistence")), \
                patch("json.dump", side_effect=AssertionError("no persistence")):
            result = run(fake)
        self.assertEqual(len(fake.calls), 7)
        self.assertEqual(result.receipt["http_budget_reservations"], 7)
        self.assertEqual(result.receipt["status"], "ready_for_review")
        self.assertEqual(result.receipt["mode"], "synthetic_fixture")
        report = result.report
        self.assertEqual(report["mode"], "synthetic_fixture")
        self.assertEqual(len(report["offers"]), 5)
        self.assertEqual({o["price_minor"] for o in report["offers"]}, {1025, 1125, 1225, 1325, 1425})
        self.assertTrue(all(o["synthetic"] for o in report["offers"]))
        self.assertTrue(all(o["grade"]["value"] == "10" and not o["grade"]["certificate_verified"] for o in report["offers"]))
        self.assertTrue(all(o["certificate"]["status"] == "not_checked" for o in report["offers"]))
        self.assertEqual(report["forwarders"], [])
        self.assertFalse(report["purchasable"])
        self.assertFalse(report["order_created"])
        self.assertEqual(parse_qs(urlsplit(fake.calls[1][1]).query)["limit"], ["5"])
        self.assertTrue(all("X-EBAY-C-ENDUSERCTX" not in call[2]["headers"] for call in fake.calls))

    def test_receipt_repr_and_cli_do_not_emit_data_or_credentials(self):
        fake = Fake()
        result = run(fake)
        rendered = json.dumps(result.receipt) + repr(result)
        for text in ["Pikachu", "123456789010", "www.ebay.com", "synthetic-secret", "synthetic-token", "offer_count"]:
            self.assertNotIn(text, rendered)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = main(["--execute", "--card-id", CARD, "--query", "Pikachu PSA 10",
                           "--read-until", "2026-10-27T00:10:00Z"], env=ENV, transport=Fake(), now=lambda: NOW)
        self.assertEqual(status, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value["status"], "ready_for_review")
        self.assertNotIn("offers", value)
        self.assertNotIn("Pikachu", output.getvalue())

    def test_no_credentials_or_any_missing_gate_prevents_all_calls(self):
        for key in ENV:
            fake = Fake()
            bad = dict(ENV); bad.pop(key)
            result = run_memory_price_pilot(bad, execute=True, card_id=CARD, query="Pikachu",
                read_until=NOW + timedelta(minutes=10), transport=fake, now=lambda: NOW)
            self.assertEqual(result.receipt["status"], "blocked")
            self.assertEqual(fake.calls, [])

    def test_invalid_window_or_query_never_reaches_token(self):
        for changes in ({"read_until": NOW}, {"read_until": NOW + timedelta(minutes=16)},
                        {"read_until": "2026-10-27T00:10:00"}, {"query": "x"}, {"card_id": ""}):
            fake = Fake()
            result = run(fake, **changes)
            self.assertEqual(result.receipt["status"], "blocked")
            self.assertEqual(fake.calls, [])

    def test_sandbox_intent_and_endpoint_overrides_cannot_dispatch_production(self):
        for key in ("EBAY_ENVIRONMENT", "EBAY_API_ENVIRONMENT", "EBAY_API_BASE_URL",
                    "EBAY_BASE_URL", "EBAY_BROWSE_BASE_URL", "EBAY_TOKEN_URL", "EBAY_API_URL", "EBAY_SANDBOX"):
            fake = Fake()
            result = run_memory_price_pilot(ENV | {key: "sandbox"}, execute=True, card_id=CARD,
                query="Pikachu", read_until=NOW + timedelta(minutes=10), transport=fake, now=lambda: NOW)
            self.assertEqual(result.receipt["status"], "blocked")
            self.assertEqual(fake.calls, [])
        fake = Fake()
        result = run_memory_price_pilot(ENV | {"EBAY_ENVIRONMENT": "production", "EBAY_API_ENVIRONMENT": "production"},
            execute=True, card_id=CARD, query="Pikachu", read_until=NOW + timedelta(minutes=10), transport=fake, now=lambda: NOW)
        self.assertEqual(result.receipt["status"], "ready_for_review")

    def test_unrelated_storage_and_provider_environment_is_not_consumed(self):
        fake = Fake()
        env = ENV | {"POKEMON_CREATOR_STATE_BUCKET": "not-used", "BNS_PARTNER_CLIENT_SECRET": "not-used",
                     "PSA_API_TOKEN": "not-used", "EBAY_EPN_CAMPAIGN_ID": "not-used"}
        result = run_memory_price_pilot(env, execute=True, card_id=CARD, query="Pikachu",
            read_until=NOW + timedelta(minutes=10), transport=fake, now=lambda: NOW)
        self.assertEqual(result.receipt["status"], "ready_for_review")
        self.assertTrue(all("X-EBAY-C-ENDUSERCTX" not in call[2]["headers"] for call in fake.calls))
        self.assertNotIn("not-used", json.dumps(result.receipt))

    def test_empty_or_unsupported_search_is_not_repeated(self):
        for rows in ([], [item(0) | {"buyingOptions": ["AUCTION"]}]):
            fake = Fake(rows)
            result = run(fake)
            self.assertEqual(len(fake.calls), 2)
            self.assertEqual(result.report["offers"], [])
            self.assertEqual(result.receipt["status"], "partial")

    def test_search_cannot_expand_the_five_item_budget(self):
        fake = Fake([item(n) for n in range(6)])
        result = run(fake)
        self.assertEqual(result.receipt["status"], "blocked")
        self.assertEqual(len(fake.calls), 2)
        self.assertIsNone(result.report)

    def test_unexpected_configuration_or_clock_error_is_sanitized(self):
        fake = Fake()
        def bad_clock():
            raise RuntimeError("private-clock-detail")
        result = run(fake, now=bad_clock)
        self.assertEqual(result.receipt["status"], "blocked")
        self.assertNotIn("private-clock-detail", repr(result) + json.dumps(result.receipt))
        self.assertEqual(fake.calls, [])

    def test_invalid_detail_cannot_become_a_fake_fresh_price(self):
        changes = [{"itemEndDate": "2026-10-26T00:00:00Z"}, {"buyingOptions": ["AUCTION"]},
                   {"itemId": "v1|999999999999|0"}, {"price": {"value": "1.234", "currency": "USD"}}]
        for change in changes:
            fake = Fake(); fake.detail_change = change
            result = run(fake)
            self.assertEqual(result.report["offers"], [])
            self.assertEqual(result.receipt["status"], "partial")
            self.assertEqual(len(fake.calls), 3)  # no retry of unsupported detail

    def test_transport_failure_is_redacted_and_never_retried(self):
        calls = []
        def broken(method, path, **kwargs):
            calls.append(path)
            raise RuntimeError("private token raw-response secret-value")
        result = run(broken)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.receipt["status"], "blocked")
        self.assertNotIn("secret-value", repr(result) + json.dumps(result.receipt))
        self.assertIsNone(result.report)

    def test_expiry_during_search_prevents_any_detail_dispatch(self):
        fake = Fake(); clock = [NOW]
        def expire(method, path, **kwargs):
            value = fake(method, path, **kwargs)
            if "/search?" in path:
                clock[0] = NOW + timedelta(minutes=10)
            return value
        result = run(expire, now=lambda: clock[0])
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(result.receipt["status"], "blocked")
        self.assertIsNone(result.report)

    def test_window_expiring_after_research_discards_report_before_return(self):
        from pokemon_index.commerce_loop import CommerceLoop
        original = CommerceLoop.research
        clock = [NOW]
        def finish_then_expire(loop, *args, **kwargs):
            report = original(loop, *args, **kwargs)
            clock[0] = NOW + timedelta(minutes=10)
            return report
        fake = Fake()
        with patch.object(CommerceLoop, "research", new=finish_then_expire):
            result = run(fake, now=lambda: clock[0])
        self.assertEqual(len(fake.calls), 7)
        self.assertIsNone(result.report)
        self.assertEqual(result.receipt["status"], "blocked")


if __name__ == "__main__":
    unittest.main()

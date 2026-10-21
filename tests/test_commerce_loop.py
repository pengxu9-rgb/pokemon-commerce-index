"""On-demand research stays separate from indexed/verified offer evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from pokemon_index.commerce_loop import (
    BoundBuyShipForwarder, CommerceError, CommerceLoop, FixtureCrawler, SCHEMA,
)

CARD = "ja:SV2A:173/165:standard"


class Clock:
    def __init__(self):
        self.instant = datetime.now(timezone.utc).replace(microsecond=0)

    def __call__(self):
        return self.instant.isoformat()

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)


class Producer:
    def __init__(self, clock):
        self.clock, self.calls = clock, []
        self.row = {"source": "mercari", "native_id": "m1001",
            "url": "https://jp.mercari.com/item/m1001", "title": "Pikachu SV2a 173/165 PSA 10 graded card",
            "price_minor": 12000, "currency": "JPY", "availability": "in_stock", "status": "on_sale",
            "grade_company": "PSA", "grade_value": "10", "scope": "listing",
            "certificate_number_claim": None, "marketplace_quality": {}, "evidence_ref": "test:evidence"}
        self.change = {}

    def detail(self, url):
        self.calls.append(("detail", url))
        return copy.deepcopy(self.row) | {"observed_at": self.clock()} | copy.deepcopy(self.change)

    def search(self, source, query, limit=5):
        self.calls.append(("search", source, query, limit))
        return {"status": "ok", "listings": [copy.deepcopy(self.row) | {"observed_at": self.clock()}]}


class CommerceLoopTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.producer = Producer(self.clock)
        self.loop = CommerceLoop(self.producer, now=self.clock)
        self.network = patch("socket.create_connection", side_effect=AssertionError("no external calls"))
        self.network.start()
        self.connect = patch("socket.socket.connect", side_effect=AssertionError("no external calls"))
        self.connect.start()

    def tearDown(self):
        self.connect.stop()
        self.network.stop()

    def research(self, owner="owner-a", **changes):
        return self.loop.research(owner, {"card_id": CARD, "query": "Pikachu 173/165 PSA 10", "platforms": ["mercari"]} | changes)

    def choose(self, offer=None, owner="owner-a", **changes):
        offer = offer or self.research(owner)["offers"][0]
        return self.loop.select(owner, {"card_id": CARD, "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"],
            "currency": offer["currency"]} | changes)

    def handoff(self, selection=None, owner="owner-a", **changes):
        selection = selection or self.choose()
        return self.loop.handoff(owner, {"selection_id": selection["selection_id"],
            "forwarder": "buyship", "destination": {"country": "HK"}} | changes)

    def test_real_research_selection_manual_handoff_rechecks_original_url(self):
        report = self.research()
        offer = report["offers"][0]
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["mode"], "on_demand_research")
        self.assertEqual(offer["grade"], {"company": "PSA", "value": "10", "certificate_verified": False})
        self.assertEqual(offer["identity_status"], "unverified_candidate")
        selected = self.choose(offer)
        self.assertEqual(len(self.producer.calls), 1)
        self.clock.advance(10)
        result = self.handoff(selected)
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertEqual(result["product_url"], offer["url"])
        self.assertEqual(result["quote_status"], "provider_unconfigured")
        self.assertIsNone(result["quote"])
        self.assertIsNone(result["purchase_action"])
        self.assertFalse(result["order_created"])
        self.assertFalse(result["purchasable"])
        self.assertEqual(self.producer.calls[-1], ("detail", offer["url"]))
        self.assertNotEqual(result["offer"]["observed_at"], offer["observed_at"])

    def test_drift_invalidates_selection_and_does_not_make_provider_call(self):
        changes = [{"price_minor": 13000}, {"currency": "USD"}, {"availability": "unknown"},
            {"status": "sold_out"}, {"status": "unknown"}, {"url": "https://jp.mercari.com/item/m2002"},
            {"title": "Different card 172/165"}, {"grade_value": "9"}, {"native_id": "m2002"},
            {"marketplace_quality": {"seller_condition": "case cracked"}},
            {"certificate_number_claim": "12345678"}, {"scope": "product_summary"}]
        class NoQuote:
            def preview(self, *_args):
                raise AssertionError("changed offers must not reach quote provider")
        self.loop.forwarders["buyship"] = NoQuote()
        for change in changes:
            with self.subTest(change=change):
                self.producer.change = {}
                selection = self.choose()
                self.producer.change = change
                with self.assertRaises(CommerceError) as raised:
                    self.handoff(selection)
                self.assertEqual(raised.exception.code, "offer_changed")
                self.producer.change = {}
                with self.assertRaises(CommerceError) as raised:
                    self.handoff(selection)
                self.assertEqual(raised.exception.code, "selection_expired")

    def test_refreshed_future_stale_or_unsafe_evidence_cannot_handoff(self):
        for change in ({"observed_at": (self.clock.instant + timedelta(seconds=1)).isoformat()},
                       {"observed_at": (self.clock.instant - timedelta(seconds=301)).isoformat()},
                       {"url": "http://127.0.0.1/private"}, {"source": "snkrdunk"}):
            with self.subTest(change=change):
                self.producer.change = {}
                selected = self.choose()
                self.producer.change = change
                with self.assertRaises(CommerceError) as raised:
                    self.handoff(selected)
                self.assertEqual(raised.exception.code, "refresh_unavailable")

    def test_selection_is_owner_card_price_and_observation_bound(self):
        offer = self.research()["offers"][0]
        for changes in ({"card_id": "another-card"}, {"expected_price_minor": 12001},
                        {"expected_observed_at": "2020-01-01T00:00:00Z"}, {"currency": "USD"}):
            with self.subTest(changes=changes), self.assertRaises(CommerceError):
                self.choose(offer, **changes)
        with self.assertRaises(CommerceError):
            self.choose(offer, owner="owner-b")
        selected = self.choose(offer)
        calls = len(self.producer.calls)
        with self.assertRaises(CommerceError):
            self.handoff(selected, owner="owner-b")
        self.assertEqual(len(self.producer.calls), calls)
        self.clock.advance(601)
        with self.assertRaises(CommerceError):
            self.handoff(selected)
        self.assertEqual(len(self.producer.calls), calls)

    def test_stale_offer_selection_does_not_refresh_silently(self):
        offer = self.research()["offers"][0]
        self.clock.advance(301)
        with self.assertRaises(CommerceError):
            self.choose(offer)
        self.assertEqual(len(self.producer.calls), 1)

    def test_unknown_price_stock_and_summary_support_manual_handoff_only(self):
        self.producer.row.update(price_minor=None, currency=None, availability="unknown",
                                 status="unknown", scope="product_summary")
        result = self.handoff()
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertIsNone(result["offer"]["price_minor"])
        self.assertEqual(result["offer"]["scope"], "product_summary")

    def test_sold_out_is_not_selectable(self):
        self.producer.row["status"] = "sold_out"
        with self.assertRaises(CommerceError) as raised:
            self.choose()
        self.assertEqual(raised.exception.code, "offer_unavailable")

    def test_arbitrary_url_and_request_auth_material_are_rejected_before_fetch(self):
        cases = [{"product_urls": ["https://127.0.0.1/private"]}, {"product_urls": ["https://jp.mercari.com/item/m1001?url=https://evil.invalid"]},
                 {"product_urls": ["https://jp.mercari.com@evil.invalid/item/m1001"]}, {"access_token": "do-not-log"},
                 {"product_urls": [{"url": "nested"}]}, {"platforms": ["mercari", "mercari"]}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(CommerceError):
                self.research(**change)
        self.assertEqual(self.producer.calls, [])

    def test_explicit_product_url_fetches_detail_instead_of_search(self):
        self.research(product_urls=[self.producer.row["url"]])
        self.assertEqual(self.producer.calls, [("detail", self.producer.row["url"])])

    def test_partial_failure_has_explicit_source_status_without_invented_offer(self):
        result = self.research(platforms=["mercari", "snkrdunk", "ebay"])
        self.assertEqual(len(result["offers"]), 1)
        self.assertEqual([p["status"] for p in result["platforms"]], ["ok", "unavailable", "unavailable"])

    def test_source_errors_are_redacted(self):
        with patch.object(self.producer, "search", side_effect=ValueError("secret-token")):
            report = self.research()
        self.assertNotIn("secret-token", json.dumps(report))
        self.assertEqual(report["offers"], [])

    def test_fixture_mode_is_explicit_and_cannot_mix_live_urls(self):
        self.loop = CommerceLoop(FixtureCrawler(now=self.clock), now=self.clock)
        result = self.research(platforms=["mercari", "ebay", "snkrdunk"])
        self.assertEqual(len(result["offers"]), 6)
        self.assertEqual(result["mode"], "synthetic_fixture")
        self.assertTrue(all(offer["synthetic"] and ".invalid" in offer["url"] for offer in result["offers"]))
        handoff = self.handoff(self.choose(result["offers"][0]))
        self.assertIn("Synthetic", handoff["message"])
        with self.assertRaises(CommerceError):
            self.research(product_urls=["https://jp.mercari.com/item/m1001"])

    def test_no_real_network_is_enabled_by_default(self):
        from pokemon_index.marketplace_crawl import Crawler
        self.loop = CommerceLoop(Crawler(), now=self.clock)
        result = self.research()
        self.assertEqual(result["offers"], [])
        self.assertEqual(result["platforms"][0]["status"], "blocked")

    def test_actual_crawler_dto_and_microsecond_clock_work_through_handoff(self):
        from pokemon_index.marketplace_crawl import Crawler
        product_url = "https://jp.mercari.com/item/m1001"
        product = {"@type": "Product", "name": "Pikachu 173/165 PSA 10 graded card",
            "offers": {"@type": "Offer", "price": "12000", "priceCurrency": "JPY",
                       "availability": "https://schema.org/InStock", "url": product_url}}
        def fetch(url):
            return {"status": 200, "url": url,
                "headers": {"content-type": "text/plain" if url.endswith("robots.txt") else "text/html"},
                "body": "User-agent: *\nAllow: /\n" if url.endswith("robots.txt") else
                        '<script type="application/ld+json">' + json.dumps(product) + '</script>'}
        self.loop = CommerceLoop(Crawler(fetch=fetch))
        report = self.research(product_urls=[product_url])
        self.assertEqual(len(report["offers"]), 1)
        offer = report["offers"][0]
        self.assertEqual(offer["price_minor"], 12000)
        self.assertEqual(offer["grade"]["value"], "10")
        self.assertEqual(self.handoff(self.choose(offer))["product_url"], product_url)

    def test_destination_and_client_url_fields_are_refused_before_detail(self):
        selected = self.choose()
        calls = len(self.producer.calls)
        for change in ({"destination": {"country": "HK", "address": "do not store"}},
                       {"destination": {"country": "hk"}}, {"url": "https://evil.invalid"},
                       {"forwarder": "unconfigured-arbitrary-provider"}):
            with self.subTest(change=change), self.assertRaises(CommerceError):
                self.handoff(selected, **change)
        self.assertEqual(len(self.producer.calls), calls)

    def test_slow_provider_success_or_failure_cannot_return_stale_evidence(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                clock = self.clock
                class SlowProvider:
                    def preview(self, *_args):
                        clock.advance(301)
                        if fail:
                            raise ValueError("injected provider failure")
                        return {"status": "quote_ready_for_review", "purchasable": False,
                                "purchase_action": None, "order_created": False}
                self.loop.forwarders["buyship"] = SlowProvider()
                selected = self.choose()
                with self.assertRaises(CommerceError) as raised:
                    self.handoff(selected)
                self.assertEqual(raised.exception.code, "offer_expired")
                with self.assertRaises(CommerceError) as raised:
                    self.handoff(selected)
                self.assertEqual(raised.exception.code, "selection_expired")

    def test_handoff_checked_at_is_completion_time(self):
        clock = self.clock
        class Provider:
            def preview(self, *_args):
                clock.advance(10)
                raise ValueError("provider unavailable")
        self.loop.forwarders["buyship"] = Provider()
        result = self.handoff()
        self.assertEqual(result["checked_at"], self.clock())


class IndexedBuyShipTests(unittest.TestCase):
    def setUp(self):
        from pokemon_index import buyship_partner, core
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "operator.sqlite3"
        self.clock = Clock()
        self.producer = Producer(self.clock)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        core.init_db(self.db)
        core.register_source(self.db, {"source": "mercari", "rights_reference": "injected test approval",
            "ingest_allowed": True, "display_allowed": True, "partner_handoff_allowed": True,
            "retention_days": 1, "listing_ttl_hours": 1})
        core.import_cards(self.db, [{"match_eligible": True, "language": "ja", "set_code": "SV2a",
            "collector_number": "173/165", "variant": "standard", "name": "Pikachu", "rarity": "AR",
            "provenance": "synthetic test", "rights_reference": "synthetic test", "display_allowed": True}])
        core.import_observations(self.db, [self.producer.row | {"source": "mercari", "language": "ja",
            "observed_at": self.clock(), "evidence_ref": "synthetic:test:binding"}])
        fixture = json.loads((Path(__file__).parents[1] / "examples/buyship_partner_preview.json").read_text())
        fixture["resolve"]["url"] = self.producer.row["url"]
        fixture["resolve"]["product"]["name"] = self.producer.row["title"]
        fixture["quote"]["expires_at"] = (self.clock.instant + timedelta(minutes=20)).isoformat()
        self.calls = []
        def sender(request):
            self.calls.append(request.full_url.rsplit("/", 1)[-1])
            if request.full_url.endswith("/oauth/token"):
                return 200, {"access_token": "in-memory-test-token", "expires_in": 300}
            return 200, copy.deepcopy(fixture["resolve" if request.full_url.endswith("/resolve") else "quote"])
        self.client = buyship_partner.PartnerClient("https://partner.invalid", "test-client", "test-secret", sender=sender)
        self.loop = CommerceLoop(self.producer, now=self.clock,
            forwarders={"buyship": BoundBuyShipForwarder(self.path, self.client)})
        self.network = patch("socket.create_connection", side_effect=AssertionError("no network"))
        self.network.start()

    def tearDown(self):
        self.network.stop()
        self.db.close()
        self.tmp.cleanup()

    def run_loop(self):
        offer = self.loop.research("owner", {"card_id": CARD, "query": "Pikachu 173/165", "platforms": ["mercari"]})["offers"][0]
        selected = self.loop.select("owner", {"card_id": CARD, "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
        return self.loop.handoff("owner", {"selection_id": selected["selection_id"], "forwarder": "buyship", "destination": {"country": "HK"}})

    def test_configured_provider_reuses_exact_indexed_quote_gate(self):
        result = self.run_loop()
        self.assertEqual(result["status"], "quote_ready_for_review")
        self.assertEqual(self.calls, ["token", "resolve", "quotes"])
        self.assertEqual(result["quote"]["buyship"]["grand_total"], {"currency": "HKD", "subunit_amount": 24060})
        self.assertFalse(result["quote"]["buyer_labels"]["certificate_verified"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM landed_quote").fetchone()[0], 0)

    def test_unmatched_indexed_listing_never_receives_provider_calls(self):
        self.producer.row["price_minor"] = 13000
        result = self.run_loop()
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertEqual(result["quote_status"], "eligible_indexed_quote_unavailable")
        self.assertEqual(self.calls, [])

    def test_unconfirmed_current_research_never_reaches_configured_quote_provider(self):
        changes = ({"availability": "unknown", "status": "unknown"},
                   {"availability": "in_stock", "status": "unknown"},
                   {"availability": "unknown", "status": "on_sale"},
                   {"scope": "product_summary"}, {"price_minor": None},
                   {"price_minor": None, "currency": None})
        original = copy.deepcopy(self.producer.row)
        class ProviderSpy:
            def preview(self, *_args):
                raise AssertionError("unconfirmed research must not reach any provider")
        self.loop.forwarders["buyship"] = ProviderSpy()
        for change in changes:
            with self.subTest(change=change):
                self.producer.row = original | change
                result = self.run_loop()
                self.assertEqual(result["status"], "manual_handoff_required")
                self.assertIsNone(result["quote"])
                self.assertIn(result["quote_status"], {"stock_not_confirmed", "exact_listing_not_established", "native_price_unavailable"})
                self.assertEqual(self.calls, [])

    def test_bound_buyship_defense_rejects_unconfirmed_offer_before_db_or_transport(self):
        forwarder = self.loop.forwarders["buyship"]
        # Exercise the adapter independently of CommerceLoop's provider preflight.
        offer = {"scope": "listing", "availability": "unknown", "listing_status": "unknown",
                 "price_minor": 12000, "currency": "JPY"}
        with self.assertRaises(ValueError):
            forwarder.preview(CARD, offer, {"country": "HK"})
        self.assertEqual(self.calls, [])

    def test_unapproved_source_never_receives_provider_calls(self):
        self.db.execute("UPDATE source_policy SET partner_handoff_allowed=0")
        self.db.commit()
        result = self.run_loop()
        self.assertIsNone(result["quote"])
        self.assertEqual(self.calls, [])

    def test_product_summary_never_becomes_indexed_quote(self):
        self.producer.row["scope"] = "product_summary"
        result = self.run_loop()
        self.assertIsNone(result["quote"])
        self.assertEqual(self.calls, [])

    def test_new_indexed_price_between_selection_binding_and_gate_stops_dispatch(self):
        from pokemon_index import buyship_partner, core
        original = buyship_partner.preview_quote

        def newer_snapshot(db, **kwargs):
            # The writer is a different connection from the adapter and gate.
            self.clock.advance(1)
            core.import_observations(self.db, [copy.deepcopy(self.producer.row) | {
                "language": "ja", "price_minor": 13000, "observed_at": self.clock(),
                "evidence_ref": "synthetic:test:new-price"}])
            self.db.commit()
            return original(db, **kwargs)

        with patch.object(buyship_partner, "preview_quote", side_effect=newer_snapshot), \
                patch.object(core, "utcnow", side_effect=self.clock):
            result = self.run_loop()
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertEqual(result["quote_status"], "eligible_indexed_quote_unavailable")
        self.assertEqual(result["offer"]["price_minor"], 12000)
        self.assertIsNone(result["quote"])
        self.assertEqual(self.calls, [])

    def test_returned_quote_must_bind_selected_ask_and_full_indexed_snapshot(self):
        from pokemon_index import buyship_partner
        original = buyship_partner.preview_quote
        for change in ("ask", "snapshot"):
            with self.subTest(change=change):
                self.calls.clear()

                def changed_preview(db, **kwargs):
                    quote = original(db, **kwargs)
                    if change == "ask":
                        quote["listing"]["ask"]["subunit_amount"] = 13000
                    else:
                        quote["evidence"]["listing_snapshot_sha256"] = "0" * 64
                    # A self-consistent preview binding alone does not prove
                    # that its observation was the user's selected observation.
                    quote["evidence"]["binding_sha256"] = buyship_partner._preview_digest(quote)
                    return quote

                with patch.object(buyship_partner, "preview_quote", side_effect=changed_preview):
                    result = self.run_loop()
                self.assertEqual(result["status"], "manual_handoff_required")
                self.assertIsNone(result["quote"])
                self.assertIn("resolve", self.calls)
                self.assertIn("quotes", self.calls)

    def test_quality_change_after_resolve_stops_quote_dispatch(self):
        from pokemon_index import marketplace_ingest
        marketplace_ingest.initialize(self.db)
        sender = self.client.sender

        def changed(request):
            result = sender(request)
            if request.full_url.endswith("/resolve"):
                quality = {"grade_company": "PSA", "grade_value": "10",
                    "grade_evidence": "structured_seller_claim", "seller_condition": "case cracked",
                    "evidence_ref": "synthetic:test:binding", "certificate_verified": False,
                    "authenticity_verified": False}
                self.db.execute("INSERT INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                    ("mercari", "m1001", self.clock(), json.dumps(quality), "synthetic:test:binding"))
                self.db.commit()
            return result

        self.client.sender = changed
        result = self.run_loop()
        self.assertEqual(self.calls, ["token", "resolve"])
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertIsNone(result["quote"])

    def test_quote_expiring_during_post_provider_quality_check_is_suppressed(self):
        from pokemon_index import core
        sender = self.client.sender
        quality_binding = BoundBuyShipForwarder._quality_binding

        def expiring(request):
            status, body = sender(request)
            if request.full_url.endswith("/quotes"):
                body["expires_at"] = (self.clock.instant + timedelta(seconds=1)).isoformat()
            return status, body

        def slow_quality(*args):
            result = quality_binding(*args)
            if self.calls and self.calls[-1] == "quotes":
                self.clock.advance(2)
            return result

        self.client.sender = expiring
        with patch.object(core, "utcnow", side_effect=self.clock), \
                patch.object(BoundBuyShipForwarder, "_quality_binding", side_effect=slow_quality):
            result = self.run_loop()
        self.assertEqual(self.calls, ["token", "resolve", "quotes"])
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertEqual(result["quote_status"], "eligible_indexed_quote_unavailable")
        self.assertEqual(result["checked_at"], self.clock())
        self.assertIsNone(result["quote"])

    def test_bound_client_keeps_transport_marker_and_live_authorization(self):
        from pokemon_index import buyship_partner
        result = self.run_loop()
        self.assertEqual(result["quote"]["evidence"]["mode"], "injected_test_transport")
        self.calls.clear()
        self.client.sender = buyship_partner._json_request
        self.client.live_authorized = False
        with patch("socket.socket.connect", side_effect=AssertionError("no network")):
            result = self.run_loop()
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertIsNone(result["quote"])
        self.assertEqual(self.calls, [])

    def test_quality_mutation_during_provider_call_suppresses_quote(self):
        from pokemon_index import marketplace_ingest
        marketplace_ingest.initialize(self.db)
        sender = self.client.sender
        def changed(request):
            result = sender(request)
            if request.full_url.endswith("/quotes"):
                quality = {"grade_company": "PSA", "grade_value": "10",
                    "grade_evidence": "structured_seller_claim", "seller_condition": "case cracked",
                    "evidence_ref": "synthetic:test:binding", "certificate_verified": False,
                    "authenticity_verified": False}
                self.db.execute("INSERT INTO marketplace_observation_quality VALUES (?,?,?,?,?)",
                    ("mercari", "m1001", self.clock(), json.dumps(quality), "synthetic:test:binding"))
                self.db.commit()
            return result
        self.client.sender = changed
        result = self.run_loop()
        self.assertEqual(self.calls, ["token", "resolve", "quotes"])
        self.assertIsNone(result["quote"])
        self.assertEqual(result["quote_status"], "eligible_indexed_quote_unavailable")


if __name__ == "__main__":
    unittest.main()

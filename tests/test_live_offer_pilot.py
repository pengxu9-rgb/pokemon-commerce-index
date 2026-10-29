"""Read-only source/quote integration and revocation; all provider boundaries fake."""
import copy
from datetime import timedelta
import io
import json
import socket
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pokemon_index import bns_url_preview, commerce_service
from pokemon_index.approved_sources import ApprovedSources, SourceWiringError
from pokemon_index.dispatch_budget import DispatchBudget
from pokemon_index.marketplace_crawl import Crawler, PublicHTMLFetch
from pokemon_index.source_readiness import source_readiness
from tests.live_offer_rehearsal import CARD, URL, Pilot, policy, rehearsal


class LiveOfferPilotTests(unittest.TestCase):
    def test_real_http_full_journey_has_two_sellers_photos_grade_choice_and_bound_quote(self):
        report = rehearsal()
        research, handoff = report["research"], report["handoff"]
        self.assertEqual(len(research["offers"]), 2)
        self.assertEqual(len({o["seller"]["id"] for o in research["offers"]}), 2)
        for offer in research["offers"]:
            self.assertEqual(offer["grade"]["value"], "10")
            self.assertFalse(offer["grade"]["certificate_verified"])
            self.assertEqual(offer["identity_evidence"]["status"], "exact_match")
            self.assertFalse(offer["identity_evidence"]["authenticity_verified"])
            self.assertEqual(offer["listing_photos"][0]["listing_url"], offer["url"])
        self.assertEqual(report["variant_required"]["status"], "variant_selection_required")
        self.assertEqual(handoff["status"], "quote_ready_for_review")
        self.assertEqual(handoff["quote"]["buyship"]["canonical_url"], URL)
        self.assertEqual(handoff["quote"]["buyship"]["variant_key"], "fixture-card")
        self.assertEqual(handoff["quote"]["buyship"]["destination"], {"country": "HK"})
        self.assertFalse(handoff["quote"]["evidence"]["authenticity_verified"])
        self.assertEqual({x["scenario"] for x in report["blocked"]}, {"price_changed", "sold", "identity_changed"})
        self.assertNotIn("/v1/orders", report["provider_paths"])
        self.assertEqual(report["external_network_calls"], 0)
        for key in ("research", "selection", "variant_required", "handoff"):
            self.assertFalse(report[key]["purchasable"]); self.assertFalse(report[key]["order_created"])

    def test_photo_display_is_separate_and_urls_do_not_leave_sidecar_without_it(self):
        with Pilot(photo_display_approved=False) as pilot:
            _, research = pilot.research(); _, selection = pilot.select(research["offers"][0])
            _, variants = pilot.handoff(selection)
            _, quote = pilot.handoff(selection, variant_key="fixture-card")
            self.assertEqual(research["offers"][0]["listing_photos"], [])
            self.assertNotIn("i.ebayimg.com", json.dumps([research, selection, variants, quote]))
            self.assertEqual(research["source_readiness"][0]["photo_display"], "not_approved")

    def test_read_authority_never_implies_partner_handoff(self):
        with Pilot(partner_handoff_allowed=False) as pilot:
            _, result = pilot.research(); _, selected = pilot.select(result["offers"][0])
            status, blocked = pilot.handoff(selected)
            self.assertEqual(status, 409); self.assertEqual(blocked["error"], "source_access_unavailable")
            self.assertEqual(pilot.provider_paths, [])

    def test_revoked_after_dns_tls_before_http_dispatch_sends_no_api_request(self):
        with Pilot() as pilot:
            pilot.on_connect = lambda: pilot.sources.revoke("ebay_us")
            _, report = pilot.research()
            self.assertEqual(report["offers"], [])
            self.assertEqual(pilot.marketplace_paths, [])
            self.assertEqual(report["source_readiness"][0]["blocker"], "source_revoked")

    def test_crawl_revocation_after_connect_blocks_robots_http_dispatch(self):
        budget = DispatchBudget(max_requests=5, seconds=60)
        crawler = Crawler(fetch=PublicHTMLFetch(enabled=True), authorized_sources=("mercari",), dispatch_budget=budget)
        route = ApprovedSources(policies={"mercari": policy(mode="crawl_only", api_approved=False, crawl_approved=True)},
                                crawler=crawler, budget=budget, enabled=True)
        dispatched = []
        class Connection:
            def __init__(self, *args, **kwargs): self.sock = SimpleNamespace(settimeout=lambda _: None)
            def connect(self): route.revoke("mercari")
            def request(self, *args, **kwargs): dispatched.append(args)
            def close(self): pass
        with patch("pokemon_index.marketplace_crawl._PinnedHTTPS", Connection):
            with self.assertRaises(ValueError): route.search("mercari", "card")
        self.assertEqual(dispatched, [])

    def test_revoked_worker_success_and_variant_refusal_publish_no_usable_result(self):
        for single_variant in (False, True):
            with self.subTest(single_variant=single_variant), Pilot() as pilot:
                if single_variant: pilot.fixture["resolve"]["variants"] = pilot.fixture["resolve"]["variants"][:1]
                _, result = pilot.research(); _, selected = pilot.select(result["offers"][0])
                pilot.after_worker = lambda: pilot.sources.revoke("ebay_us")
                status, blocked = pilot.handoff(selected)
                self.assertEqual(status, 409); self.assertEqual(blocked["error"], "source_access_unavailable")
                self.assertNotIn("provider_result", blocked); self.assertNotIn("quote", blocked)
                self.assertNotIn("variant_choices", pilot.loop._selections[selected["selection_id"]])

    def test_revoked_source_cannot_reuse_retained_selection(self):
        with Pilot() as pilot:
            _, result = pilot.research(); pilot.sources.revoke("ebay_us")
            status, blocked = pilot.select(result["offers"][0])
            self.assertEqual(status, 409); self.assertEqual(blocked["error"], "source_access_unavailable")
            self.assertEqual(pilot.provider_paths, [])

    def test_budget_and_token_state_affect_readiness_without_network_or_counter_change(self):
        with Pilot() as pilot:
            before = len(pilot.marketplace_paths)
            self.assertEqual(source_readiness(pilot.sources)[0]["status"], "enabled")
            pilot.budget.remaining = 0
            row = source_readiness(pilot.sources)[0]
            self.assertEqual(row["blocker"], "source_window_closed")
            self.assertEqual(row["photo_display"], "authorized_only")
            self.assertFalse(row["listing_read_enabled"])
            pilot.budget.remaining = 5; pilot.api._token = "expired"
            pilot.api._token_until = pilot.instant - timedelta(seconds=1)
            self.assertEqual(source_readiness(pilot.sources)[0]["status"], "configured_offline")
            self.assertEqual(len(pilot.marketplace_paths), before)
            self.assertNotIn("synthetic-operator-record", json.dumps(source_readiness(pilot.sources)))

    def test_direct_url_onboarding_requires_exact_server_allowlist_and_sticky_identity(self):
        with Pilot() as pilot:
            row = pilot.sources.onboard_url(URL)
            self.assertEqual(row["native_id"], "v1|123456789012|0")
            count = len(pilot.marketplace_paths)
            with self.assertRaises(SourceWiringError): pilot.sources.onboard_url(URL + "?x=1")
            self.assertEqual(len(pilot.marketplace_paths), count)
            pilot.rows[0]["itemId"] = "v1|123456789012|7"
            with self.assertRaises(ValueError): pilot.sources.detail(URL)

    def test_default_and_legacy_live_flags_cannot_implicitly_authorize_sources(self):
        args = SimpleNamespace(approved_source_routing=False, allow_live_crawl=False, allow_live_ebay_browse=False,
                               source_route=[], source_listing_url=[], source_request_budget=None, source_window_seconds=None)
        self.assertIsNone(commerce_service._approved_sources(args, {}))
        args.allow_live_crawl = True
        with self.assertRaises(ValueError): commerce_service._approved_sources(args, {})
        rows = source_readiness(object())
        self.assertTrue(all(row["status"] == "not_configured" and not row["listing_read_enabled"] for row in rows))

    def test_no_crawl_fallback_after_api_budget_or_authorization_failure(self):
        with Pilot(mode="api_preferred") as pilot:
            pilot.budget.remaining = 1
            _, result = pilot.research()
            self.assertEqual(result["offers"], [])
            self.assertEqual(len(pilot.marketplace_paths), 1)
            self.assertEqual(pilot.provider_paths, [])


if __name__ == "__main__":
    unittest.main()

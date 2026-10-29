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
            pilot.budget.remaining = 2  # token/search cannot afford a detail
            self.assertEqual(source_readiness(pilot.sources)[0]["status"], "configured_offline")
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

    def test_api_discovery_hydrates_each_exact_hit_before_offer_selection(self):
        with Pilot() as pilot:
            _, report = pilot.research()
            paths = pilot.marketplace_paths
            self.assertEqual(len(paths), 4)  # token, search and two exact details
            self.assertIn("legacy_item_id=123456789012", paths[2])
            self.assertIn("legacy_item_id=123456789013", paths[3])
            self.assertEqual({o["native_id"] for o in report["offers"]},
                             {"v1|123456789012|0", "v1|123456789013|0"})
            for offer in report["offers"]:
                self.assertEqual(offer["availability"], "available")
                self.assertEqual(offer["grade"]["value"], "10")
                self.assertEqual(offer["identity_status"], "exact_match")
            _, selected = pilot.select(report["offers"][0])
            _, variants = pilot.handoff(selected)
            self.assertEqual(variants["status"], "variant_selection_required")
            # A fresh detail having grader/stock/aspects is not false drift.
            self.assertEqual(pilot.marketplace_paths[4], paths[2])

    def test_detail_budget_failure_publishes_no_summary_or_partial_binding(self):
        for budget in (2, 3):
            with self.subTest(budget=budget), Pilot() as pilot:
                pilot.budget.remaining = budget
                _, report = pilot.research()
                self.assertEqual(report["offers"], [])
                self.assertEqual(len(pilot.marketplace_paths), budget)
                self.assertEqual(pilot.sources.listings, {})
                self.assertEqual(pilot.sources.snapshots, {})
                self.assertEqual(pilot.provider_paths, [])

    def test_revocation_after_search_prevents_detail_and_summary_publication(self):
        with Pilot() as pilot:
            pilot.after_search_response = lambda: pilot.sources.revoke("ebay_us")
            _, report = pilot.research()
            self.assertEqual(report["offers"], [])
            self.assertEqual(len(pilot.marketplace_paths), 2)  # token and search
            self.assertEqual(pilot.sources.listings, {})
            self.assertEqual(pilot.provider_paths, [])
            self.assertEqual(report["source_readiness"][0]["blocker"], "source_revoked")

    def test_revocation_after_detail_connect_sends_no_next_http_or_partial_rows(self):
        for sent in (2, 3):
            with self.subTest(already_sent=sent), Pilot() as pilot:
                def revoke_at_detail_connect():
                    if len(pilot.marketplace_paths) == sent:
                        pilot.sources.revoke("ebay_us")
                pilot.on_connect = revoke_at_detail_connect
                _, report = pilot.research()
                self.assertEqual(report["offers"], [])
                self.assertEqual(len(pilot.marketplace_paths), sent)
                self.assertEqual(pilot.sources.listings, {})
                self.assertEqual(pilot.provider_paths, [])

    def test_current_detail_price_replaces_stale_summary_without_reselection_loop(self):
        with Pilot() as pilot:
            pilot.after_search_response = lambda: pilot.rows[0]["price"].update(value="125.00")
            _, report = pilot.research()
            self.assertEqual(report["offers"][0]["price_minor"], 12500)
            _, selected = pilot.select(report["offers"][0])
            _, variants = pilot.handoff(selected)
            self.assertEqual(variants["status"], "variant_selection_required")

    def test_hydrated_detail_cannot_replace_discovered_native_listing(self):
        with Pilot() as pilot:
            with patch.object(pilot.api, "detail", return_value={
                    "source": "ebay_us", "native_id": "v1|123456789099|0",
                    "url": "https://www.ebay.com/itm/123456789099", "scope": "listing"}):
                _, report = pilot.research()
            self.assertEqual(report["offers"], [])
            self.assertEqual(pilot.sources.listings, {})
            self.assertEqual(len(pilot.marketplace_paths), 2)
            self.assertEqual(pilot.provider_paths, [])


if __name__ == "__main__":
    unittest.main()

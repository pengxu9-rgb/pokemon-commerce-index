"""ADV-2/3/5 regressions: local HTTP, fake HTTPS, external sockets/DNS denied."""
from contextlib import ExitStack, contextmanager
import copy
from datetime import datetime, timedelta, timezone
import json
import socket
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pokemon_index.approved_sources import ApprovedSources, SourceWiringError
from pokemon_index.dispatch_budget import DispatchBudget
from pokemon_index.marketplace_crawl import Crawler, PublicHTMLFetch, canonical_product_url
from pokemon_index.source_readiness import source_readiness
from tests.live_offer_rehearsal import CARD, TITLE, URL, Pilot, policy


@contextmanager
def later_source(pilot, change):
    """Prior adversary's exact order: eBay completes, Mercari TLS changes rights."""
    crawl = Crawler(fetch=PublicHTMLFetch(enabled=True), authorized_sources=("mercari",), dispatch_budget=pilot.budget)
    route = ApprovedSources(policies={"ebay_us": policy(), "mercari": policy(
        mode="crawl_only", api_approved=False, crawl_approved=True)}, budget=pilot.budget,
        crawler=crawl, ebay_client=pilot.api, enabled=True, public_listing_urls=(URL,))
    pilot.sources = pilot.loop.crawler = route
    seen = []

    class Reply:
        status = 200
        def read(self, size): return b"User-agent: *\nDisallow: /\n"
        def getheaders(self): return [("Content-Type", "text/plain")]

    class HTTPS:
        def __init__(self, host, **kwargs):
            assert host == "jp.mercari.com"
            self.sock = SimpleNamespace(settimeout=lambda _: None)
        def connect(self):
            assert route.listings
            seen.extend(copy.deepcopy(list(pilot.loop._offers.values())))
            change(route)
        def request(self, method, path, headers): pass
        def getresponse(self): return Reply()
        def close(self): pass

    with patch("pokemon_index.marketplace_crawl._PinnedHTTPS", HTTPS):
        yield seen


def native_raw(pilot):
    for index, row in enumerate(pilot.rows):
        row["title"] = row["title"].replace(" PSA 10", "")
        row.update(condition="Ungraded", conditionId="4000", categoryId="183454",
                   categoryPath="Collectibles|Collectible Card Games|CCG Individual Cards")
        row["conditionDescriptors"] = [{"name": "Card Condition", "values": [
            {"content": "Near mint or better" if index == 0 else "Heavily played (Poor)"}]}]
        row["localizedAspects"] = [aspect for aspect in row["localizedAspects"]
                                   if aspect["name"] not in {"Professional Grader", "Grade"}]


@contextmanager
def deny_external_network():
    external_attempts = []
    with ExitStack() as network:
        for name in ("socket.socket.connect", "socket.socket.connect_ex", "socket.create_connection",
                     "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyname_ex"):
            owner, key = name.rsplit(".", 1)
            original = getattr(socket.socket if owner == "socket.socket" else socket, key)
            # Capture method membership before patching the class attributes.
            is_method = owner == "socket.socket"
            def call(*args, original=original, is_method=is_method, **kwargs):
                address = args[1] if is_method else args[0]
                host = address[0] if isinstance(address, tuple) else address
                if host != "127.0.0.1":
                    external_attempts.append(repr(address))
                    raise AssertionError("external sockets and DNS forbidden")
                return original(*args, **kwargs)
            network.enter_context(patch(name, call))
        yield external_attempts
    assert not external_attempts, "external socket or DNS attempt invalidates the regression"


def raw_card_report():
    """Real backend DTOs for the paired frontend contract check; no provider I/O."""
    with deny_external_network(), Pilot() as pilot:
        native_raw(pilot)
        research_status, research = pilot.research()
        assert research_status == 200
        selection_status, selection = pilot.select(research["offers"][0])
        assert selection_status == 200
        assert not pilot.provider_paths
        return {"research": research, "selection": selection}


def expired_quote_report():
    """Real HTTP quote expires during a three-second native API readiness wait."""
    with deny_external_network() as external_attempts, Pilot() as pilot:
        pilot.fixture["resolve"]["variants"] = pilot.fixture["resolve"]["variants"][:1]
        quote_expires = pilot.instant + timedelta(seconds=2)
        pilot.fixture["quote"]["expires_at"] = quote_expires.isoformat()
        research_status, research = pilot.research()
        selection_status, selection = pilot.select(research["offers"][0])
        assert research_status == selection_status == 200
        timing = {}
        def delay(route):
            timing["before_publish"] = pilot.instant.isoformat()
            assert pilot.instant < quote_expires
            began = time.monotonic()
            time.sleep(3)
            pilot.instant = datetime.now(timezone.utc).replace(microsecond=0)
            timing["native_wait_elapsed"] = time.monotonic() - began
        began = time.monotonic()
        status, handoff = SourceFixTests().readiness_race(
            pilot, lambda: pilot.handoff(selection), delay, after_worker=True)
        request_elapsed = time.monotonic() - began
        assert status == 200 and 3 <= request_elapsed < 5
        assert not any("orders" in path or "payments" in path for path in pilot.provider_paths)
        return {"research": research, "selection": selection, "handoff": handoff,
                "quote_expires_at": quote_expires.isoformat(), **timing,
                "final_checked_at": handoff["checked_at"],
                "public_response_at": datetime.now(timezone.utc).isoformat(),
                "request_elapsed": request_elapsed, "external_attempts": list(external_attempts)}


class SourceFixTests(unittest.TestCase):
    def setUp(self):
        self.network = ExitStack()
        self.external_attempts = self.network.enter_context(deny_external_network())

    def tearDown(self):
        self.network.close()
        self.assertEqual(self.external_attempts, [])

    def research_all(self, pilot):
        return pilot.post("research", {"card_id": CARD, "query": TITLE, "platforms": ["ebay_us", "mercari"]})

    def readiness_race(self, pilot, action, change, *, after_refresh=False, after_worker=False):
        """Block actual native API readiness, then change current authority."""
        held, entered, done, refreshed = (threading.Event() for _ in range(4))
        errors, holder, threads = [], [], []
        native_lock = pilot.api._lock
        original_now, original_connect, original_worker = pilot.loop.now, pilot.on_connect, pilot.after_worker
        class WitnessLock:
            def __enter__(self):
                if held.is_set() and threading.get_ident() != holder[0]:
                    entered.set()
                native_lock.acquire()
                return self
            def __exit__(self, *args): native_lock.release()
        pilot.api._lock = WitnessLock()
        def arm():
            if threads:
                return
            def locker():
                try:
                    with native_lock:
                        holder.append(threading.get_ident())
                        held.set()
                        if not entered.wait(3):
                            raise AssertionError("final readiness did not wait on native API lock")
                        change(pilot.sources)
                except BaseException as exc:
                    errors.append(repr(exc))
                finally:
                    done.set()
            thread = threading.Thread(target=locker, daemon=True)
            threads.append(thread)
            thread.start()
            self.assertTrue(held.wait(2))
        if after_refresh:
            pilot.on_connect = lambda: refreshed.set()
            def at_time():
                if refreshed.is_set():
                    arm()
                return original_now()
            pilot.loop.now = at_time
        elif after_worker:
            pilot.after_worker = arm
        else:
            arm()
        try:
            response = action()
            self.assertTrue(done.wait(3))
            self.assertTrue(entered.is_set())
            self.assertEqual(errors, [])
            return response
        finally:
            for thread in threads:
                thread.join(4)
                self.assertFalse(thread.is_alive())
            pilot.api._lock = native_lock
            pilot.loop.now, pilot.on_connect, pilot.after_worker = original_now, original_connect, original_worker

    def assert_reusable_photos_absent(self, pilot):
        for state in (pilot.loop._offers, pilot.loop._selections):
            self.assertTrue(all(not row["offer"]["listing_photos"] for row in state.values()))

    def test_quote_expiring_during_real_native_readiness_wait_is_not_published_ready(self):
        from pokemon_index.bns_errors import validate_refusal
        report = expired_quote_report()
        body = report["handoff"]
        self.assertEqual(body["status"], "manual_handoff_required")
        self.assertEqual(body["quote_status"], "quote_expired")
        self.assertIsNone(body["quote"])
        self.assertEqual(validate_refusal(body["provider_result"])["code"], "quote_expired")
        self.assertLess(report["before_publish"], report["quote_expires_at"])
        self.assertGreaterEqual(report["final_checked_at"], report["quote_expires_at"])
        self.assertGreaterEqual(report["native_wait_elapsed"], 3)
        self.assertEqual(report["external_attempts"], [])
        self.assertFalse(body["purchasable"])
        self.assertFalse(body["order_created"])
        self.assertIsNone(body["purchase_action"])

    def test_quote_validity_controls_at_final_publication(self):
        for control in ("no_delay", "still_valid", "exact_expiry", "already_expired", "source_revoked",
                        "selection_expired", "offer_expired"):
            with self.subTest(control=control), Pilot() as pilot:
                pilot.fixture["resolve"]["variants"] = pilot.fixture["resolve"]["variants"][:1]
                quote_expires = pilot.instant + timedelta(seconds=30)
                pilot.fixture["quote"]["expires_at"] = quote_expires.isoformat()
                _, research = pilot.research()
                _, selection = pilot.select(research["offers"][0])
                if control == "no_delay":
                    status, body = pilot.handoff(selection)
                elif control == "already_expired":
                    pilot.after_worker = lambda: setattr(pilot, "instant", quote_expires + timedelta(seconds=1))
                    status, body = pilot.handoff(selection)
                else:
                    def change(route):
                        if control == "source_revoked":
                            route.revoke("ebay_us")
                            pilot.instant = quote_expires + timedelta(seconds=1)
                        elif control == "exact_expiry":
                            pilot.instant = quote_expires
                        elif control == "selection_expired":
                            pilot.instant += timedelta(seconds=601)
                        elif control == "offer_expired":
                            pilot.instant += timedelta(seconds=301)
                        else:
                            pilot.instant += timedelta(seconds=1)
                    status, body = self.readiness_race(pilot, lambda: pilot.handoff(selection), change, after_worker=True)
                if control in {"source_revoked", "selection_expired", "offer_expired"}:
                    self.assertEqual(status, 409)
                    self.assertEqual(body["error"], "source_access_unavailable" if control == "source_revoked" else control)
                    self.assertNotIn("quote", body)
                    self.assertEqual(pilot.loop._offers, {})
                    self.assertEqual(pilot.loop._selections, {})
                else:
                    self.assertEqual(status, 200)
                    if control in {"no_delay", "still_valid"}:
                        self.assertEqual(body["status"], "quote_ready_for_review")
                        self.assertEqual(body["quote_status"], "ready")
                        self.assertGreater(body["quote"]["buyship"]["expires_at"], body["checked_at"])
                    else:
                        self.assertEqual(body["status"], "manual_handoff_required")
                        self.assertIsNone(body["quote"])
                        if control == "exact_expiry":
                            self.assertEqual(body["quote_status"], "quote_expired")
                        else:
                            self.assertEqual(body["quote_status"], "eligible_indexed_quote_unavailable")
                self.assertEqual(len(pilot.provider_paths), 3)
                self.assertFalse(any("orders" in path or "payments" in path for path in pilot.provider_paths))

    def test_photo_downgrade_between_research_select_and_manual_handoff(self):
        with Pilot() as pilot:
            pilot.loop.forwarders.clear()
            _, research = pilot.research()
            pilot.sources.policies["ebay_us"]["photo_display_approved"] = False
            status, selected = pilot.select(research["offers"][0])
            self.assertEqual(status, 200)
            self.assertNotIn("i.ebayimg.com", json.dumps(selected))
            self.assertEqual(selected["source_readiness"][0]["photo_display"], "not_approved")
            self.assert_reusable_photos_absent(pilot)
            status, manual = pilot.handoff(selected, forwarder="other")
            self.assertEqual(status, 200)
            self.assertEqual(manual["status"], "manual_handoff_required")
            self.assertNotIn("i.ebayimg.com", json.dumps(manual))
            self.assert_reusable_photos_absent(pilot)
            self.assertEqual(pilot.provider_paths, [])
        with Pilot() as pilot:
            pilot.loop.forwarders.clear()
            _, research = pilot.research()
            _, selected = pilot.select(research["offers"][0])
            pilot.sources.policies["ebay_us"]["photo_display_approved"] = False
            status, manual = pilot.handoff(selected, forwarder="other")
            self.assertEqual(status, 200)
            self.assertNotIn("i.ebayimg.com", json.dumps(manual))
            self.assert_reusable_photos_absent(pilot)
            self.assertEqual(pilot.provider_paths, [])

    def test_select_native_readiness_wait_rechecks_source_photos_and_admission(self):
        changes = {"revoke": lambda route: route.revoke("ebay_us"),
                   "photos": lambda route: route.policies["ebay_us"].update(photo_display_approved=False),
                   "access": lambda route: route.policies["ebay_us"].update(access_approval=""),
                   "budget": lambda route: setattr(route.budget, "remaining", 0),
                   "window": lambda route: setattr(route.budget, "deadline", 0)}
        for name, change in changes.items():
            with self.subTest(change=name), Pilot() as pilot:
                _, research = pilot.research()
                paths = list(pilot.marketplace_paths)
                status, body = self.readiness_race(pilot, lambda: pilot.select(research["offers"][0]), change)
                if name in {"revoke", "access"}:
                    self.assertEqual(status, 409)
                    self.assertEqual(body["error"], "source_access_unavailable")
                    self.assertEqual(pilot.loop._offers, {})
                    self.assertEqual(pilot.loop._selections, {})
                else:
                    self.assertEqual(status, 200)
                    self.assertEqual(len(pilot.loop._offers), 2)
                    self.assertEqual(len(pilot.loop._selections), 1)
                    if name == "photos":
                        self.assertNotIn("i.ebayimg.com", json.dumps(body))
                        self.assertEqual(body["source_readiness"][0]["photo_display"], "not_approved")
                        self.assert_reusable_photos_absent(pilot)
                    else:
                        self.assertEqual(body["source_readiness"][0]["blocker"], "source_window_closed")
                        self.assertTrue(body["offer"]["listing_photos"])
                self.assertEqual(pilot.marketplace_paths, paths)
                self.assertEqual(pilot.provider_paths, [])

    def test_manual_handoff_native_readiness_wait_rechecks_source_and_photos(self):
        for name, change in (("revoke", lambda route: route.revoke("ebay_us")),
                             ("photos", lambda route: route.policies["ebay_us"].update(photo_display_approved=False))):
            with self.subTest(change=name), Pilot() as pilot:
                pilot.loop.forwarders.clear()
                _, research = pilot.research()
                _, selected = pilot.select(research["offers"][0])
                status, body = self.readiness_race(pilot, lambda: pilot.handoff(selected, forwarder="other"),
                                                   change, after_refresh=True)
                if name == "revoke":
                    self.assertEqual(status, 409)
                    self.assertEqual(body["error"], "source_access_unavailable")
                    self.assertNotIn("product_url", body)
                    self.assertEqual(pilot.loop._offers, {})
                    self.assertEqual(pilot.loop._selections, {})
                else:
                    self.assertEqual(status, 200)
                    self.assertEqual(body["status"], "manual_handoff_required")
                    self.assertNotIn("i.ebayimg.com", json.dumps(body))
                    self.assertEqual(body["source_readiness"][0]["photo_display"], "not_approved")
                    self.assert_reusable_photos_absent(pilot)
                self.assertEqual(pilot.provider_paths, [])

    def test_bns_success_and_refusal_share_final_publication_projection(self):
        for single_variant in (False, True):
            for name, change in (("revoke", lambda route: route.revoke("ebay_us")),
                                 ("photos", lambda route: route.policies["ebay_us"].update(photo_display_approved=False)),
                                 ("partner", lambda route: route.policies["ebay_us"].update(partner_handoff_allowed=False))):
                with self.subTest(single_variant=single_variant, change=name), Pilot() as pilot:
                    if single_variant:
                        pilot.fixture["resolve"]["variants"] = pilot.fixture["resolve"]["variants"][:1]
                    _, research = pilot.research()
                    _, selected = pilot.select(research["offers"][0])
                    status, body = self.readiness_race(pilot, lambda: pilot.handoff(selected), change, after_worker=True)
                    if name in {"revoke", "partner"}:
                        self.assertEqual(status, 409)
                        self.assertEqual(body["error"], "source_access_unavailable")
                        self.assertNotIn("quote", body)
                        self.assertNotIn("provider_result", body)
                        if name == "revoke":
                            self.assertEqual(pilot.loop._offers, {})
                            self.assertEqual(pilot.loop._selections, {})
                        else:
                            self.assertNotIn("variant_choices", pilot.loop._selections[selected["selection_id"]])
                    else:
                        self.assertEqual(status, 200)
                        self.assertEqual(body["status"], "quote_ready_for_review" if single_variant else "variant_selection_required")
                        self.assertNotIn("i.ebayimg.com", json.dumps(body))
                        self.assert_reusable_photos_absent(pilot)
                    self.assertTrue(pilot.provider_paths)  # existing in-memory BNS fixture only
                    self.assertFalse(any("orders" in path or "payments" in path for path in pilot.provider_paths))

    def test_contextual_certificate_publication_projects_retained_source(self):
        for name, change in (("revoke", lambda route: route.revoke("ebay_us")),
                             ("photos", lambda route: route.policies["ebay_us"].update(photo_display_approved=False))):
            with self.subTest(change=name), Pilot() as pilot:
                _, research = pilot.research()
                pilot.loop.psa_client = SimpleNamespace(lookup=lambda *args, **kwargs: {
                    "status": "unavailable", "certificate_verified": False, "authenticity_verified": False})
                status, body = self.readiness_race(pilot, lambda: pilot.post("psa", {
                    "certificate_number": "12345678", "offer_id": research["offers"][0]["offer_id"]}), change)
                if name == "revoke":
                    self.assertEqual(status, 409)
                    self.assertEqual(body["error"], "source_access_unavailable")
                    self.assertNotIn("verification", body)
                    self.assertEqual(pilot.loop._offers, {})
                else:
                    self.assertEqual(status, 200)
                    self.assert_reusable_photos_absent(pilot)
                self.assertEqual(pilot.provider_paths, [])

    def test_photo_projection_cannot_rebind_unrelated_selection_drift(self):
        with Pilot() as pilot:
            pilot.loop.forwarders.clear()
            _, research = pilot.research()
            _, selected = pilot.select(research["offers"][0])
            pilot.loop._selections[selected["selection_id"]]["offer"]["price_minor"] += 1
            pilot.sources.policies["ebay_us"]["photo_display_approved"] = False
            status, body = pilot.handoff(selected, forwarder="other")
            self.assertEqual(status, 409)
            self.assertEqual(body["error"], "offer_changed")
            self.assert_reusable_photos_absent(pilot)
            self.assertEqual(pilot.provider_paths, [])

    def test_revoked_refresh_failure_prunes_old_reusable_records(self):
        with Pilot() as pilot:
            pilot.loop.forwarders.clear()
            _, research = pilot.research()
            _, selected = pilot.select(research["offers"][0])
            pilot.on_connect = lambda: pilot.sources.revoke("ebay_us")
            status, body = pilot.handoff(selected, forwarder="other")
            self.assertEqual(status, 503)
            self.assertEqual(body["error"], "refresh_unavailable")
            self.assertEqual(pilot.loop._offers, {})
            self.assertEqual(pilot.loop._selections, {})
            self.assertEqual(pilot.provider_paths, [])

    def test_revoked_earlier_source_is_absent_from_final_http_body_and_store(self):
        with Pilot() as pilot, later_source(pilot, lambda route: route.revoke("ebay_us")) as seen:
            status, result = self.research_all(pilot)
            self.assertEqual(status, 200)
            self.assertEqual(len(seen), 2)
            self.assertTrue(all(row["offer"]["listing_photos"] for row in seen))
            self.assertEqual(result["offers"], [])
            self.assertEqual(result["coverage"]["returned_listings"], 0)
            self.assertNotIn("i.ebayimg.com", json.dumps(result))
            self.assertEqual(pilot.loop._offers, {})
            self.assertEqual(result["source_readiness"][0]["blocker"], "source_revoked")
            self.assertEqual(result["marketplace_connections"][0]["status"], "configured_offline")
            self.assertEqual(result["platforms"][0]["status"], "unavailable")
            self.assertEqual(pilot.select(seen[0]["offer"])[0], 409)
            self.assertEqual(pilot.provider_paths, [])

    def test_photo_downgrade_projects_every_accumulated_and_retained_row(self):
        with Pilot() as pilot, later_source(pilot, lambda route: route.policies["ebay_us"].update(photo_display_approved=False)) as seen:
            status, result = self.research_all(pilot)
            self.assertEqual(status, 200)
            self.assertEqual(len(result["offers"]), 2)
            self.assertTrue(all(row["offer"]["listing_photos"] for row in seen))
            self.assertTrue(all(not row["listing_photos"] for row in result["offers"]))
            self.assertEqual(result["coverage"]["listings_with_photos"], 0)
            self.assertNotIn("i.ebayimg.com", json.dumps(result))
            self.assertTrue(all(not row["offer"]["listing_photos"] for row in pilot.loop._offers.values()))
            selected_status, selected = pilot.select(result["offers"][0])
            self.assertEqual(selected_status, 200)
            self.assertEqual(selected["offer"]["listing_photos"], [])
            self.assertEqual(pilot.provider_paths, [])

    def test_final_authority_check_follows_readiness_work_and_prunes_old_selections(self):
        with Pilot() as pilot:
            _, previous = pilot.research()
            _, selected = pilot.select(previous["offers"][0])
            original_readiness = source_readiness
            def revoke_during_readiness(route):
                rows = original_readiness(route)
                if len(pilot.marketplace_paths) > 4:
                    route.revoke("ebay_us")
                return rows
            with patch("pokemon_index.source_readiness.source_readiness", revoke_during_readiness):
                status, result = pilot.research()
            self.assertEqual(status, 200)
            self.assertEqual(result["offers"], [])
            self.assertNotIn("i.ebayimg.com", json.dumps(result))
            self.assertEqual(pilot.loop._offers, {})
            self.assertNotIn(selected["selection_id"], pilot.loop._selections)
            self.assertEqual(result["source_readiness"][0]["blocker"], "source_revoked")
            self.assertEqual(pilot.provider_paths, [])

    def test_permission_changes_remove_earlier_rows_without_handoff_permission_dependency(self):
        for change in ({"mode": "disabled"}, {"api_approved": False}, {"access_approval": ""}):
            with self.subTest(change=change), Pilot() as pilot, later_source(pilot, lambda route: route.policies["ebay_us"].update(change)):
                _, result = self.research_all(pilot)
                self.assertEqual(result["offers"], [])
                self.assertEqual(pilot.loop._offers, {})
        with Pilot() as pilot, later_source(pilot, lambda route: route.policies["ebay_us"].update(partner_handoff_allowed=False)):
            _, result = self.research_all(pilot)
            self.assertEqual(len(result["offers"]), 2)
            self.assertTrue(all(row["listing_photos"] for row in result["offers"]))

    def test_ended_read_budget_preserves_captures_and_reports_offline_readiness(self):
        for change in (lambda route: setattr(route.budget, "remaining", 0),
                       lambda route: setattr(route.budget, "deadline", 0)):
            with self.subTest(change=change), Pilot() as pilot, later_source(pilot, change):
                status, result = self.research_all(pilot)
                self.assertEqual(status, 200)
                self.assertEqual(len(result["offers"]), 2)
                self.assertEqual(len(pilot.loop._offers), 2)
                self.assertTrue(all(row["listing_photos"] for row in result["offers"]))
                self.assertEqual(result["source_readiness"][0]["blocker"], "source_window_closed")
                self.assertFalse(result["source_readiness"][0]["listing_read_enabled"])
                self.assertEqual(result["marketplace_connections"][0]["status"], "configured_offline")
                self.assertEqual(pilot.provider_paths, [])

    def test_native_ccg_ungraded_is_selectable_and_keeps_each_seller_condition(self):
        with Pilot() as pilot:
            native_raw(pilot)
            status, result = pilot.research()
            self.assertEqual(status, 200)
            self.assertEqual([row["seller_condition"] for row in result["offers"]],
                             ["Near mint or better", "Heavily played (Poor)"])
            for offer in result["offers"]:
                self.assertEqual(offer["grade"]["kind"], "raw")
                self.assertEqual(offer["grade"]["evidence"], "structured_raw_claim")
                self.assertFalse(offer["grade"]["review_required"])
                self.assertFalse(offer["grade"]["certificate_verified"])
                self.assertEqual(pilot.select(offer)[0], 200)
            self.assertEqual(pilot.provider_paths, [])

    def test_card_condition_change_invalidates_selection_before_provider_dispatch(self):
        with Pilot() as pilot:
            native_raw(pilot)
            _, result = pilot.research()
            _, selected = pilot.select(result["offers"][0])
            pilot.instant += timedelta(seconds=1)
            pilot.rows[0]["conditionDescriptors"][0]["values"][0]["content"] = "Heavily played (Poor)"
            status, blocked = pilot.handoff(selected)
            self.assertEqual(status, 409)
            self.assertEqual(blocked["error"], "offer_changed")
            self.assertEqual(pilot.provider_paths, [])

    def test_raw_graded_contradictions_fail_closed(self):
        def graded_title(row): row["title"] += " PSA 10"
        def graded_aspects(row): row["localizedAspects"] += [{"name": "Professional Grader", "value": "PSA"}, {"name": "Grade", "value": "10"}]
        def graded_condition(row): row["condition"] = "Graded"
        def graded_id(row): row["conditionId"] = "2750"
        def certificate(row): row["localizedAspects"] += [{"name": "Certification Number", "value": "12345678"}]
        def conflicting_condition(row): row["conditionDescriptors"][0]["values"] += [{"content": "Damaged"}]
        for change in (graded_title, graded_aspects, graded_condition, graded_id, certificate, conflicting_condition):
            with self.subTest(change=change.__name__), Pilot() as pilot:
                native_raw(pilot)
                for row in pilot.rows: change(row)
                _, result = pilot.research()
                self.assertEqual(result["offers"], [])
                self.assertEqual(pilot.provider_paths, [])

    def test_condition_4000_outside_supported_card_category_is_not_raw_authority(self):
        for category in (None, "999", "261328"):
            with self.subTest(category=category), Pilot() as pilot:
                native_raw(pilot)
                for row in pilot.rows: row["categoryId"] = category
                _, result = pilot.research()
                self.assertEqual(len(result["offers"]), 2)
                self.assertTrue(all(row["grade"]["kind"] == "unknown" for row in result["offers"]))
                self.assertEqual(pilot.select(result["offers"][0])[0], 409)
                self.assertEqual(pilot.provider_paths, [])

    def test_snkrdunk_canonical_host_aliases_use_same_approved_source(self):
        for host in ("snkrdunk.com", "www.snkrdunk.com"):
            with self.subTest(host=host):
                url = f"https://{host}/apparels/123/used/456"
                paths = []
                class Reply:
                    status = 200
                    def __init__(self, path): self.path = path
                    def read(self, size):
                        if self.path == "/robots.txt": return b"User-agent: *\nAllow: /\n"
                        product = {"@type": "Product", "name": "Charizard 4/102 PSA 10", "url": url,
                                   "offers": {"@type": "Offer", "url": url, "price": 1000,
                                              "priceCurrency": "JPY", "availability": "https://schema.org/InStock"}}
                        return ('<script type="application/ld+json">' + json.dumps(product) + '</script>').encode()
                    def getheaders(self): return [("Content-Type", "text/html")]
                class HTTPS:
                    def __init__(self, *args, **kwargs): self.sock = SimpleNamespace(settimeout=lambda _: None)
                    def connect(self): pass
                    def request(self, method, path, headers): paths.append(path); self.path = path
                    def getresponse(self): return Reply(self.path)
                    def close(self): pass
                budget = DispatchBudget(max_requests=5, seconds=60)
                crawl = Crawler(fetch=PublicHTMLFetch(enabled=True), authorized_sources=("snkrdunk",), dispatch_budget=budget)
                route = ApprovedSources(policies={"snkrdunk": policy(mode="crawl_only", api_approved=False,
                    crawl_approved=True, photo_display_approved=False, partner_handoff_allowed=False)},
                    crawler=crawl, budget=budget, enabled=True, public_listing_urls=(url,))
                self.assertEqual(canonical_product_url(url)[2], url)
                self.assertTrue(source_readiness(route)[2]["listing_read_enabled"])
                with patch("pokemon_index.marketplace_crawl._PinnedHTTPS", HTTPS):
                    self.assertEqual(route.onboard_url(url)["url"], url)
                self.assertEqual(paths, ["/robots.txt", "/apparels/123/used/456"])
                route.policies["snkrdunk"]["crawl_approved"] = False
                with self.assertRaises(SourceWiringError): route.onboard_url(url)
                self.assertEqual(len(paths), 2)


if __name__ == "__main__":
    unittest.main()

"""Seller/listing fixtures only. No marketplace or quote provider is contacted."""
import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from pokemon_index.commerce_loop import CommerceError, CommerceLoop
from pokemon_index.marketplace_crawl import Crawler
from pokemon_index.seller_evidence import extracted_seller, profile_url, validate_seller
from tests.test_marketplace_crawl import FixtureFetch

STAMP = datetime(2026, 10, 26, 1, 0, tzinfo=timezone.utc)
MERCARI = "https://jp.mercari.com/item/m1001"
SNKR = "https://snkrdunk.com/apparels/128089/used/30335981"
CARD = "ja:SV2A:173/165:holo"


def seller_claim(identity="seller-a", *, review_count=0):
    return {"identifier": identity, "name": "Seller " + identity,
        "url": "https://jp.mercari.com/user/profile/" + identity,
        "aggregateRating": {"ratingValue": "4.8", "bestRating": "5", "reviewCount": review_count}}


def jsonld(offers, **product_fields):
    product = {"@type": "Product", "name": "Pikachu 173/165 PSA 10",
               "offers": offers, **product_fields}
    return "<html><script type='application/ld+json'>" + json.dumps(product) + "</script></html>"


def wire_offer(seller=None, **kwargs):
    return {"@type": "Offer", "price": "12000", "priceCurrency": "JPY",
        "availability": "https://schema.org/InStock", "seller": seller, **kwargs}


def flight(seller=None, *, listing=30335981, related=None):
    item = {"id": listing, "apparel": {"id": 128089}, "price": 12000,
        "commaPrice": "¥12,000", "status": 0, "isDisplaySold": False,
        "displayWearCount": "PSA10", "seller": seller}
    node = ["$", "$L59", None, {"apparelId": 128089, "listingId": listing,
        "usedApparelData": {"apparelUsedItem": item}, "relatedSeller": related}]
    record = "4c:" + json.dumps(node) + "\n"
    return ("<html><title>Pikachu 173/165 PSA10</title><script>self.__next_f.push("
        + json.dumps([1, record]) + ")</script></html>")


class SellerEvidenceTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline seller fixture only"))
            guard.start(); self.addCleanup(guard.stop)

    def crawl(self, html, url=MERCARI):
        return Crawler(FixtureFetch({url: html}), now=lambda: STAMP).detail(url)

    def test_exact_offer_seller_keeps_explicit_scale_zero_reviews_and_provenance(self):
        row = self.crawl(jsonld(wire_offer(seller_claim())))
        seller = row["seller"]
        self.assertEqual(seller["id"], "seller-a")
        self.assertEqual(seller["reputation"]["rating"], {"value": 4.8, "scale": 5.0})
        self.assertEqual(seller["reputation"]["review_count"], 0)
        self.assertIsNone(seller["reputation"]["positive_feedback_percent"])
        self.assertEqual(seller["evidence_ref"], row["evidence_ref"])
        self.assertEqual(seller["observed_at"], row["observed_at"])

    def test_product_rating_and_platform_only_name_do_not_become_seller_reputation(self):
        row = self.crawl(jsonld(wire_offer(), aggregateRating={"ratingValue": "5", "bestRating": "5", "reviewCount": 1000}))
        self.assertIsNone(row["seller"])
        self.assertIsNone(extracted_seller({"name": "SNKRDUNK"}, "snkrdunk", "hash:fixture", STAMP.isoformat()))

    def test_generic_platform_id_and_rating_do_not_become_individual_seller(self):
        claim = {"identifier": "snkrdunk", "name": "SNKRDUNK",
            "aggregateRating": {"ratingValue": 5, "bestRating": 5, "reviewCount": 1000}}
        self.assertIsNone(extracted_seller(claim, "snkrdunk", "hash:fixture", STAMP.isoformat()))
        # An explicitly reported allowed user profile distinguishes the account
        # from generic platform merchant metadata; this still is only a claim.
        claim["url"] = "https://snkrdunk.com/users/123"
        self.assertIsNotNone(extracted_seller(claim, "snkrdunk", "hash:fixture", STAMP.isoformat()))

    def test_missing_scale_does_not_invent_five_stars_and_missing_count_is_unknown(self):
        claim = seller_claim(); del claim["aggregateRating"]["bestRating"]
        del claim["aggregateRating"]["reviewCount"]
        seller = self.crawl(jsonld(wire_offer(claim)))["seller"]
        self.assertIsNone(seller["reputation"])

    def test_untrusted_seller_urls_are_never_renderable_profile_links(self):
        for url in ("javascript:alert(1)", "https://127.0.0.1/user/profile/a", "https://evil.example/user/profile/a",
                "https://user:pass@jp.mercari.com/user/profile/a", "https://jp.mercari.com/user/profile/a?token=x",
                "https://jp.mercari.com/user/profile/a#x", "https://jp.mercari.com/user/profile/%2e%2e",
                "https://www.ebay.com/usr/..", "https://jp.mercari.com/item/m1001"):
            with self.subTest(url=url):
                claim = seller_claim(); claim["url"] = url
                seller = self.crawl(jsonld(wire_offer(claim)))["seller"]
                self.assertEqual(seller["id"], "seller-a")
                self.assertIsNone(seller["url"])

    def test_exact_snkr_item_seller_is_bound_to_path_not_related_record(self):
        claim = {"id": 123, "name": "Fixture seller", "url": "/users/123"}
        row = self.crawl(flight(claim, related={"id": 999, "name": "Related seller"}), SNKR)
        self.assertEqual(row["seller"]["id"], "123")
        self.assertEqual(row["seller"]["url"], "https://snkrdunk.com/users/123")
        self.assertIsNone(self.crawl(flight(claim, listing=30335982), SNKR)["seller"])
        self.assertIsNone(self.crawl(flight(related=claim), SNKR)["seller"])

    def test_ambiguous_product_offers_do_not_pick_one_convenient_seller(self):
        row = self.crawl(jsonld([wire_offer(seller_claim("a")), wire_offer(seller_claim("b"))]))
        self.assertIsNone(row["seller"])
        self.assertIn("individual_offer_ambiguous", row["exclusion_reasons"])

    def test_snkr_and_offer_conflicting_sellers_require_review(self):
        claim = {"id": 123, "name": "A", "url": "/users/123"}
        other = {"id": 456, "name": "B", "url": "https://snkrdunk.com/users/456"}
        row = self.crawl(flight(claim) + jsonld(wire_offer(other)), SNKR)
        self.assertIsNone(row["seller"])
        self.assertTrue(row["quality_review_required"])
        self.assertIn("seller_identity_conflict", row["exclusion_reasons"])

    def test_ebay_feedback_is_separate_from_review_count_and_stars(self):
        seller = extracted_seller({"username": "test_seller", "feedbackPercentage": "99.5", "feedbackScore": 123},
            "ebay_us", "api:fixture", STAMP.isoformat())
        self.assertEqual(seller["id"], "test_seller")
        self.assertEqual(seller["reputation"]["positive_feedback_percent"], 99.5)
        self.assertEqual(seller["reputation"]["feedback_score"], 123)
        self.assertIsNone(seller["reputation"]["review_count"])
        self.assertIsNone(seller["reputation"]["rating"])

    def test_invalid_metrics_drop_without_fabricating_zero(self):
        claim = seller_claim(); claim["aggregateRating"] = {"ratingValue": "NaN", "bestRating": 5,
            "reviewCount": "9007199254740990.99"}
        claim.update(feedbackPercentage="1000", feedbackScore=True)
        seller = extracted_seller(claim, "ebay_us", "fixture:hash", STAMP.isoformat())
        self.assertIsNone(seller["reputation"])

    def test_normalized_seller_rejects_bad_timestamp_metric_and_foreign_profile(self):
        valid = extracted_seller(seller_claim(), "mercari", "fixture:hash", STAMP.isoformat())
        for change in ({"observed_at": (STAMP + timedelta(seconds=1)).isoformat()},
                {"url": "https://evil.example/user/profile/a"}, {"display_name": "bad\x00name"},
                {"reputation": {}}, {"extra": "unrecognized"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_seller(valid | change, "mercari", STAMP.isoformat())
        self.assertTrue(profile_url("https://www.ebay.com/usr/a_b.1", "ebay_us"))

    def test_normalized_dto_rejects_whitespace_and_non_iso_timestamp_extensions(self):
        valid = extracted_seller(seller_claim(), "mercari", "fixture:hash", STAMP.isoformat())
        for change in ({"id": " seller-a"}, {"display_name": "Seller a "},
                {"evidence_ref": " fixture:hash"}, {"observed_at": "2026-10-26 01:00:00+00:00"},
                {"observed_at": "2026-10-26T01:00:00"}, {"observed_at": "2026-10-26T01:00:00Z "}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_seller(valid | change, "mercari", STAMP.isoformat())


class MultiSellerCommerceTests(unittest.TestCase):
    def setUp(self):
        for target in ("socket.create_connection", "socket.socket.connect", "socket.getaddrinfo"):
            guard = patch(target, side_effect=AssertionError("offline seller fixture only"))
            guard.start(); self.addCleanup(guard.stop)
        self.instant = STAMP
        self.rows = [self.row("m1001", "seller-a", 12000), self.row("m1002", "seller-b", 11000),
                     self.row("m1003", "seller-a", 14000)]
        outer = self
        class Producer:
            def search(self, source, query, limit=3):
                return {"status": "ok", "listings": copy.deepcopy(outer.rows)}
            def detail(self, url):
                row = next(row for row in outer.rows if row["url"] == url)
                return copy.deepcopy(row) | {"observed_at": outer.instant.isoformat()}
        self.loop = CommerceLoop(Producer(), now=lambda: self.instant.isoformat())

    def row(self, native, seller, price):
        return {"source": "mercari", "native_id": native, "url": "https://jp.mercari.com/item/" + native,
            "title": "Pikachu SV2a 173/165 PSA 10", "price_minor": price, "currency": "JPY",
            "status": "on_sale", "availability": "in_stock", "scope": "listing", "listing_quantity": 1,
            "grade_company": "PSA", "grade_value": "10", "observed_at": self.instant.isoformat(),
            "seller_native_id": seller, "seller_name": "Seller " + seller if seller else None,
            "evidence_ref": "fixture:listing:" + native}

    def research(self):
        return self.loop.research("owner", {"card_id": CARD, "query": "Pikachu 173/165", "platforms": ["mercari"]})

    def choose(self):
        offer = self.research()["offers"][0]
        return self.loop.select("owner", {"card_id": CARD, "offer_id": offer["offer_id"],
            "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": "JPY"})

    def handoff(self, selected):
        return self.loop.handoff("owner", {"selection_id": selected["selection_id"],
            "forwarder": "buyship", "destination": {"country": "HK"}})

    def test_same_platform_two_sellers_and_same_seller_two_listings_stay_independent(self):
        offers = self.research()["offers"]
        self.assertEqual([o["seller"]["id"] for o in offers], ["seller-a", "seller-b", "seller-a"])
        self.assertEqual(len({o["offer_id"] for o in offers}), 3)
        self.assertEqual([o["native_id"] for o in offers], ["m1001", "m1002", "m1003"])
        self.assertTrue(all(o["seller"]["reputation"] is None for o in offers))

    def test_same_canonical_listing_deduplicates_without_collapsing_other_sellers(self):
        self.rows.insert(0, copy.deepcopy(self.rows[0]))
        self.assertEqual(len(self.research()["offers"]), 3)
        self.assertEqual(len(self.loop._offers), 3)

    def test_conflicting_duplicate_does_not_choose_lowest_price(self):
        self.rows.append(copy.deepcopy(self.rows[0]) | {"price_minor": 1})
        result = self.research()
        self.assertEqual(result["offers"], [])
        self.assertEqual(result["platforms"][0]["status"], "unavailable")

    def test_same_url_with_different_listing_id_is_not_two_distinct_offers(self):
        self.rows.append(copy.deepcopy(self.rows[0]) | {"native_id": "m9999"})
        self.assertEqual(self.research()["offers"], [])

    def test_seller_change_and_new_identity_invalidate_existing_selection(self):
        for first, changed in (("seller-a", "seller-b"), (None, "seller-b")):
            with self.subTest(first=first):
                self.rows[0] = self.row("m1001", first, 12000)
                selected = self.choose()
                self.rows[0]["seller_native_id"] = changed
                self.rows[0]["seller_name"] = "Seller " + changed
                self.instant += timedelta(seconds=1)
                with self.assertRaises(CommerceError) as error:
                    self.handoff(selected)
                self.assertEqual(error.exception.code, "offer_changed")
                with self.assertRaises(CommerceError) as error:
                    self.handoff(selected)
                self.assertEqual(error.exception.code, "selection_expired")

    def test_new_capture_or_reputation_does_not_change_stable_seller_identity(self):
        seller = extracted_seller(seller_claim(), "mercari", "fixture:initial", self.instant.isoformat())
        self.rows[0]["seller"] = seller
        selected = self.choose()
        self.instant += timedelta(seconds=1)
        self.rows[0]["seller"] = copy.deepcopy(seller) | {"evidence_ref": "fixture:fresh", "observed_at": self.instant.isoformat()}
        self.rows[0]["seller"]["reputation"]["review_count"] = 100
        result = self.handoff(selected)
        self.assertEqual(result["status"], "manual_handoff_required")
        self.assertEqual(result["offer"]["seller"]["reputation"]["review_count"], 100)
        self.assertFalse(result["order_created"])

    def test_legacy_ebay_export_seller_id_is_carried_without_invented_metrics(self):
        row = self.row("123456789012", "ebay_username", 12000)
        row.update(source="ebay_us", url="https://www.ebay.com/itm/123456789012", currency="USD")
        seller = self.loop._offer(row, "ebay_us", self.instant)["seller"]
        self.assertEqual(seller["id"], "ebay_username")
        self.assertIsNone(seller["reputation"])

    def test_product_summary_never_carries_an_individual_seller(self):
        row = copy.deepcopy(self.rows[0]) | {"scope": "product_summary"}
        self.assertIsNone(self.loop._offer(row, "mercari", self.instant)["seller"])
        row["seller"] = extracted_seller(seller_claim(), "mercari", "fixture:hash", self.instant.isoformat())
        self.assertIsNone(self.loop._offer(row, "mercari", self.instant)["seller"])

    def test_explicit_unknown_seller_does_not_resurrect_legacy_identity(self):
        row = copy.deepcopy(self.rows[0]) | {"seller": None}
        self.assertIsNone(self.loop._offer(row, "mercari", self.instant)["seller"])

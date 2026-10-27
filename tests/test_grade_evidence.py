"""Offline grading evidence; fixture claims never become physical verification."""
from datetime import datetime, timezone
import json
import socket
import unittest
from unittest.mock import patch

from pokemon_index.commerce_loop import CommerceLoop, CommerceError
from pokemon_index.marketplace_crawl import Crawler
from pokemon_index.marketplace_sources import _quality
from tests.test_marketplace_crawl import FixtureFetch

URL = "https://snkrdunk.com/apparels/162095/used/51736994"
CARD = "ja:SV4A:349/190:holo"
STAMP = datetime(2026, 10, 24, 1, tzinfo=timezone.utc)


def listing_html(*, title="リザードンex SAR SV4a 349/190", **changes):
    item = {"id": 51736994, "apparel": {"id": 162095}, "price": 65999,
            "commaPrice": "¥65,999", "wearCount": "tradingCardSingleConditionPSA10",
            "displayWearCount": "PSA10", "isDisplaySold": False,
            "status": 0, "statusText": "出品中/入札中"}
    item.update(changes)
    flight = ["$", "$L1", None, {"apparelId": 162095, "listingId": 51736994,
                                  "usedApparelData": {"apparelUsedItem": item}}]
    product = {"@type": "Product", "name": title, "offers": {"@type": "Offer",
               "price": "65999", "priceCurrency": "JPY", "availability": "https://schema.org/InStock"}}
    return ("<script type='application/ld+json'>" + json.dumps(product) + "</script><script>"
            "self.__next_f.push(" + json.dumps([1, "a:" + json.dumps(flight) + "\n"]) + ");</script>")


class GradeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("offline only"))
        self.network.start()

    def tearDown(self):
        self.network.stop()

    def crawl(self, **changes):
        return Crawler(FixtureFetch({URL: listing_html(**changes)}), now=lambda: STAMP).detail(URL)

    def offer(self, row):
        return CommerceLoop(None, now=lambda: STAMP.isoformat())._offer(row, "snkrdunk", STAMP)

    def test_path_bound_condition_only_grade_survives_generic_catalog_title(self):
        row = self.crawl()
        self.assertEqual((row["grade_company"], row["grade_value"]), ("PSA", "10"))
        offer = self.offer(row)
        self.assertEqual((offer["grade"]["kind"], offer["grade"]["evidence"]), ("slab", "snkr_used_condition"))
        self.assertFalse(offer["grade"]["review_required"])
        self.assertEqual(offer["seller_condition"], "PSA10")
        self.assertEqual(offer["source_status_text"], "出品中/入札中")
        self.assertEqual(offer["certificate"], {"number_claim": None, "status": "number_missing", "physical_authenticity": "not_verified"})
        self.assertFalse(offer["grade"]["certificate_verified"])
        self.assertFalse(offer["authenticity_verified"])

    def test_each_explicit_condition_field_can_supply_a_claim_without_ocr(self):
        for changes in ({"wearCount": None}, {"displayWearCount": None}):
            with self.subTest(changes=changes):
                grade = self.offer(self.crawl(**changes))["grade"]
                self.assertEqual((grade["company"], grade["value"]), ("PSA", "10"))
                self.assertFalse(grade["review_required"])

    def test_title_condition_and_condition_field_conflicts_require_review(self):
        for changes in ({"title": "リザードン PSA9 鑑定品"}, {"displayWearCount": "PSA9"},
                        {"title": "リザードン PSA10 狙い 未鑑定"}):
            with self.subTest(changes=changes):
                offer = self.offer(self.crawl(**changes))
                self.assertTrue(offer["grade"]["review_required"])
                self.assertTrue(offer["grade"]["review_reasons"])
                self.assertFalse(offer["grade"]["certificate_verified"])

    def test_conflicting_raw_display_keeps_coded_slab_claim_visible_for_review(self):
        for condition in ("raw", "ungraded", "未鑑定"):
            with self.subTest(condition=condition):
                offer = self.offer(self.crawl(displayWearCount=condition))
                self.assertEqual((offer["grade"]["kind"], offer["grade"]["company"], offer["grade"]["value"]), ("slab", "PSA", "10"))
                self.assertEqual(offer["seller_condition"], condition)
                self.assertTrue(offer["grade"]["review_required"])
                self.assertIn("conflicting_grade_claims", offer["grade"]["review_reasons"])

    def test_unknown_and_explicit_raw_are_separate_and_platform_authentication_is_not_psa(self):
        unknown = self.offer(self.crawl(wearCount=None, displayWearCount=None))
        raw = self.offer(self.crawl(wearCount=None, displayWearCount="raw"))
        platform = self.offer(self.crawl(wearCount=None, displayWearCount="鑑定済"))
        self.assertEqual(raw["grade"]["kind"], "raw")
        self.assertFalse(raw["grade"]["review_required"])
        for offer in (unknown, platform):
            self.assertEqual((offer["grade"]["kind"], offer["grade"]["company"], offer["grade"]["value"]), ("unknown", None, None))
            self.assertTrue(offer["grade"]["review_required"])
            self.assertFalse(offer["authenticity_verified"])

    def test_special_labels_do_not_silently_join_ordinary_numeric_grade(self):
        grade = self.offer(self.crawl(wearCount="tradingCardSingleConditionBGS10", displayWearCount="BGS10 Black Label"))["grade"]
        self.assertEqual(grade["special_label"], "black_label")
        self.assertTrue(grade["review_required"])

    def test_normalized_explicit_raw_claim_is_preserved_without_inferring_missing_grade_as_raw(self):
        row = self.crawl(wearCount=None, displayWearCount=None)
        quality, review = _quality({"grade_company": "RAW", "grade_value": "raw"}, row["title"], "offline:test")
        row.update(marketplace_quality=quality, quality_review_required=review)
        offer = self.offer(row)
        self.assertEqual((offer["grade"]["kind"], offer["grade"]["evidence"]), ("raw", "structured_raw_claim"))
        self.assertFalse(offer["grade"]["review_required"])

    def test_sold_used_item_overrides_generic_instock_and_never_selects_or_quotes(self):
        for changes in ({"isDisplaySold": True}, {"status": 9, "statusText": "運営への到着待ち"}):
            with self.subTest(changes=changes):
                row = self.crawl(**changes)
                self.assertEqual((row["availability"], row["status"]), ("out_of_stock", "sold_out"))
                class Saved:
                    def detail(self, url):
                        self_url = url
                        assert self_url == URL
                        return row
                loop = CommerceLoop(Saved(), now=lambda: STAMP.isoformat())
                offer = loop.research("owner-a", {"card_id": CARD, "query": "Charizard", "platforms": ["snkrdunk"], "product_urls": [URL]})["offers"][0]
                with self.assertRaises(CommerceError) as error:
                    loop.select("owner-a", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
                self.assertEqual(error.exception.code, "offer_unavailable")
                self.assertEqual(offer["price_minor"], 65999)

    def test_review_rows_cannot_bypass_ui_to_acquire_selection(self):
        row = self.crawl(displayWearCount="PSA9")
        class Saved:
            def detail(self, _url):
                return row
        loop = CommerceLoop(Saved(), now=lambda: STAMP.isoformat())
        offer = loop.research("owner-a", {"card_id": CARD, "query": "Charizard", "platforms": ["snkrdunk"], "product_urls": [URL]})["offers"][0]
        with self.assertRaises(CommerceError) as error:
            loop.select("owner-a", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
        self.assertEqual(error.exception.code, "grade_review_required")

    def test_certificate_number_is_a_claim_not_authentication(self):
        offer = self.offer(self.crawl(title="リザードン PSA10 鑑定品 cert 12345678"))
        self.assertEqual(offer["certificate"]["number_claim"], "12345678")
        self.assertEqual(offer["certificate"]["status"], "not_checked")
        self.assertEqual(offer["certificate"]["physical_authenticity"], "not_verified")

    def test_quantity_uses_only_path_bound_card_count_label_not_inventory_quantity(self):
        for size, expected in (({"localizedName": "1枚", "quantity": 0}, 1),
                               ({"localizedName": "12枚", "quantity": 0}, 12),
                               ({"localizedName": "M", "quantity": 1}, None),
                               ({"localizedName": "0枚", "quantity": 9}, None)):
            with self.subTest(size=size):
                self.assertEqual(self.offer(self.crawl(size=size))["listing_quantity"], expected)

    def test_changed_grading_condition_certificate_or_lot_never_reaches_quote_provider(self):
        for changes in ({"displayWearCount": "PSA9"}, {"title": "リザードン PSA10 Black Label"},
                        {"title": "リザードン PSA10 cert 12345678"}, {"size": {"localizedName": "2枚"}}):
            with self.subTest(changes=changes):
                first, refreshed = self.crawl(size={"localizedName": "1枚"}), self.crawl(**changes)
                class Saved:
                    calls = 0
                    def detail(self, _url):
                        self.calls += 1
                        return first if self.calls == 1 else refreshed
                class Provider:
                    url_preview = True
                    def preview_before(self, *_args, **_kwargs):
                        raise AssertionError("changed evidence must stop before quoting")
                loop = CommerceLoop(Saved(), now=lambda: STAMP.isoformat(), forwarders={"buyship": Provider()})
                offer = loop.research("owner-a", {"card_id": CARD, "query": "Charizard", "platforms": ["snkrdunk"], "product_urls": [URL]})["offers"][0]
                selection = loop.select("owner-a", {"card_id": CARD, "offer_id": offer["offer_id"], "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"], "currency": offer["currency"]})
                with self.assertRaises(CommerceError) as error:
                    loop.handoff("owner-a", {"selection_id": selection["selection_id"], "forwarder": "buyship", "destination": {"country": "HK"}})
                self.assertEqual(error.exception.code, "offer_changed")


if __name__ == "__main__":
    unittest.main()

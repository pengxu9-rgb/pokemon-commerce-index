"""Fake official responses traverse research, selection and canonical handoff."""
import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch

from pokemon_index.commerce_loop import CommerceLoop
from pokemon_index.ebay_official import BrowseClient, DISCLOSURE, EbayOfficialCrawler

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)
URL = "https://www.ebay.com/itm/123456789012"
AFFILIATE = URL + "?mkevt=1&mkcid=1&campid=5331234567&toolid=10001&customid=pilot_1"
CARD = "ja:SV2A:173/165:standard"


def official_item():
    return {"itemId": "v1|123456789012|0", "itemWebUrl": URL, "itemAffiliateWebUrl": AFFILIATE,
        "title": "Pikachu SV2a 173/165 PSA 10", "buyingOptions": ["FIXED_PRICE"],
        "price": {"value": "12.34", "currency": "USD"}, "seller": {"username": "synthetic_seller"},
        "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK"}],
        "localizedAspects": [{"name": "Professional Grader", "value": "PSA"},
            {"name": "Grade", "value": "10"}, {"name": "Certification Number", "value": "99900194"}]}


class NoFallback:
    def search(self, *_args, **_kwargs):
        raise AssertionError("official eBay failure cannot fall back to crawling")

    detail = search


class EbayCommerceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.calls, self.change = [], {}

        def transport(method, path, **kwargs):
            self.calls.append((method, path))
            if method == "POST":
                return {"access_token": "synthetic-token", "expires_in": 3600}
            value = official_item() | copy.deepcopy(self.change)
            return {"itemSummaries": [value], "total": 1} if "/search?" in path else value

        client = BrowseClient("synthetic-id", "synthetic-secret", allow_network=True,
            production_approved=True, display_approved=True, request_budget=6,
            read_until=NOW + timedelta(minutes=10), now=lambda: NOW,
            affiliate_campaign_id="5331234567", affiliate_approved=True, transport=transport)
        self.loop = CommerceLoop(EbayOfficialCrawler(NoFallback(), client), now=lambda: NOW.isoformat())

    def research(self):
        return self.loop.research("owner", {"card_id": CARD, "query": "Pikachu PSA 10", "platforms": ["ebay"]})

    def test_quote_handoff_preserves_original_url_and_unverified_certificate(self):
        with patch("socket.socket.connect", side_effect=AssertionError("offline only")):
            research = self.research()
            offer = research["offers"][0]
            self.assertEqual(offer["url"], URL)
            self.assertEqual(offer["price_minor"], 1234)
            self.assertEqual(offer["purchase_link"], {"kind": "epn_affiliate", "url": AFFILIATE, "disclosure": DISCLOSURE})
            self.assertEqual(offer["grade"]["value"], "10")
            self.assertFalse(offer["grade"]["certificate_verified"])
            self.assertEqual(offer["certificate"]["status"], "not_checked")
            selected = self.loop.select("owner", {"card_id": CARD, "offer_id": offer["offer_id"],
                "expected_observed_at": offer["observed_at"], "expected_price_minor": 1234, "currency": "USD"})
            handoff = self.loop.handoff("owner", {"selection_id": selected["selection_id"],
                "forwarder": "buyship", "destination": {"country": "HK"}})
        self.assertEqual(handoff["product_url"], URL)
        self.assertEqual(handoff["status"], "manual_handoff_required")
        self.assertIsNone(handoff["quote"])
        self.assertIsNone(handoff["purchase_action"])
        self.assertFalse(handoff["order_created"])
        self.assertEqual(len(self.calls), 3)  # one token, one search, one refresh
        serialized = json.dumps([research, selected, handoff])
        self.assertNotIn("synthetic-secret", serialized)
        self.assertNotIn("synthetic-token", serialized)

    def test_wrong_affiliate_item_is_omitted_without_replacing_canonical_listing(self):
        self.change = {"itemAffiliateWebUrl": AFFILIATE.replace("123456789012", "999999999999")}
        offer = self.research()["offers"][0]
        self.assertEqual(offer["url"], URL)
        self.assertNotIn("purchase_link", offer)

    def test_conflicting_grade_cannot_become_a_displayed_authenticated_offer(self):
        self.change = {"title": "Pikachu PSA 9"}
        result = self.research()
        self.assertEqual(result["offers"], [])
        self.assertFalse(result["purchasable"])


if __name__ == "__main__":
    unittest.main()

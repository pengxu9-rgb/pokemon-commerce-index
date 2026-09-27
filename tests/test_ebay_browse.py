"""eBay Browse observations are current asks pending photo review."""

import copy
import sqlite3
import unittest

from pokemon_index import core, ebay_browse


TIME = "2026-09-27T03:00:00Z"


def item():
    return {"itemId": "v1|123456789012|0", "title": "Pokemon Pikachu SV2a 173/165",
            "itemWebUrl": "https://www.ebay.com/itm/123456789012",
            "listingMarketplaceId": "EBAY_US", "buyingOptions": ["FIXED_PRICE"],
            "price": {"value": "12.34", "currency": "USD"},
            "seller": {"username": "fixture_seller"},
            "itemCreationDate": "2026-09-26T00:00:00Z",
            "image": {"imageUrl": "https://i.ebayimg.com/images/g/example/s-l1600.jpg"}}


class EbayBrowseTests(unittest.TestCase):
    def test_exact_decimal_and_photo_refs(self):
        row = ebay_browse.normalize_item(item(), TIME)
        self.assertEqual(row["price_minor"], 1234)
        self.assertEqual(row["status"], "on_sale")
        self.assertEqual(row["resolution_gate"], "photo_required")
        self.assertEqual(len(ebay_browse.photo_candidates(item(), TIME)["photo_refs"]), 1)
        self.assertEqual(ebay_browse.normalize_search({"total": 0}, TIME), [])

    def test_refuses_auction_ended_or_mispriced_listing(self):
        changes = [
            {"buyingOptions": ["AUCTION"]},
            {"itemEndDate": "2026-09-26T00:00:00Z"},
            {"price": {"value": "12.345", "currency": "USD"}},
            {"price": {"value": "12.34", "currency": "JPY"}},
            {"listingMarketplaceId": "EBAY_GB"},
            {"itemWebUrl": "https://not-ebay.example/itm/123456789012"},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                ebay_browse.normalize_item(item() | change, TIME)
        bad = copy.deepcopy(item())
        bad["image"]["imageUrl"] = "https://other.example/photo.jpg"
        with self.assertRaises(ValueError):
            ebay_browse.photo_candidates(bad, TIME)

    def test_search_observations_cannot_auto_match_priceable_unit(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        try:
            core.init_db(db)
            core.register_source(db, {"source": "ebay_us", "rights_reference": "synthetic test fixture",
                                      "ingest_allowed": True, "display_allowed": False,
                                      "retention_days": 1, "listing_ttl_hours": 6})
            core.import_cards(db, [{"language": "ja", "set_code": "SV2a",
                                    "collector_number": "173/165", "variant": "standard",
                                    "name": "Pikachu", "provenance": "fixture",
                                    "rights_reference": "fixture", "display_allowed": False}])
            rows = ebay_browse.normalize_search({"itemSummaries": [item()]}, TIME)
            result = core.import_observations(db, rows)
            self.assertEqual(result, {"imported": 1, "unresolved": 1})
            listing = db.execute("SELECT unit_id,resolution_method FROM listing").fetchone()
            self.assertIsNone(listing["unit_id"])
            self.assertEqual(listing["resolution_method"], "unresolved")
            # Even an explicit card_id cannot bypass this source's photo gate.
            unit, method = core.resolve(db, rows[0] | {"card_id": "ja:SV2A:173/165:standard"})
            self.assertIsNone(unit)
            self.assertEqual(method, "unresolved")
            with self.assertRaisesRegex(ValueError, "six hours"):
                core.register_source(db, {"source": "ebay_us", "rights_reference": "synthetic test fixture",
                                          "ingest_allowed": True, "display_allowed": True,
                                          "retention_days": 1, "listing_ttl_hours": 24})
        finally:
            db.close()

    def test_production_probe_needs_explicit_approval(self):
        with self.assertRaisesRegex(ValueError, "explicit eBay approval"):
            ebay_browse.BrowseProbe("id", "secret", environment="production")
        with self.assertRaisesRegex(ValueError, "credentials are missing"):
            ebay_browse.BrowseProbe("", "", environment="sandbox")

    def test_probe_makes_one_fixed_price_search_and_redacts_results(self):
        probe = ebay_browse.BrowseProbe("fixture-id", "fixture-secret")
        calls = []

        def fake_request(method, path, **kwargs):
            calls.append((method, path, kwargs))
            if path == "/identity/v1/oauth2/token":
                return {"access_token": "fixture-token"}
            return {"total": 1, "itemSummaries": [item()]}

        probe._json = fake_request
        output = probe.search_shape("Pokemon Pikachu")
        self.assertEqual(len(calls), 2)
        self.assertIn("buyingOptions%3A%7BFIXED_PRICE%7D", calls[1][1])
        self.assertEqual(output["item_count"], 1)
        self.assertNotIn("fixture-token", str(output))
        self.assertNotIn("fixture-secret", str(output))


if __name__ == "__main__":
    unittest.main()

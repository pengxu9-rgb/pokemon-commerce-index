"""Offline contract/regression tests: every transport is an injected fake."""
import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from pokemon_index.ebay_official import (
    BrowseClient, DISCLOSURE, EbayOfficialCrawler, OfficialEbayError,
    configure_official_ebay, validate_purchase_link,
)

NOW = datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
URL = "https://www.ebay.com/itm/123456789012"
AFFILIATE = URL + "?mkevt=1&mkcid=1&campid=5331234567&toolid=10001&customid=pilot_1"


def item():
    return {"itemId": "v1|123456789012|0", "itemWebUrl": URL,
            "itemAffiliateWebUrl": AFFILIATE, "title": "Pokemon Pikachu PSA 10 slab",
            "listingMarketplaceId": "EBAY_US", "buyingOptions": ["FIXED_PRICE"],
            "price": {"value": "12.34", "currency": "USD"},
            "seller": {"username": "fixture_seller"},
            "estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK",
                                          "estimatedAvailableQuantity": 1}],
            "localizedAspects": [{"name": "Professional Grader", "value": "PSA"},
                                 {"name": "Grade", "value": "10"},
                                 {"name": "Certification Number", "value": "99900194"}]}


class Fake:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else {"itemSummaries": [item()], "total": 1}
        self.calls = []

    def __call__(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if method == "POST":
            return {"access_token": "synthetic-token", "expires_in": 7200}
        return copy.deepcopy(self.payload)


class Fallback:
    mode = "on_demand_research"

    def __init__(self):
        self.calls = []

    def search(self, source, query, limit=3):
        self.calls.append((source, query, limit))
        return {"listings": [], "status": "unavailable"}

    def detail(self, url):
        self.calls.append(url)
        return {"url": url}


def client(transport, **kwargs):
    config = dict(allow_network=True, production_approved=True, display_approved=True,
                  read_until=NOW + timedelta(minutes=10), request_budget=8,
                  affiliate_campaign_id="5331234567", affiliate_approved=True,
                  affiliate_reference_id="pilot_1", transport=transport, now=lambda: NOW)
    config.update(kwargs)
    return BrowseClient("synthetic-id", "synthetic-secret", **config)


class OfficialEbayTests(unittest.TestCase):
    def test_default_off_even_when_credentials_are_present(self):
        fake, fallback = Fake(), Fallback()
        self.assertIs(configure_official_ebay(fallback, {"EBAY_CLIENT_ID": "id", "EBAY_CLIENT_SECRET": "secret"},
                                             transport=fake, now=lambda: NOW), fallback)
        disabled = BrowseClient("id", "secret", transport=fake, now=lambda: NOW)
        with self.assertRaisesRegex(OfficialEbayError, "disabled"):
            disabled.search("Pikachu")
        self.assertEqual(fake.calls, [])

    def test_each_explicit_gate_and_bounded_configuration_is_required(self):
        changes = [{"production_approved": False}, {"display_approved": False},
                   {"read_until": None}, {"read_until": NOW},
                   {"read_until": NOW + timedelta(minutes=91)},
                   {"read_until": "2026-10-26T00:10:00"},
                   {"request_budget": None}, {"request_budget": True}, {"request_budget": 21},
                   {"affiliate_approved": False}, {"affiliate_campaign_id": "123"},
                   {"affiliate_reference_id": "peng@example.test"},
                   {"affiliate_reference_id": "pilot,affiliateCampaignId=bad"}]
        for change in changes:
            fake = Fake()
            with self.subTest(change=change), self.assertRaises(OfficialEbayError):
                client(fake, **change)
            self.assertEqual(fake.calls, [])
        with self.assertRaisesRegex(OfficialEbayError, "credentials_required"):
            BrowseClient("", "", allow_network=True, production_approved=True, display_approved=True)

    def test_token_search_and_epn_header_preserve_claims_without_verification(self):
        fake = Fake()
        rows = client(fake).search("Pikachu PSA 10")["listings"]
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[0][0:2], ("POST", "/identity/v1/oauth2/token"))
        params = parse_qs(urlsplit(fake.calls[1][1]).query)
        self.assertEqual(params, {"q": ["Pikachu PSA 10"], "limit": ["3"],
                                  "filter": ["buyingOptions:{FIXED_PRICE}"]})
        headers = fake.calls[1][2]["headers"]
        self.assertEqual(headers["X-EBAY-C-MARKETPLACE-ID"], "EBAY_US")
        self.assertEqual(headers["X-EBAY-C-ENDUSERCTX"],
                         "affiliateCampaignId=5331234567,affiliateReferenceId=pilot_1")
        row = rows[0]
        self.assertEqual(row["price_minor"], 1234)
        self.assertEqual(row["url"], URL)
        self.assertEqual(row["availability"], "available")
        self.assertEqual(row["grade_company"], "PSA")
        self.assertEqual(row["grade_value"], "10")
        self.assertEqual(row["marketplace_quality"]["certificate_number_claim"], "99900194")
        self.assertFalse(row["marketplace_quality"]["certificate_verified"])
        self.assertFalse(row["marketplace_quality"]["authenticity_verified"])
        self.assertEqual(row["purchase_link"], {"kind": "epn_affiliate", "url": AFFILIATE,
                                               "disclosure": DISCLOSURE})
        self.assertNotIn("synthetic-secret", str(rows))
        self.assertNotIn("synthetic-token", str(rows))

    def test_no_epn_config_never_uses_returned_affiliate_url(self):
        result = client(Fake(), affiliate_campaign_id=None, affiliate_reference_id=None,
                        affiliate_approved=False).search("Pikachu")
        self.assertNotIn("purchase_link", result["listings"][0])

    def test_bad_affiliate_only_removes_tracking_not_the_canonical_offer(self):
        for link in (AFFILIATE.replace("5331234567", "5339999999"),
                     AFFILIATE.replace("123456789012", "123456789013"),
                     "https://attacker.example/itm/123456789012"):
            payload = {"itemSummaries": [item() | {"itemAffiliateWebUrl": link}]}
            with self.subTest(link=link):
                row = client(Fake(payload)).search("Pikachu")["listings"][0]
                self.assertEqual(row["url"], URL)
                self.assertNotIn("purchase_link", row)

    def test_auction_conversion_ended_mismatched_and_unknown_stock_are_not_promoted(self):
        changes = [{"buyingOptions": ["AUCTION"]}, {"buyingOptions": ["FIXED_PRICE", "AUCTION"]},
                   {"itemEndDate": "2026-10-25T00:00:00Z"},
                   {"price": {"value": "12.345", "currency": "USD"}},
                   {"price": {"value": 12.34, "currency": "USD"}},
                   {"price": {"value": "12", "currency": "JPY"}},
                   {"price": {"value": "12.34", "currency": "USD", "convertedFromCurrency": "JPY"}},
                   {"itemWebUrl": URL.replace("123456789012", "123456789013")},
                   {"itemId": "v1|123456789012|1234"},
                   {"estimatedAvailabilities": [{"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]},
                   {"estimatedAvailabilities": [{"estimatedAvailabilityStatus": "IN_STOCK",
                                                 "estimatedAvailableQuantity": 0}]}]
        for change in changes:
            with self.subTest(change=change):
                self.assertEqual(client(Fake({"itemSummaries": [item() | change]})).search("Pikachu")["listings"], [])
        value = item()
        del value["estimatedAvailabilities"]
        self.assertEqual(client(Fake({"itemSummaries": [value]})).search("Pikachu")["listings"][0]["availability"], "unknown")

    def test_detail_binds_response_to_requested_listing_and_reuses_token(self):
        fake = Fake(item())
        c = client(fake)
        self.assertEqual(c.detail(URL)["url"], URL)
        c.detail(URL)
        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(fake.calls[1][1], "/buy/browse/v1/item/get_item_by_legacy_id?legacy_item_id=123456789012")
        other = item() | {"itemId": "v1|123456789013|0", "itemWebUrl": URL.replace("012", "013")}
        with self.assertRaisesRegex(OfficialEbayError, "item_mismatch"):
            client(Fake(other)).detail(URL)

    def test_budget_exhaustion_and_expiry_never_retry(self):
        fake = Fake()
        with self.assertRaisesRegex(OfficialEbayError, "budget_exhausted"):
            client(fake, request_budget=1).search("Pikachu")
        self.assertEqual(len(fake.calls), 1)
        clock = [NOW]
        fake = Fake()
        c = client(fake, now=lambda: clock[0])
        clock[0] = NOW + timedelta(minutes=10)
        with self.assertRaisesRegex(OfficialEbayError, "window_expired"):
            c.search("Pikachu")
        self.assertEqual(fake.calls, [])

    def test_crossing_deadline_during_response_discards_results(self):
        clock = [NOW]
        fake = Fake()
        def transport(*args, **kwargs):
            result = fake(*args, **kwargs)
            clock[0] = NOW + timedelta(minutes=10)
            return result
        with self.assertRaisesRegex(OfficialEbayError, "window_expired"):
            client(transport, now=lambda: clock[0]).search("Pikachu")
        self.assertEqual(len(fake.calls), 1)

    def test_tls_connect_crossing_cutoff_sends_no_http_credentials(self):
        clock, events = [NOW], []
        class Connection:
            def __init__(self, host, timeout):
                events.append(("construct", host, timeout))
            def connect(self):
                events.append(("connect",))
                clock[0] = NOW + timedelta(minutes=10)
            def request(self, *args, **kwargs):
                events.append(("request",))
                raise AssertionError("HTTP must not start after cutoff")
            def close(self):
                events.append(("close",))
        c = client(None, now=lambda: clock[0])
        with patch("pokemon_index.ebay_official.http.client.HTTPSConnection", Connection):
            with self.assertRaisesRegex(OfficialEbayError, "window_expired"):
                c.search("Pikachu")
        self.assertEqual([v[0] for v in events], ["construct", "connect", "close"])
        self.assertEqual(events[0][1], "api.ebay.com")

    def test_transport_failure_is_redacted_and_not_retried(self):
        calls = []
        def transport(*args, **kwargs):
            calls.append(args)
            raise RuntimeError("provider body synthetic-secret synthetic-token")
        with self.assertRaisesRegex(OfficialEbayError, "^ebay_official_transport_failed$"):
            client(transport).search("Pikachu")
        self.assertEqual(len(calls), 1)

    def test_duplicate_or_oversized_search_pages_fail_closed(self):
        for payload in ({"itemSummaries": [item(), item()]},
                        {"itemSummaries": [item()] * 4}, {"itemSummaries": "oops"},
                        {"itemSummaries": [item() | {"itemId": []}]}, {}):
            with self.subTest(payload=payload), self.assertRaisesRegex(OfficialEbayError, "invalid_response"):
                client(Fake(payload)).search("Pikachu")

    def test_wrapper_uses_other_producers_without_bypassing_smaller_scope(self):
        fake, fallback = Fake(), Fallback()
        wrapper = EbayOfficialCrawler(fallback, client(fake))
        wrapper.search("mercari", "Pikachu", limit=2)
        wrapper.detail("https://snkrdunk.com/apparels/123/used/456")
        self.assertEqual(len(fallback.calls), 2)
        self.assertEqual(fake.calls, [])
        wrapper.search("ebay", "Pikachu")
        self.assertEqual(len(fake.calls), 2)
        for attribute, value in (("read_only_scope", True), ("mode", "synthetic_fixture")):
            restricted = Fallback()
            setattr(restricted, attribute, value)
            with self.assertRaisesRegex(OfficialEbayError, "scope_conflict"):
                EbayOfficialCrawler(restricted, client(Fake()))

    def test_config_requires_production_and_display_approval_not_credential_presence(self):
        env = {"EBAY_CLIENT_ID": "synthetic-id", "EBAY_CLIENT_SECRET": "synthetic-secret"}
        with self.assertRaisesRegex(OfficialEbayError, "approval_required"):
            configure_official_ebay(Fallback(), env, allow_network=True,
                                    read_until=NOW + timedelta(minutes=1), request_budget=2, now=lambda: NOW)
        env.update(EBAY_PRODUCTION_APPROVED="true", EBAY_DISPLAY_APPROVED="true")
        fake = Fake()
        wrapper = configure_official_ebay(Fallback(), env, allow_network=True,
            read_until=NOW + timedelta(minutes=1), request_budget=2, now=lambda: NOW, transport=fake)
        self.assertTrue(wrapper.official_ebay_configured)
        self.assertTrue(wrapper.official_ebay_enabled)
        self.assertEqual(fake.calls, [])


class AffiliateValidationTests(unittest.TestCase):
    def validate(self, url=AFFILIATE, **kwargs):
        config = dict(source="ebay_us", native_id="v1|123456789012|0", canonical_url=URL)
        config.update(kwargs)
        return validate_purchase_link({"kind": "epn_affiliate", "url": url, "disclosure": DISCLOSURE}, **config)

    def test_valid_same_item_and_opaque_reference(self):
        self.assertEqual(self.validate()["url"], AFFILIATE)
        self.assertEqual(self.validate(AFFILIATE.replace("/itm/", "/itm/Pokemon-card/"))["kind"], "epn_affiliate")

    def test_redirect_wrong_item_host_path_duplicate_or_pii_parameters_refused(self):
        links = [AFFILIATE.replace("https:", "http:"), AFFILIATE.replace("www.ebay.com", "www.ebay.com.attacker.test"),
                 AFFILIATE.replace("www.ebay.com", "user@www.ebay.com"),
                 AFFILIATE.replace("www.ebay.com", "www.ebay.com:443"),
                 AFFILIATE.replace("123456789012", "123456789013"),
                 AFFILIATE.replace("/itm/", "/itm/%2f"), AFFILIATE + "#fragment", AFFILIATE + "#",
                 AFFILIATE.replace("123456789012?", "123456789012/?"),
                 AFFILIATE + "&campid=5331234567", AFFILIATE + "&redirect=https://attacker.test",
                 AFFILIATE + "&email=peng@example.test", AFFILIATE + "&var=1234",
                 AFFILIATE.replace("pilot_1", "peng%40example.test"),
                 AFFILIATE.replace("mkevt=1", "mkevt=2"), AFFILIATE.replace("mkcid=1", "mkcid=2"),
                 AFFILIATE.replace("campid=5331234567", "campid=123"),
                 AFFILIATE.replace("toolid=10001", "toolid=abc"),
                 AFFILIATE + "&hash=%0d%0aAuthorization:secret"]
        for link in links:
            with self.subTest(link=link), self.assertRaises(OfficialEbayError):
                self.validate(link)
        for args in ({"source": "mercari"}, {"native_id": "v1|123456789012|5"},
                     {"native_id": "123456789012"},
                     {"canonical_url": URL + "?campid=5331234567"},
                     {"campaign_id": "5339999999"}):
            with self.subTest(args=args), self.assertRaises(OfficialEbayError):
                self.validate(**args)


if __name__ == "__main__":
    unittest.main()

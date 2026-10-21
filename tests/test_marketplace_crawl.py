"""Public HTML fixtures only; all sockets are denied during these tests."""
from datetime import datetime, timezone
import json
import socket
import unittest
from unittest.mock import patch

from pokemon_index.marketplace_crawl import (
    Crawler, CrawlBlocked, PublicHTMLFetch, canonical_product_url, _PinnedHTTPS,
)

MERCARI = "https://jp.mercari.com/item/m97669071757"
SNKR = "https://snkrdunk.com/apparels/128089"
SNKR_USED = SNKR + "/used/30335981"
EBAY = "https://www.ebay.com/itm/123456789012"
STAMP = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
ROBOTS = "User-agent: *\nAllow: /\n"


def product_html(*, title="Charizard 001/102 PSA 10 鑑定済 cert 12345678", price="12700",
                 currency="JPY", availability="https://schema.org/InStock", **extra):
    product = {"@context": "https://schema.org", "@type": "Product", "name": title,
               "offers": {"@type": "Offer", "price": price, "priceCurrency": currency,
                          "availability": availability}}
    product.update(extra)
    return "<html><title>Card</title><script type='application/ld+json'>" + json.dumps(product) + "</script></html>"


def snkr_flight_html(*, listing_id=30335981, apparel_id=128089, price=34900, related_price=1):
    item = {"id": listing_id, "apparel": {"id": apparel_id}, "price": price,
            "commaPrice": "¥" + format(price, ","), "status": 0, "statusText": "出品中/入札中",
            "isDisplaySold": False, "displayWearCount": "PSA10"}
    node = ["$", "$L59", None, {"apparelId": apparel_id, "listingId": listing_id,
                                    "usedApparelData": {"apparelUsedItem": item},
                                    "relatedProduct": {"price": related_price, "id": 88888}}]
    flight = "4c:" + json.dumps(node, ensure_ascii=False) + "\n"
    # Split a record across chunks, as real streamed React Flight responses can.
    cut = len(flight) // 2
    scripts = "".join("<script>self.__next_f.push(" + json.dumps([1, chunk], ensure_ascii=False)
                      + ")</script>" for chunk in (flight[:cut], flight[cut:]))
    return "<html><meta property='og:title' content='【PSA10】ピカチュウ AR SV2a 173/165'>" + scripts + "</html>"


class FixtureFetch:
    def __init__(self, pages=None, robots=ROBOTS):
        self.pages, self.robots, self.calls = pages or {}, robots, []

    def __call__(self, url):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return {"status": 200, "body": self.robots, "headers": {"Content-Type": "text/plain"}, "url": url}
        value = self.pages.get(url, {"status": 404, "body": "Not found"})
        if isinstance(value, str):
            value = {"status": 200, "body": value, "headers": {"Content-Type": "text/html"}}
        return dict(value, url=value.get("url", url))


class PublicMarketplaceCrawlTests(unittest.TestCase):
    def setUp(self):
        self.socket = patch.object(socket.socket, "connect", side_effect=AssertionError("offline fixture only"))
        self.socket.start()

    def tearDown(self):
        self.socket.stop()

    def crawler(self, pages=None, **kwargs):
        fetch = FixtureFetch(pages)
        return Crawler(fetch, now=lambda: STAMP, **kwargs), fetch

    def test_default_network_and_ebay_access_are_closed(self):
        with self.assertRaisesRegex(CrawlBlocked, "network_disabled"):
            PublicHTMLFetch()(MERCARI)
        crawler, fetch = self.crawler()
        self.assertEqual(crawler.search("ebay_us", "Charizard")["message"], "source_access_not_authorized")
        self.assertEqual(fetch.calls, [])
        with self.assertRaisesRegex(CrawlBlocked, "source_access_not_authorized"):
            crawler.detail(EBAY)

    def test_enabled_transport_still_rejects_private_api_paths_and_private_dns(self):
        with self.assertRaisesRegex(CrawlBlocked, "marketplace_path_not_allowed"):
            PublicHTMLFetch(enabled=True)("https://jp.mercari.com/api/private")
        dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
        with patch("socket.getaddrinfo", return_value=dns), patch("socket.create_connection") as connect:
            with self.assertRaisesRegex(CrawlBlocked, "nonpublic_dns_address"):
                _PinnedHTTPS("jp.mercari.com").connect()
            connect.assert_not_called()
        with self.assertRaisesRegex(ValueError, "explicit boolean"):
            PublicHTMLFetch(enabled="false")

    def test_discover_anchor_links_then_individual_jsonld_with_unverified_psa(self):
        search = "https://jp.mercari.com/search?keyword=Charizard+PSA+10"
        crawler, fetch = self.crawler({search: "<a href='/item/m97669071757'>Card</a><a href='/item/m97669071757'>Duplicate</a>",
                                       MERCARI: product_html()})
        result = crawler.search("mercari", "Charizard PSA 10")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["candidates"]), 1)
        row = result["listings"][0]
        self.assertEqual((row["source"], row["native_id"], row["price_minor"], row["currency"]),
                         ("mercari", "m97669071757", 12700, "JPY"))
        self.assertEqual((row["scope"], row["status"], row["grade_company"], row["grade_value"]),
                         ("listing", "on_sale", "PSA", "10"))
        self.assertEqual(row["certificate_number_claim"], "12345678")
        self.assertFalse(row["certificate_verified"])
        self.assertFalse(row["authenticity_verified"])
        self.assertEqual(row["identity_status"], "unresolved")
        self.assertIsNone(row["purchase_action"])
        self.assertEqual(fetch.calls[0], "https://jp.mercari.com/robots.txt")

    def test_mercari_actual_meta_shape_preserves_ask_with_unknown_availability(self):
        html = """<html><head><title>Mercari</title>
          <meta property="og:title" content="リザードン PSA10 鑑定品">
          <meta property="product:price:currency" content="JPY">
          <meta property="product:price:amount" content="12700">
          <link rel="canonical" href="https://jp.mercari.com/item/m97669071757">
          </head><body>Public product</body></html>"""
        crawler, _ = self.crawler({MERCARI: html})
        row = crawler.detail(MERCARI)
        self.assertEqual((row["price_minor"], row["currency"], row["price_status"]), (12700, "JPY", "known"))
        self.assertEqual((row["status"], row["availability"]), ("unknown", "unknown"))
        self.assertIn("availability_unknown", row["exclusion_reasons"])

    def test_normal_page_captcha_library_reference_is_not_a_challenge(self):
        crawler, _ = self.crawler({MERCARI: product_html() + "<script>window.recaptchaConfig={enabled:true}</script>"})
        self.assertEqual(crawler.detail(MERCARI)["price_minor"], 12700)

    def test_no_server_rendered_links_is_visible_block_not_no_inventory_claim(self):
        search = "https://jp.mercari.com/search?keyword=Charizard"
        crawler, _ = self.crawler({search: "<html><div id='app'></div><script src='/app.js'></script></html>"})
        result = crawler.search("mercari", "Charizard")
        self.assertEqual((result["status"], result["message"]), ("blocked", "public_search_has_no_listing_links"))

    def test_renderer_fallback_uses_public_search_url_and_validates_anchors(self):
        search = "https://jp.mercari.com/search?keyword=Charizard"
        rendered = FixtureFetch({search: f"<a href='{MERCARI}'>Actual hydrated listing</a><a href='https://127.0.0.1/private'>Bad</a>"})
        crawler, fetch = self.crawler({search: "<div id='app'></div>", MERCARI: product_html()}, renderer=rendered)
        result = crawler.search("mercari", "Charizard")
        self.assertEqual(result["message"], "public_html_research_rendered")
        self.assertEqual([item["url"] for item in result["candidates"]], [MERCARI])
        self.assertEqual(rendered.calls, [search])
        self.assertEqual(fetch.calls[0], "https://jp.mercari.com/robots.txt")

    def test_renderer_failure_is_explicit_and_robots_cannot_be_bypassed(self):
        search = "https://jp.mercari.com/search?keyword=Charizard"
        rendered = FixtureFetch({search: "CAPTCHA challenge"})
        crawler, _ = self.crawler({search: "<div id='app'></div>"}, renderer=rendered)
        result = crawler.search("mercari", "Charizard")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("public_renderer_failed", result["message"])
        fetch = FixtureFetch({search: "<div id='app'></div>"}, robots="User-agent: *\nDisallow: /search\n")
        rendered.calls.clear()
        result = Crawler(fetch, renderer=rendered).search("mercari", "Charizard")
        self.assertEqual(result["message"], "robots_disallowed")
        self.assertEqual(rendered.calls, [])

    def test_snkr_unmapped_name_only_discovery_is_explicit(self):
        crawler, fetch = self.crawler()
        result = crawler.search("snkrdunk", "Charizard")
        self.assertEqual(result["message"], "query_mapping_required")
        self.assertEqual(fetch.calls, ["https://snkrdunk.com/robots.txt", "https://snkrdunk.com/search?keywords=Charizard"])

    def test_snkr_product_floor_never_becomes_listing_ask(self):
        aggregate = {"@type": "AggregateOffer", "lowPrice": "8000", "highPrice": "12000",
                     "priceCurrency": "JPY", "offerCount": 9}
        crawler, _ = self.crawler({SNKR: product_html(offers=aggregate)}, snkr_seed_urls=[SNKR])
        row = crawler.search("snkrdunk", "Charizard 001/102")["listings"][0]
        self.assertEqual(row["scope"], "product_summary")
        self.assertIsNone(row["price_minor"])
        self.assertEqual(row["status"], "unknown")
        self.assertIn("product_summary_not_listing", row["exclusion_reasons"])

    def test_snkr_verified_used_path_can_preserve_individual_ask(self):
        crawler, _ = self.crawler({SNKR_USED: product_html()}, snkr_seed_urls=[SNKR_USED])
        row = crawler.search("snkrdunk", "Charizard 001/102")["listings"][0]
        self.assertEqual((row["scope"], row["native_id"], row["price_minor"]), ("listing", "30335981", 12700))

    def test_snkr_flight_record_binds_all_listing_ids_and_ignores_related_prices(self):
        crawler, _ = self.crawler({SNKR_USED: snkr_flight_html()})
        row = crawler.detail(SNKR_USED)
        self.assertEqual((row["price_minor"], row["currency"]), (34900, "JPY"))
        self.assertEqual(row["currency_basis"], "japanese_site_yen_display")
        self.assertEqual(row["source_status_text"], "出品中/入札中")
        self.assertEqual(row["status"], "unknown")
        self.assertFalse(row["certificate_verified"])
        for kwargs in ({"listing_id": 99999999}, {"apparel_id": 999999}, {"price": 50000}):
            crawler, _ = self.crawler({SNKR_USED: snkr_flight_html(**kwargs)})
            row = crawler.detail(SNKR_USED)
            self.assertEqual(row["price_minor"], 50000 if kwargs == {"price": 50000} else None)

    def test_snkr_seed_discovers_real_used_anchors_before_catalog_summary(self):
        crawler, _ = self.crawler({SNKR: f"<title>Pikachu SV2a 173/165</title><a href='/apparels/128089/used/30335981'>Used listing</a>",
                                  SNKR_USED: snkr_flight_html()}, snkr_seed_urls=[SNKR])
        result = crawler.search("snkrdunk", "Pikachu 173/165", limit=1)
        self.assertEqual(result["candidates"][0]["url"], SNKR_USED)
        self.assertEqual(result["listings"][0]["price_minor"], 34900)

    def test_snkr_global_seed_cannot_answer_different_number_or_unmapped_name(self):
        for query in ("Charizard 004/102", "Pikachu SV3a 173/165", "Charizard", "Pikachu SV2a 172",
                      "Charizard 173/165", "Charizard SV2a 173/165", "Mysterymon 173/165"):
            crawler, _ = self.crawler({SNKR_USED: snkr_flight_html()}, snkr_seed_urls=[SNKR_USED])
            result = crawler.search("snkrdunk", query)
            self.assertEqual(result["message"], "query_mapping_required", query)
            self.assertEqual(result["listings"], [], query)
            self.assertEqual(result["candidates"], [], query)

    def test_known_named_contradiction_is_rejected_in_public_search_despite_same_number(self):
        for query in ("Charizard 173/165", "Charizard SV2a 173/165", "リザードン 173/165"):
            from urllib.parse import urlencode
            search = "https://snkrdunk.com/search?" + urlencode({"keywords": query})
            crawler, _ = self.crawler({search: f"<a href='{SNKR_USED}'>Recommended card</a>", SNKR_USED: snkr_flight_html()})
            result = crawler.search("snkrdunk", query)
            self.assertEqual(result["listings"], [], query)
            self.assertEqual(result["message"], "query_mapping_required", query)

    def test_unknown_seed_name_needs_literal_grounding_but_public_search_stays_unverified(self):
        unknown = "https://snkrdunk.com/apparels/99999/used/88888888"
        crawler, _ = self.crawler({unknown: product_html(title="Mysterymon 173/165")}, snkr_seed_urls=[unknown])
        row = crawler.search("snkrdunk", "Mysterymon 173/165")["listings"][0]
        self.assertEqual(row["identity_status"], "unresolved")
        search = "https://snkrdunk.com/search?keywords=Unknownmon+173%2F165"
        crawler, _ = self.crawler({search: f"<a href='{SNKR_USED}'>Search result</a>", SNKR_USED: snkr_flight_html()})
        row = crawler.search("snkrdunk", "Unknownmon 173/165")["listings"][0]
        self.assertEqual(row["identity_status"], "unresolved")
        self.assertEqual(row["name_match_status"], "identity_unverified")

    def test_unsupported_unicode_seed_names_cannot_disappear_during_grounding(self):
        for query in ("리자몽 173/165", "Чаризард 173/165"):
            with self.subTest(query=query):
                crawler, _ = self.crawler({SNKR_USED: snkr_flight_html()}, snkr_seed_urls=[SNKR_USED])
                result = crawler.search("snkrdunk", query)
                self.assertEqual(result["message"], "query_mapping_required")
                self.assertEqual(result["listings"], [])
        for title, expected in (("리자몽드래곤 173/165", 0), ("리자몽 173/165", 1)):
            crawler, _ = self.crawler({SNKR_USED: product_html(title=title)}, snkr_seed_urls=[SNKR_USED])
            self.assertEqual(len(crawler.search("snkrdunk", "리자몽 173/165")["listings"]), expected)

    def test_internal_identity_digits_are_preserved_for_seed_name_grounding(self):
        for title, expected in (("Porygon 173/165", 0), ("Porygon2 173/165", 1)):
            crawler, _ = self.crawler({SNKR_USED: product_html(title=title)}, snkr_seed_urls=[SNKR_USED])
            result = crawler.search("snkrdunk", "Porygon2 173/165")
            self.assertEqual(len(result["listings"]), expected, title)

    def test_sitemap_fallback_cannot_ground_an_unknown_name_from_number_alone(self):
        sitemap = "https://snkrdunk.com/sitemap/cards.xml"
        body = f"<urlset><url><loc>{SNKR_USED}</loc></url></urlset>"
        crawler, _ = self.crawler({sitemap: {"status": 200, "body": body, "headers": {"content-type": "application/xml"}},
                                  SNKR_USED: snkr_flight_html()}, snkr_sitemap_urls=[sitemap])
        result = crawler.search("snkrdunk", "Unknownmon 173/165")
        self.assertEqual(result["listings"], [])
        self.assertEqual(result["message"], "query_mapping_required")

    def test_mewtwo_name_does_not_also_claim_mew(self):
        search = "https://jp.mercari.com/search?keyword=Mew+173%2F165"
        crawler, _ = self.crawler({search: f"<a href='{MERCARI}'>Result</a>", MERCARI: product_html(title="ミュウツー 173/165")})
        self.assertEqual(crawler.search("mercari", "Mew 173/165")["listings"], [])

    def test_snkr_verified_public_search_discovers_without_any_configured_seed(self):
        search = "https://snkrdunk.com/search?keywords=Pikachu+173%2F165"
        wrong = "https://snkrdunk.com/apparels/845611/used/99999999"
        crawler, fetch = self.crawler({search: f"<a href='{wrong}'>Promoted card</a><a href='{SNKR_USED}'>Matching used item</a>",
                                       wrong: product_html(title="Charizard 004/102"), SNKR_USED: snkr_flight_html()})
        result = crawler.search("snkrdunk", "Pikachu 173/165", limit=3)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["message"], "public_search_query_discovery")
        self.assertEqual([row["native_id"] for row in result["listings"]], ["30335981"])
        self.assertEqual(result["listings"][0]["query_match_basis"], "collector_context")
        self.assertLessEqual(len(fetch.calls), 8)

    def test_public_snkr_catalog_result_follows_only_same_product_used_anchors(self):
        search = "https://snkrdunk.com/search?keywords=Pikachu+173%2F165"
        unrelated = "https://snkrdunk.com/apparels/99999/used/88888888"
        catalog = ("<title>Pikachu SV2a 173/165</title>"
                   f"<a href='{SNKR_USED}'>Individual item</a><a href='{unrelated}'>Recommended other card</a>")
        crawler, fetch = self.crawler({search: f"<a href='{SNKR}'>Product</a>", SNKR: catalog, SNKR_USED: snkr_flight_html()})
        result = crawler.search("snkrdunk", "Pikachu 173/165", limit=3)
        self.assertEqual([row["url"] for row in result["listings"]], [SNKR_USED])
        self.assertEqual(len(result["product_summaries"]), 1)
        self.assertNotIn(unrelated, fetch.calls)

    def test_snkr_query_set_and_number_both_bind_and_name_only_public_results_stay_unverified(self):
        search = "https://snkrdunk.com/search?keywords=Pikachu"
        crawler, _ = self.crawler({search: f"<a href='{SNKR_USED}'>Result</a>", SNKR_USED: snkr_flight_html()})
        row = crawler.search("snkrdunk", "Pikachu")["listings"][0]
        self.assertEqual(row["query_match_basis"], "public_search_query_identity_unverified")
        self.assertEqual(row["identity_status"], "unresolved")
        for query, expected in (("Pikachu SV2a 173/165", 1), ("Pikachu SV3a 173/165", 0),
                                ("Pikachu SV2a 173", 1), ("Pikachu SV2a 172", 0)):
            crawler, _ = self.crawler({SNKR_USED: snkr_flight_html()}, snkr_seed_urls=[SNKR_USED])
            self.assertEqual(len(crawler.search("snkrdunk", query)["listings"]), expected, query)

    def test_mercari_query_number_also_filters_wrong_detail_titles(self):
        search = "https://jp.mercari.com/search?keyword=Pikachu+173%2F165"
        crawler, _ = self.crawler({search: f"<a href='{MERCARI}'>Card</a>", MERCARI: product_html(title="Charizard 004/102")})
        result = crawler.search("mercari", "Pikachu 173/165")
        self.assertEqual(result["listings"], [])
        self.assertEqual(result["candidates"], [])

    def test_rsc_javascript_is_not_evaluated_and_conflicting_item_records_fail_closed(self):
        crawler, _ = self.crawler({SNKR_USED: snkr_flight_html() + snkr_flight_html(price=99999)})
        self.assertIsNone(crawler.detail(SNKR_USED)["price_minor"])
        payload = "<title>PSA10 card</title><script>self.__next_f.push([1, process.exit(1)])</script>"
        crawler, _ = self.crawler({SNKR_USED: payload})
        self.assertIsNone(crawler.detail(SNKR_USED)["price_minor"])

    def test_configured_public_sitemap_finds_used_and_summary_urls_only(self):
        sitemap = "https://snkrdunk.com/sitemap/cards.xml"
        body = f"<urlset xmlns='http://www.sitemaps.org/schemas/sitemap/0.9'><url><loc>{SNKR_USED}</loc></url><url><loc>https://127.0.0.1/admin</loc></url></urlset>"
        crawler, fetch = self.crawler({sitemap: {"status": 200, "body": body, "headers": {"content-type": "application/xml"}},
                                       SNKR_USED: product_html()}, snkr_sitemap_urls=[sitemap])
        result = crawler.search("snkrdunk", "Charizard 001/102")
        self.assertEqual([item["url"] for item in result["candidates"]], [SNKR_USED])
        self.assertFalse(any("127.0.0.1" in url for url in fetch.calls))

    def test_authorized_ebay_public_search_uses_native_currency_minor_units(self):
        search = "https://www.ebay.com/sch/i.html?_nkw=Charizard"
        crawler, _ = self.crawler({search: f"<a href='{EBAY}'>Card</a>",
                                  EBAY: product_html(price="99.50", currency="USD")}, authorized_sources=["ebay_us"])
        row = crawler.search("ebay", "Charizard")["listings"][0]
        self.assertEqual((row["price_minor"], row["currency"]), (9950, "USD"))

    def test_money_is_explicit_positive_exact_minor_units_never_guessed(self):
        for price, currency in (("1,200", "JPY"), ("1.01", "JPY"), (0, "USD"),
                                ("NaN", "USD"), (True, "USD"), ("12", "XYZ"), ("12", None)):
            with self.subTest(price=price, currency=currency):
                crawler, _ = self.crawler({MERCARI: product_html(price=price, currency=currency)})
                row = crawler.detail(MERCARI)
                self.assertIsNone(row["price_minor"])
                self.assertEqual(row["price_status"], "unknown")

    def test_availability_is_never_inferred_from_price(self):
        for availability, status in ((None, "unknown"), ("Available", "unknown"),
                                     ("https://schema.org/SoldOut", "sold_out")):
            crawler, _ = self.crawler({MERCARI: product_html(availability=availability)})
            row = crawler.detail(MERCARI)
            self.assertEqual(row["status"], status)

    def test_primary_visible_sold_out_overrides_stale_instock_metadata(self):
        for cue in ("<h1>売り切れました</h1><button disabled>Sold out</button>",
                    "<h1>This item is sold out.</h1>", "<button><span>Out of stock</span></button>",
                    "<h1>This listing has ended</h1>", "<button disabled>Currently unavailable</button>",
                    "<div role='status'>Sold out</div>", "<h2>Sold out</h2>",
                    "<div role='alert'>This product is no longer available.</div>",
                    "<main><h1>売り切れました"):
            with self.subTest(cue=cue):
                crawler, _ = self.crawler({MERCARI: product_html(price="100") + cue})
                row = crawler.detail(MERCARI)
                self.assertEqual((row["availability"], row["status"]), ("out_of_stock", "sold_out"))
                self.assertIn("availability_evidence_conflict", row["exclusion_reasons"])

    def test_hidden_recommended_and_prose_sold_out_text_is_not_primary_stock(self):
        for cue in ("<div hidden><button disabled>Sold out</button></div>",
                    "<div aria-hidden='true'><h1>売り切れました</h1></div>",
                    "<div style='display: none'><button>Sold out</button></div>",
                    "<aside><button disabled>Sold out</button></aside>",
                    "<section class='related-products'><button>Sold out</button></section>",
                    "<section class='related-products'><h2>Sold out</h2><div role='status'>Sold out</div></section>",
                    "<div hidden><div role='alert'>This listing has ended</div></div>",
                    "<p>Other listings may be sold out.</p>",
                    "<script>const status='Sold out';</script>"):
            with self.subTest(cue=cue):
                crawler, _ = self.crawler({MERCARI: product_html(price="100") + cue})
                row = crawler.detail(MERCARI)
                self.assertEqual((row["price_minor"], row["availability"], row["status"]), (100, "in_stock", "on_sale"))

    def test_same_listing_jsonld_and_og_money_must_agree_in_amount_and_currency(self):
        for metadata in (("200", "JPY"), ("100", "USD"), ("1", "USD")):
            with self.subTest(metadata=metadata):
                html = (product_html(price="100")
                        + f"<meta property='product:price:amount' content='{metadata[0]}'>"
                        + f"<meta property='product:price:currency' content='{metadata[1]}'>")
                crawler, _ = self.crawler({MERCARI: html})
                row = crawler.detail(MERCARI)
                self.assertEqual((row["price_minor"], row["currency"], row["price_status"]), (None, None, "unknown"))
                self.assertIn("price_evidence_conflict", row["exclusion_reasons"])
                self.assertNotEqual(row["status"], "on_sale")

    def test_equivalent_money_metadata_preserves_listing_ask_and_stock(self):
        html = (product_html(price="100", offers={"@type": "Offer", "price": "100", "priceCurrency": "JPY",
                    "availability": "https://schema.org/InStock",
                    "priceSpecification": {"price": "100.0", "priceCurrency": "JPY"}})
                + "<meta property='product:price:amount' content='100.00'>"
                + "<meta property='product:price:amount' content='100'>"
                + "<meta property='product:price:currency' content='JPY'>")
        crawler, _ = self.crawler({MERCARI: html})
        row = crawler.detail(MERCARI)
        self.assertEqual((row["price_minor"], row["currency"], row["status"]), (100, "JPY", "on_sale"))

    def test_duplicate_and_nested_same_listing_money_conflicts_fail_closed(self):
        html = (product_html(price="100")
                + "<meta property='product:price:amount' content='100'>"
                + "<meta property='product:price:amount' content='200'>"
                + "<meta property='product:price:currency' content='JPY'>")
        nested = product_html(offers={"@type": "Offer", "price": "100", "priceCurrency": "JPY",
            "availability": "https://schema.org/InStock",
            "priceSpecification": {"price": "200", "priceCurrency": "JPY"}})
        for body in (html, nested):
            crawler, _ = self.crawler({MERCARI: body})
            row = crawler.detail(MERCARI)
            self.assertIsNone(row["price_minor"])
            self.assertIn("price_evidence_conflict", row["exclusion_reasons"])

    def test_bound_snkr_money_agrees_with_primary_metadata_not_unrelated_floor(self):
        for amount, expected in (("34900", 34900), ("34901", None)):
            html = (snkr_flight_html(related_price=1)
                    + f"<meta property='product:price:amount' content='{amount}'>"
                    + "<meta property='product:price:currency' content='JPY'>")
            crawler, _ = self.crawler({SNKR_USED: html})
            row = crawler.detail(SNKR_USED)
            self.assertEqual(row["price_minor"], expected)
            self.assertEqual(row["status"], "unknown")
            if expected is None:
                self.assertIn("price_evidence_conflict", row["exclusion_reasons"])

    def test_contradictory_refresh_never_reaches_quote_provider(self):
        from pokemon_index.commerce_loop import CommerceError, CommerceLoop
        class NoQuote:
            def __init__(self):
                self.calls = 0

            def preview(self, *_args):
                self.calls += 1
                raise AssertionError("contradictory current page must not reach provider")
        contradictions = ("<h1>売り切れました</h1><button disabled>Sold out</button>",
            "<h1>This listing has ended</h1>", "<button disabled>Currently unavailable</button>",
            "<div role='status'>Sold out</div>", "<h2>Sold out</h2>",
            "<meta property='product:price:amount' content='200'><meta property='product:price:currency' content='JPY'>",
            "<meta property='product:price:amount' content='100'><meta property='product:price:currency' content='USD'>")
        for cue in contradictions:
            with self.subTest(cue=cue):
                crawler, fetch = self.crawler({MERCARI: product_html(price="100")})
                provider = NoQuote()
                loop = CommerceLoop(crawler, now=lambda: STAMP.isoformat(), forwarders={"buyship": provider})
                offer = loop.research("owner", {"card_id": "research:unverified", "query": "Charizard",
                    "platforms": ["mercari"], "product_urls": [MERCARI]})["offers"][0]
                selected = loop.select("owner", {"card_id": "research:unverified", "offer_id": offer["offer_id"],
                    "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"],
                    "currency": offer["currency"]})
                fetch.pages[MERCARI] = product_html(price="100") + cue
                with self.assertRaises(CommerceError) as raised:
                    loop.handoff("owner", {"selection_id": selected["selection_id"], "forwarder": "buyship",
                        "destination": {"country": "HK"}})
                self.assertEqual(raised.exception.code, "offer_changed")
                self.assertEqual(provider.calls, 0)
                # Starting research on an already contradictory page is safe,
                # too: sold-out cannot be selected; unknown money is manual only.
                offer = loop.research("owner", {"card_id": "research:unverified", "query": "Charizard",
                    "platforms": ["mercari"], "product_urls": [MERCARI]})["offers"][0]
                choose = {"card_id": "research:unverified", "offer_id": offer["offer_id"],
                    "expected_observed_at": offer["observed_at"], "expected_price_minor": offer["price_minor"],
                    "currency": offer["currency"]}
                if offer["availability"] == "sold_out":
                    with self.assertRaises(CommerceError) as raised:
                        loop.select("owner", choose)
                    self.assertEqual(raised.exception.code, "offer_unavailable")
                else:
                    selected = loop.select("owner", choose)
                    result = loop.handoff("owner", {"selection_id": selected["selection_id"], "forwarder": "buyship",
                        "destination": {"country": "HK"}})
                    self.assertEqual(result["status"], "manual_handoff_required")
                    self.assertIsNone(result["quote"])
                self.assertEqual(provider.calls, 0)

    def test_variant_multiple_offers_and_identity_mismatch_fail_closed(self):
        fixtures = [product_html(hasVariant=[{"name": "Other edition"}]),
                    product_html(url="https://jp.mercari.com/item/m99999999999"),
                    product_html(offers=[{"@type": "Offer", "price": "100", "priceCurrency": "JPY"},
                                         {"@type": "Offer", "price": "101", "priceCurrency": "JPY"}]),
                    product_html(offers={"@type": "Offer", "url": "https://jp.mercari.com/item/m99999999999",
                                         "price": "100", "priceCurrency": "JPY"})]
        for html in fixtures:
            crawler, _ = self.crawler({MERCARI: html})
            row = crawler.detail(MERCARI)
            self.assertIsNone(row["price_minor"])
            self.assertEqual(row["status"], "unknown")

    def test_product_group_and_variant_og_money_stay_unresolved_summaries(self):
        metadata = ("<meta property='og:title' content='Pikachu raw or PSA 10'>"
                    "<meta property='product:price:amount' content='100'>"
                    "<meta property='product:price:currency' content='JPY'>")
        groups = [{"@type": "ProductGroup", "name": "Grade choices", "variesBy": "grade",
                   "hasVariant": [{"@type": "Product", "name": "PSA 10"}]},
                  {"@type": "ProductGroup", "name": "Grade choices", "variesBy": "grade"},
                  {"@type": "ProductGroup", "name": "Grade choices", "hasVariant": []},
                  {"@type": ["Product", "ProductGroup"], "name": "Grade choices"}]
        for group in groups:
            with self.subTest(group=group):
                html = metadata + "<script type='application/ld+json'>" + json.dumps(group) + "</script>"
                crawler, _ = self.crawler({MERCARI: html})
                row = crawler.detail(MERCARI)
                self.assertEqual((row["scope"], row["variant_status"]), ("product_summary", "unresolved"))
                self.assertIsNone(row["price_minor"])
                self.assertIsNone(row["currency"])
                self.assertEqual((row["status"], row["availability"]), ("unknown", "unknown"))
                self.assertIn("variant_unresolved", row["exclusion_reasons"])

    def test_obvious_visible_auction_controls_override_ordinary_instock_offer(self):
        cues = ["<span>Current bid</span><span>$10.00</span>", "<span>Auction ends</span><span>in 2 days</span>",
                "<span>Place a bid</span>", "<span>12 bids</span>", "<span>Starting bid: ¥1,000</span>",
                "<span>現在の入札価格: ¥1,000</span>"]
        for cue in cues:
            with self.subTest(cue=cue):
                crawler, _ = self.crawler({MERCARI: product_html() + cue})
                row = crawler.detail(MERCARI)
                self.assertIsNone(row["price_minor"])
                self.assertEqual((row["status"], row["availability"]), ("unknown", "unknown"))
                self.assertIn("auction_not_fixed_price", row["exclusion_reasons"])

    def test_unrelated_script_auction_label_does_not_override_public_fixed_ask(self):
        crawler, _ = self.crawler({MERCARI: product_html() + "<script>const labels={auction:'Auction ends',current:'Current bid'}</script>"})
        row = crawler.detail(MERCARI)
        self.assertEqual((row["price_minor"], row["status"]), (12700, "on_sale"))

    def test_ambiguous_psa_text_is_unverified_and_review_required(self):
        crawler, _ = self.crawler({MERCARI: product_html(title="Charizard PSA 10 PSA 9 slab")})
        row = crawler.detail(MERCARI)
        self.assertIsNone(row["grade_company"])
        self.assertTrue(row["quality_review_required"])
        self.assertFalse(row["certificate_verified"])

    def test_host_path_userinfo_encoding_and_private_addresses_rejected_before_fetch(self):
        urls = ["http://jp.mercari.com/item/m123", "https://127.0.0.1/item/m123", "https://[::1]/item/m123",
                "https://jp.mercari.com.evil.com/item/m123", "https://x@jp.mercari.com/item/m123",
                "https://jp.mercari.com:444/item/m123", "https://jp.mercari.com/api/items/m123",
                "https://jp.mercari.com/item/%6d123", "https://jp.mercari.com/item/m123?token=secret",
                "https://snkrdunk.com/api/private", "https://jp.mercari.com/item/m123#x"]
        crawler, fetch = self.crawler()
        for url in urls:
            with self.subTest(url=url), self.assertRaises(CrawlBlocked):
                crawler.detail(url)
        self.assertEqual(fetch.calls, [])

    def test_private_redirect_is_validated_before_second_request(self):
        crawler, fetch = self.crawler({MERCARI: {"status": 302, "body": "", "headers": {"Location": "https://127.0.0.1/admin"}}})
        with self.assertRaisesRegex(CrawlBlocked, "marketplace_host_not_allowed"):
            crawler.detail(MERCARI)
        self.assertEqual(fetch.calls, ["https://jp.mercari.com/robots.txt", MERCARI])

    def test_injected_transport_cannot_hide_redirect(self):
        crawler, _ = self.crawler({MERCARI: {"status": 200, "body": product_html(), "url": "https://127.0.0.1/"}})
        with self.assertRaises(CrawlBlocked):
            crawler.detail(MERCARI)

    def test_robots_disallow_unavailable_and_pacing_fail_closed(self):
        for text in ("User-agent: *\nDisallow: /item/\n", "User-agent: *\nCrawl-delay: 2\n"):
            fetch = FixtureFetch({MERCARI: product_html()}, robots=text)
            with self.assertRaisesRegex(CrawlBlocked, "robots_"):
                Crawler(fetch).detail(MERCARI)
            self.assertEqual(len(fetch.calls), 1)
        def unavailable(url):
            return {"status": 404, "body": ""}
        with self.assertRaisesRegex(CrawlBlocked, "robots_unavailable"):
            Crawler(unavailable).detail(MERCARI)

    def test_challenge_login_bytes_content_type_and_page_bounds(self):
        for response in ("<html>Verify you are human CAPTCHA</html>", "<input type='password'>",
                         {"status": 200, "body": "x" * 1100},
                         {"status": 200, "body": "{}", "headers": {"content-type": "application/json"}}):
            crawler, _ = self.crawler({MERCARI: response}, max_bytes=1024)
            with self.assertRaises(CrawlBlocked):
                crawler.detail(MERCARI)
        search = "https://jp.mercari.com/search?keyword=Card"
        crawler, fetch = self.crawler({search: f"<a href='{MERCARI}'>Card</a>", MERCARI: product_html()}, max_pages=2)
        result = crawler.search("mercari", "Card")
        self.assertEqual((result["status"], len(result["listings"])), ("partial", 0))
        self.assertEqual(len(fetch.calls), 2)

    def test_canonical_url_export_returns_stable_used_listing_identity(self):
        self.assertEqual(canonical_product_url(SNKR_USED), ("snkrdunk", "30335981", SNKR_USED))
        self.assertEqual(canonical_product_url(MERCARI + "/"), ("mercari", "m97669071757", MERCARI))


if __name__ == "__main__":
    unittest.main()

"""Offline-only validation for explicitly selected public eBay browse seeds."""
import socket
import unittest
from unittest.mock import patch

from pokemon_index.ebay_discovery import browse_urls, listing_anchor


class EbayPublicBrowseConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.connect = patch.object(socket.socket, "connect", side_effect=AssertionError("offline only"))
        self.connect.start()

    def tearDown(self):
        self.connect.stop()

    def test_exact_configured_category_only_and_deduplicated(self):
        url = "https://www.ebay.com/b/Pokemon-TCG-Cards/183454/bn_12345"
        self.assertEqual(browse_urls([url + "/", url]), (url,))
        self.assertEqual(browse_urls(), ())

    def test_search_and_product_or_seller_endpoints_are_not_browse_seeds(self):
        for path in ("/sch/i.html?_nkw=Pikachu", "/itm/123456789012", "/usr/test", "/str/test", "/bhp/pikachu"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "browse URL"):
                browse_urls(["https://www.ebay.com" + path])

    def test_config_cannot_add_network_origins_or_ambiguous_paths(self):
        valid = "https://www.ebay.com/b/Pokemon/183454/bn_12345"
        urls = [valid + "?q=Pikachu", valid + "#more", valid.replace("https:", "http:"),
                valid.replace("www.ebay.com", "www.ebay.com.evil.invalid"),
                valid.replace("www.ebay.com", "127.0.0.1"),
                valid.replace("www.ebay.com", "token@www.ebay.com"),
                valid.replace("www.ebay.com", "www.ebay.com:8443"),
                valid.replace("/Pokemon/", "/%50okemon/"),
                valid.replace("/Pokemon/", "/../Pokemon/"),
                valid.replace("/Pokemon/", "//Pokemon/"), valid + "\n"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                browse_urls([url])

    def test_bounded_explicit_array_required(self):
        url = "https://www.ebay.com/b/Pokemon/183454/bn_12345"
        for values in (url, {url}, [url] * 6, [None], [False]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                browse_urls(values)

    def test_only_known_item_tracking_can_be_removed_without_losing_variation(self):
        url = "https://www.ebay.com/itm/123456789012"
        self.assertEqual(listing_anchor(url + "?itmmeta=abc&hash=item123&itmprp=enc%3A123&_skw=Pikachu&_trksid=x"), url)
        for query in ("var=123", "quantity=2", "unknown=x", "itmmeta=x&var=123", "_nkw=Pikachu"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                listing_anchor(url + "?" + query)
        for value in (url.replace("www.ebay.com", "127.0.0.1"), url + "#more", url + "/%2fsecret",
                      url.replace("www.ebay.com", "user@www.ebay.com")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                listing_anchor(value)


if __name__ == "__main__":
    unittest.main()

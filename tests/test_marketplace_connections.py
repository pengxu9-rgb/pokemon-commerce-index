"""Official partner status must not be inferred from a public research result."""
import unittest
from types import SimpleNamespace

from pokemon_index.commerce_loop import CommerceLoop, FixtureCrawler
from pokemon_index.marketplace_connections import marketplace_connections


class MarketplaceConnectionTests(unittest.TestCase):
    def test_default_research_does_not_claim_official_or_fanatics_access(self):
        result = CommerceLoop(FixtureCrawler()).research("owner", {
            "card_id": "ja:SV2A:173/165:standard", "query": "Pikachu"})
        self.assertTrue(result["offers"])
        self.assertEqual([(v["source"], v["status"]) for v in result["marketplace_connections"]],
            [("ebay_us", "not_configured"), ("fanatics_collect", "not_configured")])
        self.assertNotIn("fanatics_collect", [v["source"] for v in result["offers"]])
        self.assertFalse(result["order_created"])
        self.assertIsNone(result["purchase_action"])

    def test_only_explicit_server_capabilities_can_enable_official_status(self):
        for configured, enabled, expected in (
            (False, True, "not_configured"), ("yes", True, "not_configured"),
            (True, False, "configured_offline"), (True, "yes", "configured_offline"),
            (True, True, "enabled"),
        ):
            with self.subTest(configured=configured, enabled=enabled):
                value = marketplace_connections(SimpleNamespace(
                    official_ebay_configured=configured, official_ebay_enabled=enabled))
                self.assertEqual(value[0]["status"], expected)
                self.assertEqual(value[1]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()

"""Official Browse cannot inherit a crawler or fixture's permission to run."""
from datetime import datetime, timedelta, timezone
import contextlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pokemon_index import commerce_service


class EbayServiceConfigurationTests(unittest.TestCase):
    def run_main(self, flags, env=None):
        output = io.StringIO()
        server = SimpleNamespace(server_port=8766, serve_forever=lambda: None)
        manager = contextlib.nullcontext(server)
        with patch.dict(os.environ, {"POKEMON_COMMERCE_TOKEN": "offline-service-token-at-least-24"} | (env or {}), clear=True), \
                patch("sys.argv", ["commerce_service", *flags]), \
                patch.object(commerce_service, "create_server", return_value=manager), \
                contextlib.redirect_stderr(output), contextlib.redirect_stdout(output):
            commerce_service.main()
        return output.getvalue()

    def test_existing_live_crawl_flag_does_not_enable_official_api(self):
        with patch("pokemon_index.ebay_official.configure_official_ebay") as factory:
            with self.assertRaises(SystemExit):
                self.run_main(["--allow-live-crawl"])
        factory.assert_not_called()

    def test_session_bounds_without_explicit_opt_in_fail_closed(self):
        for flags in (["--ebay-read-until", "2026-10-26T12:00:00Z"], ["--ebay-request-budget", "3"]):
            with self.subTest(flags=flags), self.assertRaises(SystemExit):
                self.run_main(flags)

    def test_explicit_api_activation_cannot_mix_fixture_or_missing_configuration(self):
        for flags in (["--fixture", "--allow-live-ebay-browse"],
                      ["--allow-live-ebay-browse"]):
            # Missing credentials/window also fails, without requesting a token.
            with self.subTest(flags=flags), self.assertRaises(SystemExit):
                self.run_main(flags)

    def test_explicit_gate_passes_server_config_without_exposing_it(self):
        from pokemon_index.ebay_official import configure_official_ebay
        env = {"EBAY_CLIENT_ID": "offline-private-id", "EBAY_CLIENT_SECRET": "offline-private-secret",
               "EBAY_PRODUCTION_APPROVED": "true", "EBAY_DISPLAY_APPROVED": "true"}
        deadline = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        with patch("pokemon_index.ebay_official.configure_official_ebay", wraps=configure_official_ebay) as factory:
            output = self.run_main(["--approved-source-routing", "--source", "ebay_us", "--source-route", "ebay_us=api_only",
                "--source-access-approval", "ebay_us=synthetic-source-approval", "--source-request-budget", "3",
                "--source-window-seconds", "60", "--allow-live-ebay-browse", "--ebay-read-until", deadline,
                "--ebay-request-budget", "3"], env)
        self.assertEqual(factory.call_count, 1)
        self.assertTrue(factory.call_args.kwargs["allow_network"])
        self.assertEqual(factory.call_args.kwargs["request_budget"], 3)
        self.assertEqual(factory.call_args.kwargs["read_until"], deadline)
        self.assertNotIn("offline-private", output)


if __name__ == "__main__":
    unittest.main()

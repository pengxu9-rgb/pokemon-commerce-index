import json
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pokemon_index.marketplace_browser import BrowserHTMLFetch
from pokemon_index.marketplace_crawl import CrawlBlocked


URL = 'https://jp.mercari.com/search?keyword=PSA10'


def diagnostics(**changes):
    return {"schema": "pokemon.public-browser-diagnostics.v1", "stage": "navigation",
            "elapsed_ms": 1500, "requests": 4, "allowed_requests": 3, "blocked_requests": 1,
            "failed_requests": 1, "responses": 2, "pinned_hosts": 6, "listing_links": 0,
            "search_status": None, "search_api_status": None, "blocked_api_requests": 1} | changes


class BrowserTransportTests(unittest.TestCase):
    def test_disabled_or_unsupported_url_never_starts_browser(self):
        def denied(*args, **kwargs):
            self.fail('browser must not start')
        with self.assertRaises(CrawlBlocked):
            BrowserHTMLFetch(runner=denied)(URL)
        for url in ('http://127.0.0.1/search?keyword=x',
                    'https://jp.mercari.com/purchase/1',
                    'https://www.ebay.com/sch/i.html?_nkw=PSA10'):
            with self.subTest(url=url), self.assertRaises(CrawlBlocked):
                BrowserHTMLFetch(enabled=True, runner=denied)(url)

    def test_valid_response_is_bounded_and_uses_argument_array(self):
        calls = []
        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 200, 'url': URL, 'body': '<html>public</html>'}))
        result = BrowserHTMLFetch(enabled=True, runner=runner)(URL)
        self.assertEqual(result['status'], 200)
        self.assertEqual(calls[0][0][-2], URL)
        self.assertNotIn('shell', calls[0][1])

    def test_browser_subprocess_never_inherits_provider_or_sidecar_credentials(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(returncode=0, stdout=json.dumps({'status': 200, 'url': URL, 'body': '<html>public</html>'}))
        with patch.dict('os.environ', {'PSA_API_TOKEN': 'private-psa', 'BNS_PARTNER_CLIENT_SECRET': 'private-bns',
                                      'POKEMON_COMMERCE_TOKEN': 'private-sidecar', 'NODE_PATH': '/opt/browser/node_modules',
                                      'POKEMON_PUBLIC_BROWSER_BUNDLED': '1'}):
            BrowserHTMLFetch(enabled=True, runner=runner)(URL)
        self.assertEqual(calls[0]['env']['POKEMON_PUBLIC_BROWSER_BUNDLED'], '1')
        self.assertEqual(calls[0]['env']['NODE_PATH'], '/opt/browser/node_modules')
        for key in ('PSA_API_TOKEN', 'BNS_PARTNER_CLIENT_SECRET', 'POKEMON_COMMERCE_TOKEN'):
            self.assertNotIn(key, calls[0]['env'])

    def test_failures_redirects_bad_json_and_timeout_fail_closed(self):
        cases = [SimpleNamespace(returncode=1, stdout=''),
                 SimpleNamespace(returncode=0, stdout='not json'),
                 SimpleNamespace(returncode=0, stdout=json.dumps({'status': 200, 'url': 'https://evil.invalid', 'body': ''})),
                 SimpleNamespace(returncode=0, stdout=json.dumps({'status': 200, 'url': URL, 'body': 'x' * 1025}))]
        for response in cases:
            with self.subTest(response=response), self.assertRaises(CrawlBlocked):
                BrowserHTMLFetch(enabled=True, max_bytes=1024, runner=lambda *a, **k: response)(URL)
        def timeout(*a, **k):
            raise subprocess.TimeoutExpired('node', 2)
        with self.assertRaisesRegex(CrawlBlocked, '^browser_renderer_timeout$'):
            BrowserHTMLFetch(enabled=True, runner=timeout)(URL)

    def test_known_child_failure_preserves_exact_category_and_safe_diagnostics(self):
        for code in ("browser_renderer_dns_unavailable", "browser_renderer_navigation_timeout",
                     "browser_renderer_request_budget_exhausted", "browser_renderer_deadline_exhausted",
                     "browser_renderer_challenge", "browser_renderer_no_listing_links"):
            response = {"error": {"code": code}, "diagnostics": diagnostics()}
            result = SimpleNamespace(returncode=1, stdout=json.dumps(response), stderr='private-token')
            with self.subTest(code=code), self.assertRaises(CrawlBlocked) as raised:
                BrowserHTMLFetch(enabled=True, runner=lambda *a, **k: result)(URL)
            self.assertEqual(str(raised.exception), code)
            self.assertEqual(raised.exception.diagnostics, response["diagnostics"])
            self.assertNotIn('private-token', str(raised.exception))

    def test_diagnostic_vocabulary_and_error_dto_cannot_smuggle_raw_messages(self):
        cases = [
            {"error": {"code": "private-token"}},
            {"error": {"code": "browser_renderer_failed", "message": "private-token"}},
            {"error": {"code": "browser_renderer_failed"}, "raw": "private-token"},
            {"error": {"code": "browser_renderer_failed"}, "diagnostics": diagnostics(stage="private-token")},
            {"error": {"code": "browser_renderer_failed"}, "diagnostics": diagnostics(headers="private-token")},
            {"error": {"code": "browser_renderer_failed"}, "diagnostics": diagnostics(search_api_status=True)},
            {"error": {"code": "browser_renderer_failed"}, "diagnostics": diagnostics(allowed_requests=65)},
        ]
        for response in cases:
            result = SimpleNamespace(returncode=1, stdout=json.dumps(response))
            with self.subTest(response=response), self.assertRaisesRegex(CrawlBlocked, '^browser_renderer_invalid_response$') as raised:
                BrowserHTMLFetch(enabled=True, runner=lambda *a, **k: result)(URL)
            self.assertNotIn('private-token', str(raised.exception))

    def test_successful_diagnostic_dto_is_validated_and_ordinary_failure_is_not_unavailable(self):
        response = {"status": 200, "url": URL, "body": '<html>public</html>',
                    "diagnostics": diagnostics(stage="complete", listing_links=1)}
        result = SimpleNamespace(returncode=0, stdout=json.dumps(response))
        value = BrowserHTMLFetch(enabled=True, runner=lambda *a, **k: result)(URL)
        self.assertEqual(value["diagnostics"]["stage"], "complete")
        result.returncode = 1
        with self.assertRaisesRegex(CrawlBlocked, '^browser_renderer_failed$'):
            BrowserHTMLFetch(enabled=True, runner=lambda *a, **k: result)(URL)

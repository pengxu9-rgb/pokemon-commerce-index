import json
import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pokemon_index.marketplace_browser import BrowserHTMLFetch
from pokemon_index.marketplace_crawl import CrawlBlocked


URL = 'https://jp.mercari.com/search?keyword=PSA10'


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
        with self.assertRaises(CrawlBlocked):
            BrowserHTMLFetch(enabled=True, runner=timeout)(URL)

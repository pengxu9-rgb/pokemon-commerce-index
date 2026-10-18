"""Synthetic Node replay must reach its local server with environment proxies on."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from scripts import rehearse_collector_recommendations as runner


class SyntheticNodeEnvironmentTests(unittest.TestCase):
    def test_preserves_both_bypass_spellings_and_parent_route(self):
        parent = {
            'NO_PROXY': 'original.invalid, .kept.invalid',
            'no_proxy': 'lowercase.invalid',
            'HTTP_PROXY': 'http://127.0.0.1:7897',
            'HTTPS_PROXY': 'http://127.0.0.1:7897',
            'NODE_USE_ENV_PROXY': '1',
            'UNRELATED': 'unchanged',
        }
        with patch.dict(os.environ, parent, clear=True):
            child = runner._synthetic_node_env()
            self.assertEqual(dict(os.environ), parent)
        self.assertEqual(child, dict(parent,
            NO_PROXY=parent['NO_PROXY'] + ',127.0.0.1',
            no_proxy=parent['no_proxy'] + ',127.0.0.1'))

    def test_unset_and_empty_bypass_only_add_fixed_ipv4_loopback(self):
        for parent in [{}, {'NO_PROXY': '', 'no_proxy': ''}]:
            with self.subTest(parent=parent), patch.dict(os.environ, parent, clear=True):
                child = runner._synthetic_node_env()
                self.assertEqual(child['NO_PROXY'], '127.0.0.1')
                self.assertEqual(child.get('no_proxy'),
                                 '127.0.0.1' if 'no_proxy' in parent else None)
                self.assertEqual(dict(os.environ), parent)

    def test_existing_loopback_entries_are_preserved_without_duplicates(self):
        parent = {'NO_PROXY': 'kept.invalid, 127.0.0.1 ',
                  'no_proxy': '127.0.0.1,lowercase.invalid'}
        with patch.dict(os.environ, parent, clear=True):
            self.assertEqual(runner._synthetic_node_env(), parent)


class SyntheticNodeProxyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if not cls.node:
            raise unittest.SkipTest('Node is required for real local HTTP replay')
        version = subprocess.check_output([cls.node, '--version'], text=True, timeout=5)
        if tuple(map(int, version.strip().lstrip('v').split('.'))) < (24, 5, 0):
            raise unittest.SkipTest('Node 24.5+ is required for NODE_USE_ENV_PROXY')

    @staticmethod
    def proxy_environment(proxy):
        env = os.environ.copy()
        url = 'http://127.0.0.1:' + str(proxy.getsockname()[1])
        for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            env[key] = url
        env.update(NODE_USE_ENV_PROXY='1', NO_PROXY='preserved.invalid',
                   no_proxy='lowercase.invalid')
        return env

    def test_actual_node_proxy_negative_control_and_child_bypass(self):
        class Handler(BaseHTTPRequestHandler):
            requests = 0

            def do_GET(self):
                type(self).requests += 1
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'local-only')

            def log_message(self, *args):
                pass

        script = """
fetch(process.argv[1], {signal: AbortSignal.timeout(1500)})
  .then(async r => console.log(JSON.stringify({status:r.status, body:await r.text()})))
  .catch(e => console.log(JSON.stringify({error:e.cause?.code || e.name})))
  .finally(() => process.exit(0));
"""
        with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server, socket.socket() as proxy:
            # Reserve a loopback endpoint without listening: no external proxy is contacted.
            proxy.bind(('127.0.0.1', 0))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                parent = self.proxy_environment(proxy)
                url = 'http://127.0.0.1:' + str(server.server_port)
                blocked = json.loads(subprocess.check_output(
                    [self.node, '-e', script, url], env=parent, text=True, timeout=5))
                self.assertIn('error', blocked)
                self.assertEqual(Handler.requests, 0)
                with patch.dict(os.environ, parent, clear=True):
                    child = runner._synthetic_node_env()
                    self.assertEqual(dict(os.environ), parent)
                direct = json.loads(subprocess.check_output(
                    [self.node, '-e', script, url], env=child, text=True, timeout=5))
                self.assertEqual(direct, {'status': 200, 'body': 'local-only'})
                self.assertEqual(Handler.requests, 1)
            finally:
                server.shutdown()
                worker.join(timeout=5)

    def test_all_42_prefixes_and_read_only_guards_with_unreachable_proxy(self):
        with socket.socket() as proxy, tempfile.TemporaryDirectory() as temp:
            proxy.bind(('127.0.0.1', 0))
            parent = self.proxy_environment(proxy)
            output = Path(temp) / 'rehearsal.json'
            with patch.dict(os.environ, parent, clear=True), contextlib.redirect_stdout(io.StringIO()):
                runner.run(runner.SUITE, output)
                self.assertEqual(dict(os.environ), parent)
            report = json.loads(output.read_text())
        self.assertEqual((report['journeys'], report['prefix_requests'],
                          report['passed'], report['failed']), (13, 42, 42, 0))
        self.assertTrue(report['catalog_bytes_unchanged'])
        self.assertTrue(all(row['passed'] for row in report['results']))
        for row in report['results']:
            if 'error' in row['expect']:
                self.assertEqual(row['error_code'], row['expect']['error'])
            else:
                result = row['call']['result']
                self.assertFalse(result['prices'])
                self.assertFalse(result['live_offers'])
                self.assertFalse(result['purchase_ready'])
                self.assertFalse(result['public_display_allowed'])


if __name__ == '__main__':
    unittest.main()

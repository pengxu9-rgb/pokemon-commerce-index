"""Loopback-only commerce research sidecar; run separately from the frozen catalog.

The Node proxy owns browser sessions and sends a startup-configured bearer token
and trusted X-Commerce-Owner header. Neither field belongs in a browser payload.
"""
from __future__ import annotations

import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
import socket

from .commerce_loop import CommerceError, CommerceLoop, FixtureCrawler, SCHEMA


def _json(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate JSON field")
            value[key] = item
        return value
    def finite(value):
        raise ValueError("nonfinite JSON value")
    # Bound nesting before json.loads, including malformed input.
    depth, quoted, escaped = 0, False, False
    for char in raw.decode("utf-8"):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 16:
                raise ValueError("JSON nesting exceeds limit")
        elif char in "]}":
            depth -= 1
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=finite)
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def create_server(loop, *, token, host="127.0.0.1", port=8766):
    """Create a private loopback server. No listener is opened by importing it."""
    if host != "localhost":
        try:
            valid = ipaddress.ip_address(host).is_loopback
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("commerce service binds to loopback only")
    if not isinstance(token, str) or not 24 <= len(token) <= 1024 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError("a server-owned bearer token of at least 24 characters is required")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_args):
            pass

        def _send(self, status, body):
            raw = json.dumps(body, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            self.close_connection = True

        def _owner(self):
            auth = self.headers.get_all("Authorization") or []
            owners = self.headers.get_all("X-Commerce-Owner") or []
            if (len(auth) != 1 or not auth[0].isascii() or not hmac.compare_digest(auth[0], "Bearer " + token)
                    or len(owners) != 1 or not owners[0].strip() or len(owners[0]) > 128
                    or any(ord(char) < 33 or ord(char) > 126 for char in owners[0])):
                raise CommerceError("commerce_access_denied", "Commerce access denied.", 401)
            # This endpoint is for a server proxy, never a credentialed browser.
            if self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"):
                raise CommerceError("commerce_proxy_required", "Use the authenticated application proxy.", 403)
            return owners[0]

        def do_POST(self):
            try:
                owner = self._owner()
                routes = {"/commerce/research": loop.research,
                          "/commerce/select": loop.select, "/commerce/handoff": loop.handoff,
                          "/commerce/psa": loop.psa}
                if self.path not in routes:
                    raise CommerceError("not_found", "Unknown commerce route.", 404)
                lengths = self.headers.get_all("Content-Length") or []
                if (len(lengths) != 1 or not lengths[0].isdecimal() or not 1 <= int(lengths[0]) <= 65536
                        or self.headers.get("Transfer-Encoding")
                        or self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json"):
                    raise CommerceError("invalid_request", "A bounded application/json body is required.")
                length = int(lengths[0])
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise CommerceError("invalid_request", "Incomplete request body.")
                try:
                    payload = _json(raw)
                except (ValueError, UnicodeError, RecursionError) as exc:
                    raise CommerceError("invalid_request", "A bounded unambiguous JSON object is required.") from exc
                self._send(200, routes[self.path](owner, payload))
            except CommerceError as exc:
                self._send(exc.status, {"schema": SCHEMA, "error": exc.code, "message": exc.message})
            except (TimeoutError, ConnectionError):
                self._send(408, {"schema": SCHEMA, "error": "request_timeout", "message": "The request timed out."})
            except Exception:
                self._send(500, {"schema": SCHEMA, "error": "commerce_unavailable", "message": "Commerce research is temporarily unavailable."})

        def do_GET(self):
            try:
                self._owner()
                if self.path != "/commerce/health":
                    raise CommerceError("not_found", "Unknown commerce route.", 404)
                self._send(200, {"schema": SCHEMA, "ok": True, "mode": loop.mode})
            except CommerceError as exc:
                self._send(exc.status, {"schema": SCHEMA, "error": exc.code, "message": exc.message})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 16
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    return Server((host, port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--fixture", action="store_true", help="synthetic .invalid examples; no network or database")
    parser.add_argument("--allow-live-crawl", action="store_true", help="opt in to bounded public-page research")
    parser.add_argument("--browser-renderer", action="store_true", help="allow the configured public-page browser renderer after normal HTML discovery")
    parser.add_argument("--source", action="append", choices=["mercari", "ebay_us", "snkrdunk"], help="explicitly authorized research sources")
    parser.add_argument("--snkr-seed-url", action="append", default=[])
    parser.add_argument("--snkr-sitemap-url", action="append", default=[])
    parser.add_argument("--quote-db", help="existing approved operator DB, never the packaged catalog")
    parser.add_argument("--allow-live-buyship", action="store_true", help="enable configured BNS resolve/quote only; no order")
    parser.add_argument("--allow-live-psa", action="store_true", help="enable configured read-only PSA certificate lookup")
    args = parser.parse_args()
    fixture = args.fixture or os.environ.get("POKEMON_COMMERCE_FIXTURE") == "true"
    browser_renderer = args.browser_renderer or os.environ.get("POKEMON_COMMERCE_BROWSER_RENDERER") == "1"
    if fixture and (args.allow_live_crawl or args.allow_live_buyship or args.allow_live_psa or args.quote_db or browser_renderer):
        parser.error("fixture mode cannot mix with live research or a quote database")
    if browser_renderer and not args.allow_live_crawl:
        parser.error("the public-page browser renderer requires --allow-live-crawl")
    token = os.environ.get("POKEMON_COMMERCE_TOKEN") or os.environ.get("POKEMON_COMMERCE_SERVICE_TOKEN")
    if not token:
        parser.error("set the server-only POKEMON_COMMERCE_TOKEN environment variable")
    forwarders = {}
    if fixture:
        crawler = FixtureCrawler()
    else:
        from .marketplace_crawl import Crawler
        renderer = None
        if browser_renderer:
            from .marketplace_browser import BrowserHTMLFetch
            renderer = BrowserHTMLFetch(enabled=True)
            if os.environ.get("POKEMON_COMMERCE_BROWSER_PROBE") == "1":
                print(json.dumps({"event": "commerce_browser_runtime", **renderer.probe()}), flush=True)
        crawler = Crawler(allow_network=args.allow_live_crawl,
            renderer=renderer,
            authorized_sources=args.source or ("mercari", "snkrdunk"),
            snkr_seed_urls=args.snkr_seed_url, snkr_sitemap_urls=args.snkr_sitemap_url)
    if args.allow_live_buyship:
        if not args.quote_db:
            parser.error("live BNS preview requires --quote-db with approved existing indexed evidence")
        from .bounded_buyship import BoundedBuyShipForwarder
        values = [os.environ.get(key) for key in ("BNS_PARTNER_BASE_URL", "BNS_PARTNER_CLIENT_ID", "BNS_PARTNER_CLIENT_SECRET")]
        if not all(values):
            parser.error("configure server-owned BNS_PARTNER_BASE_URL, BNS_PARTNER_CLIENT_ID and BNS_PARTNER_CLIENT_SECRET")
        forwarders["buyship"] = BoundedBuyShipForwarder(args.quote_db, *values, live_authorized=True)
    elif args.quote_db:
        parser.error("--quote-db is only used with --allow-live-buyship")
    from .psa_cert import PSACertClient
    psa_client = PSACertClient(token=os.environ.get("PSA_API_TOKEN"), allow_live=args.allow_live_psa)
    loop = CommerceLoop(crawler, forwarders=forwarders, psa_client=psa_client)
    with create_server(loop, token=token, host=args.host, port=args.port) as server:
        print(json.dumps({"event": "commerce_sidecar_ready", "mode": loop.mode, "port": server.server_port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

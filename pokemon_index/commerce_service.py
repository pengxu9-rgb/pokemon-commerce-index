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


def create_server(loop, *, token, host="127.0.0.1", port=8766, research_only=False):
    """Create a private loopback server. No listener is opened by importing it."""
    if type(research_only) is not bool:
        raise ValueError("research-only mode requires an explicit boolean")
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
                if research_only and self.path not in {"/commerce/research", "/commerce/read-certificate"}:
                    raise CommerceError("read_only_scope", "Only seller research is enabled.", 403)
                routes = {"/commerce/research": loop.research,
                          "/commerce/read-certificate": loop.read_certificate,
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
                result = routes[self.path](owner, payload)
                if research_only:
                    result = {**result, "forwarders": []}
                self._send(200, result)
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
                from .source_readiness import source_readiness
                self._send(200, {"schema": SCHEMA, "ok": True, "mode": loop.mode,
                                 "source_readiness": source_readiness(loop.crawler)})
            except CommerceError as exc:
                self._send(exc.status, {"schema": SCHEMA, "error": exc.code, "message": exc.message})

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        request_queue_size = 16
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    return Server((host, port), Handler)


def _crawl_bounds(args):
    timeout = getattr(args, 'crawl_timeout_seconds', 8)
    maximum = getattr(args, 'crawl_max_seconds', 30)
    if (type(timeout) not in (int, float) or not 1 <= timeout <= 8
            or type(maximum) not in (int, float) or not 1 <= maximum <= 30):
        raise ValueError('invalid bounded crawler timing configuration')
    # These are socket-operation and between-request bounds. DNS and in-flight
    # operations are not preemptible; do not advertise an absolute query SLA.
    return {'timeout': timeout, 'max_seconds': maximum}


def _approved_sources(args, env):
    """Explicitly compose bounded adapters; None preserves the legacy service path."""
    if not args.approved_source_routing:
        if getattr(args, 'allow_live_crawl', False) or getattr(args, 'allow_live_ebay_browse', False):
            raise ValueError('live marketplace access requires approved routing')
        if (args.source_route or args.source_listing_url or args.source_request_budget is not None or args.source_window_seconds is not None
                or any(getattr(args, key, []) for key in ("source_access_approval", "source_photo_display", "source_partner_handoff"))):
            raise ValueError('routing bounds require explicit routing opt-in')
        return None
    if (args.fixture or args.browser_renderer or env.get('POKEMON_COMMERCE_FIXTURE') == 'true'
            or env.get('POKEMON_COMMERCE_BROWSER_RENDERER') == '1'):
        raise ValueError('approved routing cannot mix with fixture or browser renderer')
    if not args.source_route or not args.source or args.source_request_budget is None or args.source_window_seconds is None:
        raise ValueError('routing requires sources, routes and finite shared bounds')
    import re
    def approvals(name):
        result = {}
        for value in getattr(args, name, []):
            source, sep, reference = value.partition('=')
            if not sep or source not in args.source or source in result or not re.fullmatch(r'[A-Za-z0-9._:-]{3,128}', reference):
                raise ValueError('invalid separate source use approval')
            result[source] = reference
        return result
    access = approvals('source_access_approval')
    photos = approvals('source_photo_display')
    handoff = approvals('source_partner_handoff')
    if set(access) != set(args.source):
        raise ValueError('each source needs an explicit source access approval')
    policies = {}
    for spec in args.source_route:
        parts = spec.split('=')
        if len(parts) != 2 or parts[0] not in args.source or parts[0] in policies or parts[1] not in {'api_only', 'crawl_only', 'api_preferred'}:
            raise ValueError('invalid source route')
        source, mode = parts
        if mode in {'api_only', 'api_preferred'} and source == 'ebay_us' and not args.allow_live_ebay_browse:
            raise ValueError('eBay API route requires its existing opt-in')
        if mode == 'api_only' and source != 'ebay_us':
            raise ValueError('unsupported API source')
        if (mode == 'crawl_only' or (mode == 'api_preferred' and source != 'ebay_us')) and not args.allow_live_crawl:
            raise ValueError('crawl route requires its existing opt-in')
        policies[source] = {'mode': mode, 'api_approved': bool(args.allow_live_ebay_browse and source == 'ebay_us'),
                            'crawl_approved': bool(args.allow_live_crawl), 'access_approval': access[source],
                            'photo_display_approved': source in photos, 'partner_handoff_allowed': source in handoff}
    from .dispatch_budget import DispatchBudget
    from .marketplace_crawl import Crawler
    from .approved_sources import ApprovedSources
    budget = DispatchBudget(max_requests=args.source_request_budget, seconds=args.source_window_seconds)
    crawler = None
    if args.allow_live_crawl:
        crawler = Crawler(allow_network=True, authorized_sources=args.source,
            snkr_seed_urls=args.snkr_seed_url, snkr_sitemap_urls=args.snkr_sitemap_url,
            ebay_browse_urls=args.ebay_browse_url, dispatch_budget=budget, **_crawl_bounds(args))
    api = None
    if args.allow_live_ebay_browse:
        from .ebay_official import configure_official_ebay
        fallback = crawler or Crawler(authorized_sources=(), dispatch_budget=budget)
        api = configure_official_ebay(fallback, env, allow_network=True,
            read_until=args.ebay_read_until, request_budget=args.ebay_request_budget, dispatch_budget=budget).client
    if set(policies) != set(args.source):
        raise ValueError('each authorized source requires exactly one route')
    return ApprovedSources(policies=policies, crawler=crawler, ebay_client=api, budget=budget, enabled=True,
                           public_listing_urls=args.source_listing_url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--fixture", action="store_true", help="synthetic .invalid examples; no marketplace or provider calls")
    parser.add_argument("--catalog-db", help="existing operator-supplied read-only catalog for listing identity checks")
    parser.add_argument("--allow-live-crawl", action="store_true", help="opt in to bounded public-page research")
    parser.add_argument("--research-only", action="store_true", help="deny selection, handoff and certificate operations")
    parser.add_argument("--allow-live-ebay-browse", action="store_true", help="opt in to an approved bounded official eBay Browse session; separate from crawling")
    parser.add_argument("--ebay-read-until", help="absolute UTC end for an explicitly approved eBay Browse session")
    parser.add_argument("--ebay-request-budget", type=int, help="finite eBay HTTP request budget, including token requests")
    parser.add_argument("--approved-source-routing", action="store_true", help="explicitly opt in to bounded approved source routing")
    parser.add_argument("--source-route", action="append", default=[], help="explicit source=api_only, source=crawl_only or source=api_preferred")
    parser.add_argument("--source-listing-url", action="append", default=[], help="exact canonical URL allowlist for direct listing onboarding")
    parser.add_argument("--source-request-budget", type=int, help="shared finite HTTP request budget")
    parser.add_argument("--source-window-seconds", type=int, help="finite shared read window")
    parser.add_argument("--source-access-approval", action="append", default=[], help="source=operator-record-reference; records source-use authorization, grants nothing")
    parser.add_argument("--source-photo-display", action="append", default=[], help="source=separate-photo-display-approval; absent strips seller photo URLs")
    parser.add_argument("--source-partner-handoff", action="append", default=[], help="source=separate-BNS-handoff-approval; absent prevents provider calls")
    parser.add_argument("--browser-renderer", action="store_true", help="allow the configured public-page browser renderer after normal HTML discovery")
    parser.add_argument("--source", action="append", choices=["mercari", "ebay_us", "snkrdunk"], help="explicitly authorized research sources")
    parser.add_argument("--snkr-seed-url", action="append", default=[])
    parser.add_argument("--snkr-sitemap-url", action="append", default=[])
    parser.add_argument("--crawl-timeout-seconds", type=float, default=8)
    parser.add_argument("--crawl-max-seconds", type=float, default=30)
    parser.add_argument("--ebay-browse-url", action="append", default=[],
                        help="exact operator-selected public eBay category URL; current robots policy is always checked")
    parser.add_argument("--quote-db", help="existing approved operator DB, never the packaged catalog")
    parser.add_argument("--allow-live-buyship", action="store_true", help="enable configured BNS resolve/quote only; no order")
    parser.add_argument("--buyship-url-preview", action="store_true", help="explicit selected-URL preview instead of the indexed quote gate")
    parser.add_argument("--allow-live-psa", action="store_true", help="enable configured read-only PSA certificate lookup")
    parser.add_argument("--allow-certificate-ocr", action="store_true", help="read at most two retained listing photos; never calls PSA")
    args = parser.parse_args()
    if args.allow_certificate_ocr and (args.fixture or not args.approved_source_routing or not args.allow_live_crawl):
        parser.error('certificate OCR requires approved public research routing')
    if args.research_only and (args.fixture or args.allow_live_buyship or args.allow_live_psa
                              or args.quote_db or args.buyship_url_preview):
        parser.error("research-only mode cannot mix with fixtures or provider operations")
    fixture = args.fixture or os.environ.get("POKEMON_COMMERCE_FIXTURE") == "true"
    if not args.allow_live_ebay_browse and (args.ebay_read_until is not None or args.ebay_request_budget is not None):
        parser.error("eBay session bounds require --allow-live-ebay-browse")
    if args.allow_live_ebay_browse and fixture:
        parser.error("official eBay Browse cannot mix with fixture mode")
    browser_renderer = args.browser_renderer or os.environ.get("POKEMON_COMMERCE_BROWSER_RENDERER") == "1"
    if fixture and (args.allow_live_crawl or args.allow_live_buyship or args.allow_live_psa or args.quote_db or browser_renderer or args.buyship_url_preview):
        parser.error("fixture mode cannot mix with live research or a quote database")
    if browser_renderer and not args.allow_live_crawl:
        parser.error("the public-page browser renderer requires --allow-live-crawl")
    if args.buyship_url_preview and (not args.allow_live_buyship or args.quote_db is not None):
        parser.error("URL preview requires explicit live Buy&Ship intent and cannot use a quote database")
    token = os.environ.get("POKEMON_COMMERCE_TOKEN") or os.environ.get("POKEMON_COMMERCE_SERVICE_TOKEN")
    if not token:
        parser.error("set the server-only POKEMON_COMMERCE_TOKEN environment variable")
    catalog_lookup = None
    if args.catalog_db is not None:
        if not args.catalog_db:
            parser.error("catalog database path cannot be empty")
        from .listing_evidence import CatalogIdentityLookup
        catalog_lookup = CatalogIdentityLookup(args.catalog_db)
    forwarders = {}
    try:
        routed = _approved_sources(args, os.environ)
    except ValueError:
        parser.error("live marketplace access requires explicit approved routing, source permissions, adapters and finite bounds")
    if routed is not None:
        crawler = routed
    elif fixture:
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
            authorized_sources=args.source or (),
            snkr_seed_urls=args.snkr_seed_url, snkr_sitemap_urls=args.snkr_sitemap_url,
            ebay_browse_urls=args.ebay_browse_url, **_crawl_bounds(args))
    if args.allow_live_ebay_browse and routed is None:
        from .ebay_official import configure_official_ebay
        try:
            crawler = configure_official_ebay(crawler, os.environ, allow_network=True,
                read_until=args.ebay_read_until, request_budget=args.ebay_request_budget)
        except ValueError:
            parser.error("official eBay Browse requires approved server-owned credentials, display rights and finite session bounds")
    if args.allow_live_buyship:
        if not args.quote_db and not args.buyship_url_preview:
            parser.error("live BNS preview requires --quote-db with approved existing indexed evidence")
        from .bounded_buyship import BoundedBuyShipForwarder
        values = [os.environ.get(key) for key in ("BNS_PARTNER_BASE_URL", "BNS_PARTNER_CLIENT_ID", "BNS_PARTNER_CLIENT_SECRET")]
        if not all(values):
            parser.error("configure server-owned BNS_PARTNER_BASE_URL, BNS_PARTNER_CLIENT_ID and BNS_PARTNER_CLIENT_SECRET")
        if args.buyship_url_preview:
            from .bns_url_preview import URLBuyShipForwarder
            forwarders["buyship"] = URLBuyShipForwarder(*values, live_authorized=True)
        else:
            forwarders["buyship"] = BoundedBuyShipForwarder(args.quote_db, *values, live_authorized=True)
    elif args.quote_db:
        parser.error("--quote-db is only used with --allow-live-buyship")
    from .psa_cert import PSACertClient
    from .psa_gcs import configure as configure_shared_psa
    coordinator = configure_shared_psa(os.environ, enabled=args.allow_live_psa)
    psa_client = PSACertClient(token=os.environ.get("PSA_API_TOKEN"), allow_live=args.allow_live_psa, coordinator=coordinator)
    from .certificate_evidence import CertificateReader
    reader = CertificateReader(enabled=args.allow_certificate_ocr, budget=routed.budget if routed else None)
    loop = CommerceLoop(crawler, forwarders=forwarders, psa_client=psa_client, catalog_lookup=catalog_lookup, certificate_reader=reader)
    with create_server(loop, token=token, host=args.host, port=args.port, research_only=args.research_only) as server:
        print(json.dumps({"event": "commerce_sidecar_ready", "mode": loop.mode, "port": server.server_port}), flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

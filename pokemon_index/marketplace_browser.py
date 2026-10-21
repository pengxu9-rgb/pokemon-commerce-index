"""Optional browser-rendered public search transport; no account/session reuse."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from .marketplace_crawl import CrawlBlocked, _url


RENDERER_ERROR_CODES = frozenset({
    "browser_renderer_dns_unavailable", "browser_renderer_navigation_timeout",
    "browser_renderer_navigation_failed", "browser_renderer_source_unavailable",
    "browser_renderer_challenge", "browser_renderer_no_listing_links",
    "browser_renderer_request_budget_exhausted", "browser_renderer_deadline_exhausted",
    "browser_renderer_response_too_large", "browser_renderer_failed",
})
_DIAGNOSTIC_STAGES = {"validation", "dns", "launch", "navigation", "hydration", "inspection", "complete"}
_DIAGNOSTIC_COUNTS = {"requests", "allowed_requests", "blocked_requests", "failed_requests",
                      "responses", "pinned_hosts", "listing_links", "blocked_api_requests"}


def _diagnostics(value):
    """Validate the child's fixed, credential-free diagnostic vocabulary."""
    if value is None:
        return None
    fields = _DIAGNOSTIC_COUNTS | {"schema", "stage", "elapsed_ms", "search_status", "search_api_status"}
    if (not isinstance(value, dict) or set(value) != fields
            or value.get("schema") != "pokemon.public-browser-diagnostics.v1"
            or not isinstance(value.get("stage"), str) or value["stage"] not in _DIAGNOSTIC_STAGES
            or type(value.get("elapsed_ms")) is not int or not 0 <= value["elapsed_ms"] <= 22_000
            or any(type(value.get(key)) is not int or not 0 <= value[key] <= 129
                   for key in _DIAGNOSTIC_COUNTS)
            or value["allowed_requests"] > 64 or value["pinned_hosts"] > 6 or value["listing_links"] > 25
            or any(value.get(key) is not None and
                   (type(value[key]) is not int or not 100 <= value[key] <= 599)
                   for key in ("search_status", "search_api_status"))):
        raise CrawlBlocked("browser_renderer_invalid_response")
    return value


class BrowserHTMLFetch:
    """Render only allowlisted Mercari search pages in an isolated browser.

    Requires an operator-installed Playwright Node runtime. NODE_PATH may point
    to that runtime; no package is downloaded automatically. Robots and crawl
    budgets remain the caller's responsibility, before invoking this transport.
    """
    def __init__(self, *, enabled=False, timeout=22, max_bytes=750_000, runner=None):
        self.enabled = enabled
        self.timeout = min(22, max(2, float(timeout)))
        self.max_bytes = min(1_000_000, max(1024, int(max_bytes)))
        self.runner = runner or subprocess.run
        self.script = Path(__file__).resolve().parents[1] / "integrations/browser/renderPublicPage.cjs"

    def __call__(self, url):
        if not self.enabled:
            raise CrawlBlocked("browser_renderer_disabled")
        canonical, source = _url(url, purpose="search")
        if source != "mercari":
            raise CrawlBlocked("browser_source_not_enabled")
        try:
            # Marketplace page scripts do not need partner credentials, the
            # sidecar bearer token or cloud application configuration.
            result = self.runner(["node", str(self.script), canonical, str(self.max_bytes)],
                                 capture_output=True, text=True, timeout=self.timeout, check=False,
                                 env=self._environment())
        except subprocess.TimeoutExpired as exc:
            raise CrawlBlocked("browser_renderer_timeout") from exc
        except OSError as exc:
            raise CrawlBlocked("browser_renderer_unavailable") from exc
        if not isinstance(result.stdout, str) or len(result.stdout.encode()) > self.max_bytes * 3 + 4096:
            raise CrawlBlocked("browser_renderer_invalid_response")
        try:
            response = json.loads(result.stdout)
        except (TypeError, ValueError) as exc:
            raise CrawlBlocked("browser_renderer_invalid_response") from exc
        if not isinstance(response, dict):
            raise CrawlBlocked("browser_renderer_invalid_response")
        diagnostic = _diagnostics(response.get("diagnostics"))
        if "error" in response:
            error = response["error"]
            if (set(response) - {"error", "diagnostics"} or not isinstance(error, dict)
                    or set(error) != {"code"} or not isinstance(error.get("code"), str)
                    or error["code"] not in RENDERER_ERROR_CODES):
                raise CrawlBlocked("browser_renderer_invalid_response")
            blocked = CrawlBlocked(error["code"])
            blocked.diagnostics = diagnostic
            raise blocked
        if result.returncode != 0:
            raise CrawlBlocked("browser_renderer_failed")
        if (not isinstance(response, dict) or response.get("url") != canonical
                or type(response.get("status")) is not int or not isinstance(response.get("body"), str)
                or len(response["body"].encode()) > self.max_bytes):
            raise CrawlBlocked("browser_renderer_invalid_response")
        return response

    @staticmethod
    def _environment():
        return {key: os.environ[key] for key in
                ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "NODE_PATH", "PLAYWRIGHT_BROWSERS_PATH", "POKEMON_PUBLIC_BROWSER_BUNDLED")
                if key in os.environ}

    def probe(self):
        """Offline browser launch check, with no marketplace/provider requests."""
        try:
            result = self.runner(["node", str(self.script), "--probe"], capture_output=True,
                                 text=True, timeout=10, check=False, env=self._environment())
            value = json.loads(result.stdout) if result.returncode == 0 and len(result.stdout) < 1024 else {}
            if value.get("ok") is True and value.get("sandbox_enabled") is True:
                return {"ok": True, "sandbox_enabled": True, "version": str(value.get("version", ""))[:80]}
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        return {"ok": False, "sandbox_enabled": True, "reason": "browser_runtime_unavailable"}

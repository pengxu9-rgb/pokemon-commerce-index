"""Optional browser-rendered public search transport; no account/session reuse."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .marketplace_crawl import CrawlBlocked, _url


class BrowserHTMLFetch:
    """Render only allowlisted Mercari search pages in an isolated browser.

    Requires an operator-installed Playwright Node runtime. NODE_PATH may point
    to that runtime; no package is downloaded automatically. Robots and crawl
    budgets remain the caller's responsibility, before invoking this transport.
    """
    def __init__(self, *, enabled=False, timeout=22, max_bytes=750_000, runner=None):
        self.enabled = enabled
        self.timeout = min(30, max(2, float(timeout)))
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
            result = self.runner(["node", str(self.script), canonical, str(self.max_bytes)],
                                 capture_output=True, text=True, timeout=self.timeout, check=False)
            if result.returncode != 0 or len(result.stdout.encode()) > self.max_bytes * 3:
                raise CrawlBlocked("browser_renderer_failed")
            response = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise CrawlBlocked("browser_renderer_unavailable") from exc
        if (not isinstance(response, dict) or response.get("url") != canonical
                or type(response.get("status")) is not int or not isinstance(response.get("body"), str)
                or len(response["body"].encode()) > self.max_bytes):
            raise CrawlBlocked("browser_renderer_invalid_response")
        return response

"""Safe official-partner readiness, separate from public listing research.

These are server-owned capabilities, never inferred from a successful crawl or
from the presence of an outbound product URL. Fanatics has no configured feed.
"""


def marketplace_connections(crawler):
    configured = getattr(crawler, "official_ebay_configured", False) is True
    enabled = configured and getattr(crawler, "official_ebay_enabled", False) is True
    status = "enabled" if enabled else "configured_offline" if configured else "not_configured"
    return [
        {"source": "ebay_us", "status": status, "message": (
            "Official eBay Browse is enabled for this bounded read-only session. Affiliate links appear only when separately configured."
            if enabled else
            "Official eBay Browse is configured but disabled."
            if configured else
            "Official eBay Browse and EPN are not connected. Separately authorized public research may still be available."
        )},
        {"source": "fanatics_collect", "status": "not_configured",
         "message": "Fanatics Collect is not connected. A partner-approved listing feed and affiliate access are required."},
    ]

"""Safe read-only capability projection; never permissions, credentials or URLs."""
from .approved_sources import ApprovedSources

SOURCES = ("ebay_us", "mercari", "snkrdunk")
MESSAGES = {
    "source_access_required": "Live listings are not connected. Approved source access is required.",
    "source_disabled": "This listing source is configured but switched off.",
    "source_revoked": "Access to this listing source has been revoked.",
    "source_window_closed": "The approved read window or request allowance has ended.",
    "source_adapter_unavailable": "This listing source is configured but cannot currently be read.",
}


def source_readiness(crawler):
    """No network request, counter consumption, identity or photo verification."""
    rows = []
    for source in SOURCES:
        policy = crawler.policies.get(source) if type(crawler) is ApprovedSources else None
        status, method, blocker = "not_configured", "none", "source_access_required"
        if policy is not None:
            status = "configured_offline"
            mode = policy.get("mode")
            method = "api" if source == "ebay_us" and mode in {"api_only", "api_preferred"} else "crawl" if mode in {"crawl_only", "api_preferred"} else "none"
            with crawler._revocation_lock:
                revoked = source in crawler._revoked
            if revoked:
                blocker = "source_revoked"
            elif mode == "disabled":
                blocker = "source_disabled"
            else:
                try:
                    crawler.budget.check()
                    if crawler.budget.remaining <= 0:
                        raise ValueError()
                except ValueError:
                    blocker = "source_window_closed"
                else:
                    try:
                        crawler._guard()
                        crawler._method(source)
                        if method == "api":
                            with crawler.api._lock:
                                instant = crawler.api._check()
                                # Discovery alone cannot publish an offer: allow
                                # at least one exact detail after search/token.
                                needed = 3 if crawler.api._token is None else 2
                                if (crawler.api._remaining < needed or crawler.budget.remaining < needed
                                        or crawler.api._token is not None and
                                        (crawler.api._token_until is None or instant >= crawler.api._token_until)):
                                    raise ValueError()
                        status, blocker = "enabled", None
                    except (ValueError, KeyError, TypeError, AttributeError):
                        blocker = "source_adapter_unavailable"
        enabled = status == "enabled"
        rows.append({"source": source, "status": status, "method": method,
                     "listing_read_enabled": enabled,
                     "photo_display": "authorized_only" if policy is not None and policy.get("access_approval") and policy["photo_display_approved"] and not revoked else "not_approved",
                     "blocker": blocker,
                     "message": "Live listing reads are enabled for this approved, bounded session." if enabled else MESSAGES[blocker]})
    return rows

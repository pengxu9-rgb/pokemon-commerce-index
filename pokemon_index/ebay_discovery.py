"""Exact, operator-selected eBay browse pages for bounded public discovery.

These are publisher-facing category pages, not alternate search endpoints.
Configuration is not permission: the caller must check the source's current
robots policy before fetching each page and every discovered listing. Browse
page prices must never be treated as individual listing evidence.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


def browse_urls(values=()):
    """Validate at most five exact public category URLs; do not invent a URL.

    Query strings and other eBay endpoint families are deliberately excluded.
    The resulting URL is only a discovery seed. It establishes neither query
    identity nor listing price, availability, grade or source authorization.
    """
    if not isinstance(values, (tuple, list)) or len(values) > 5:
        raise ValueError("at most five exact eBay public browse URLs required")
    result = []
    for value in values:
        if (not isinstance(value, str) or len(value) > 2048
                or re.search(r"[\s\\\x00-\x1f\x7f]", value)):
            raise ValueError("invalid eBay public browse URL")
        try:
            parsed = urlsplit(value)
            valid = (parsed.scheme == "https" and parsed.hostname in {"www.ebay.com", "ebay.com"}
                     and not parsed.username and not parsed.password and parsed.port in (None, 443)
                     and not parsed.query and not parsed.fragment
                     and re.fullmatch(r"/b/[A-Za-z0-9_-]+/[0-9]+/bn_[0-9]+/?", parsed.path))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("invalid eBay public browse URL")
        canonical = urlunsplit(("https", parsed.hostname, parsed.path.rstrip("/"), "", ""))
        if canonical not in result:
            result.append(canonical)
    return tuple(result)


TRACKING_QUERY_KEYS = {"itmmeta", "itmprp", "hash", "_skw", "_trksid", "_trkparms"}


def listing_anchor(value):
    """Drop only known tracking keys from a public /itm anchor.

    A variation, quantity or unknown query must retain its semantics and is
    rejected. The clean /itm destination still requires a robots check and a
    fresh detail response; an anchor never supplies a price.
    """
    if (not isinstance(value, str) or len(value) > 2048
            or re.search(r"[\s\\\x00-\x1f\x7f]", value)):
        raise ValueError("invalid eBay listing anchor")
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname in {"www.ebay.com", "ebay.com"}
                 and not parsed.username and not parsed.password and parsed.port in (None, 443)
                 and not parsed.fragment
                 and re.fullmatch(r"/itm/(?:[A-Za-z0-9_-]+/)?[0-9]{8,20}/?", parsed.path)
                 and set(parse_qs(parsed.query, keep_blank_values=True)) <= TRACKING_QUERY_KEYS)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("invalid eBay listing anchor")
    return urlunsplit(("https", parsed.hostname, parsed.path.rstrip("/"), "", ""))

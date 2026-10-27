"""Bounded public-page research. This does not authorize collection or create offers.

The injected fetch contract is ``fetch(url) -> {status, body, headers?, url?}``.
Network transport is disabled unless explicitly enabled. eBay additionally needs
explicit source authorization. SNKRDUNK catalog floors stay product summaries.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from typing import Any, Callable
import unicodedata
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from . import core, marketplace_sources
from .marketplace_quality import grade_details
from .ebay_discovery import browse_urls as validate_ebay_browse_urls, listing_anchor as ebay_listing_anchor
from .mercari_discovery import preload_product_urls
from .public_robots import RobotsPolicy
from .seller_evidence import extracted_seller, seller_identity
from .listing_evidence import extracted_listing_evidence

USER_AGENT = "PokemonPublicResearch/1.0"
HOSTS = {"mercari": {"jp.mercari.com"}, "ebay_us": {"www.ebay.com", "ebay.com"},
         "snkrdunk": {"snkrdunk.com", "www.snkrdunk.com"}}
CURRENCY_EXPONENTS = {"JPY": 0, "KRW": 0, "USD": 2, "HKD": 2, "EUR": 2,
                      "GBP": 2, "CAD": 2, "AUD": 2}


class CrawlBlocked(ValueError):
    pass


def _source(value: str) -> str:
    value = "ebay_us" if value == "ebay" else value
    if value not in HOSTS:
        raise CrawlBlocked("unsupported_source")
    return value


def _url(value: str, *, source: str | None = None, purpose: str = "detail",
         configured: set[str] | None = None) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise CrawlBlocked("unsafe_url")
    try:
        p = urlsplit(value)
        if p.scheme != "https" or p.username or p.password or p.port not in (None, 443) or p.fragment:
            raise CrawlBlocked("https_marketplace_url_required")
        detected = next((s for s, hosts in HOSTS.items() if p.hostname in hosts), None)
        if not detected or (source and source != detected):
            raise CrawlBlocked("marketplace_host_not_allowed")
        if "%" in p.path or "//" in p.path or "/../" in p.path or p.path.endswith("/.."):
            raise CrawlBlocked("marketplace_path_not_allowed")
        query = parse_qs(p.query, keep_blank_values=True)
        if purpose == "robots":
            valid = p.path == "/robots.txt" and not query
        elif purpose == "sitemap":
            valid = value in (configured or set()) and not query and bool(re.fullmatch(r"/[A-Za-z0-9_./-]+\.xml", p.path))
        elif purpose == "browse":
            valid = detected == "ebay_us" and value in (configured or set()) and value in validate_ebay_browse_urls([value])
        elif purpose == "search":
            valid = ((detected == "mercari" and p.path == "/search" and set(query) == {"keyword"}) or
                     (detected == "ebay_us" and p.path == "/sch/i.html" and set(query) == {"_nkw"}) or
                     (detected == "snkrdunk" and p.path == "/search" and set(query) == {"keywords"}))
        elif detected == "mercari":
            valid = bool(re.fullmatch(r"/item/m[0-9]+/?", p.path)) and not query
        elif detected == "ebay_us":
            valid = bool(re.fullmatch(r"/itm/(?:[A-Za-z0-9_-]+/)?[0-9]{8,20}/?", p.path)) and not query
        else:
            # Public catalog paths only. These are not individual seller offers.
            valid = bool(re.fullmatch(r"/(?:apparels/[0-9]+(?:/used/[0-9]+)?|products/[0-9]+)/?", p.path)) and not query
        if not valid:
            raise CrawlBlocked("marketplace_path_not_allowed")
        return urlunsplit(("https", p.hostname, p.path.rstrip("/") or "/", p.query, "")), detected
    except ValueError as exc:
        if isinstance(exc, CrawlBlocked):
            raise
        raise CrawlBlocked("unsafe_url") from exc


def canonical_product_url(url: str) -> tuple[str, str, str]:
    """Validate a public listing/catalog URL; return source, native ID, URL."""
    canonical, source = _url(url)
    return source, urlsplit(canonical).path.rstrip("/").rsplit("/", 1)[-1], canonical


class _Page(HTMLParser):
    def __init__(self, body: str):
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self._anchors: list[dict] = []
        self.scripts: list[str] = []
        self._json = False
        self._script: list[str] = []
        self._title = False
        self._in_script = False
        self._inline: list[str] = []
        self.inline_scripts: list[str] = []
        self.title = ""
        self.visible_text: list[str] = []
        self.primary_stock_text: list[str] = []
        self._elements: list[dict] = []
        self.login = False
        self.meta: dict[str, list[str]] = {}
        self.canonicals: list[str] = []
        self.feed(body)
        for element in self._elements:
            if element["stock"] and not element["hidden"]:
                self.primary_stock_text.append(" ".join(element["text"]))

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        # Stock controls/headings are evidence only when visible and outside
        # navigation/recommendations. Script data and hidden component copies
        # must not override the current listing's displayed state.
        hidden = (tag in {"script", "style", "template", "noscript", "nav", "aside", "footer"}
                  or "hidden" in attrs or str(attrs.get("aria-hidden", "")).lower() == "true"
                  or bool(re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", str(attrs.get("style", "")), re.I))
                  or bool(re.search(r"(?:^|[\s_-])(?:related|recommend\w*|similar|carousel)(?:$|[\s_-])",
                                    " ".join(str(attrs.get(k, "")) for k in ("id", "class", "aria-label")), re.I)))
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self._elements.append({"tag": tag, "hidden": hidden or bool(self._elements and self._elements[-1]["hidden"]),
                                   "stock": tag in {"h1", "h2", "h3", "h4", "h5", "h6", "button"}
                                   or str(attrs.get("role", "")).lower() in {"button", "status", "alert"}, "text": []})
        if tag == "script":
            self._in_script, self._inline = True, []
        if tag == "a" and isinstance(attrs.get("href"), str):
            self.links.append(attrs["href"])
            self._anchors.append({"href": attrs["href"], "text": [str(attrs.get("aria-label", "")), str(attrs.get("title", ""))]})
        if tag == "img" and attrs.get("alt") and self._anchors:
            self._anchors[-1]["text"].append(attrs["alt"])
        if tag == "script" and attrs.get("type", "").lower().split(";")[0] == "application/ld+json":
            self._json, self._script = True, []
        if tag == "title":
            self._title = True
        if tag == "input" and attrs.get("type", "").lower() == "password":
            self.login = True
        if tag == "meta" and attrs.get("property", attrs.get("name")):
            key = attrs.get("property", attrs.get("name")).lower()
            self.meta.setdefault(key, []).append(attrs.get("content", ""))
        if tag == "link" and attrs.get("rel", "").lower() == "canonical" and attrs.get("href"):
            self.canonicals.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag == "a" and self._anchors:
            anchor = self._anchors.pop()
            self.anchors.append((anchor["href"], " ".join(anchor["text"])))
        for index in range(len(self._elements) - 1, -1, -1):
            if self._elements[index]["tag"] == tag:
                for element in self._elements[index:]:
                    if element["stock"] and not element["hidden"]:
                        self.primary_stock_text.append(" ".join(element["text"]))
                del self._elements[index:]
                break
        if tag == "script" and self._in_script:
            self.inline_scripts.append("".join(self._inline))
            self._in_script = False
        if tag == "script" and self._json:
            self.scripts.append("".join(self._script))
            self._json = False
        if tag == "title":
            self._title = False

    def handle_data(self, data):
        for anchor in self._anchors:
            anchor["text"].append(data)
        if not self._elements or not self._elements[-1]["hidden"]:
            for element in self._elements:
                if element["stock"] and not element["hidden"]:
                    element["text"].append(data)
        if not self._in_script:
            self.visible_text.append(data)
        if self._in_script:
            self._inline.append(data)
        if self._json:
            self._script.append(data)
        if self._title:
            self.title += data


def _walk(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _typed(value, kind):
    types = value.get("@type", [])
    return kind in ([types] if isinstance(types, str) else types if isinstance(types, list) else [])


def _meta_one(page, key):
    values = set(page.meta.get(key, []))
    return next(iter(values)) if len(values) == 1 else None


_COLLECTOR_REF = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{0,4}[0-9]{1,4})\s*/\s*([A-Za-z]{0,4}[0-9]{1,4})(?![A-Za-z0-9])")
_SET_REF = re.compile(
    r"(?<![A-Za-z0-9])((?:SWSH|HGSS|BASE|PROMO|PCG|ADV|SVP|SMP|BWP|DPP|HSP|XYP|"
    r"SV|SM|XY|BW|DP|PT|CP|GYM|EX|POP|PL|COL|MEW|CEL|MC|S)[0-9]+[A-Za-z0-9.-]*)(?![A-Za-z0-9])")

# A bounded contradiction guard, not a catalog translation/equivalence service.
# The full reviewed bilingual resolver needs a catalog DB, which this transport
# deliberately does not own. Unknown names need literal grounding for seed reuse.
_CHARACTER_NAMES = (("Pikachu", "ピカチュウ"), ("Charizard", "リザードン"),
                    ("Eevee", "イーブイ"), ("Mewtwo", "ミュウツー"), ("Mew", "ミュウ"),
                    ("Gengar", "ゲンガー"), ("Rayquaza", "レックウザ"),
                    ("Umbreon", "ブラッキー"), ("Espeon", "エーフィ"),
                    ("Gardevoir", "サーナイト"))


def _named_characters(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    matches = []
    for canonical, localized in _CHARACTER_NAMES:
        for alias in (canonical.casefold(), localized):
            pattern = (r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])"
                       if alias.isascii() else re.escape(alias))
            for match in re.finditer(pattern, text):
                matches.append((match.start(), match.end(), canonical.casefold()))
    # Japanese ミュウ must not turn ミュウツー into a two-character claim.
    return {name for start, end, name in matches if not any(
        left <= start and right >= end and (left, right) != (start, end)
        for left, right, _ in matches)}


def _seed_name_grounded(query, title):
    names, candidate_names = _named_characters(query), _named_characters(title)
    if names:
        return names == candidate_names
    residual = unicodedata.normalize("NFKC", query).upper()
    residual = core.GRADE_RE.sub(" ", _SET_REF.sub(" ", _COLLECTOR_REF.sub(" ", residual)))
    residual = re.sub(r"(?<![A-Z0-9])[0-9]{1,4}(?![A-Z0-9])", " ", residual)
    residual = re.sub(r"\b(?:POKEMON|POKÉMON|CARD|CARDS|RAW|GRADED|SLAB|HOLO|JAPANESE|ENGLISH|JA|EN|JP|AR|SAR|SR|UR|RR)\b", " ", residual)
    residual = re.sub(r"ポケモン|カード|鑑定品|鑑定済", " ", residual)
    # Preserve every script and internal digits: dropping unfamiliar letters
    # would make all([]) authorize an unrelated seed; Porygon2 is not Porygon.
    parts = re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", residual, flags=re.UNICODE)
    normalized_title = unicodedata.normalize("NFKC", title).upper()
    return all(re.search(r"(?<!\w)" + re.escape(part) + r"(?!\w)", normalized_title) for part in parts)


def _query_context(text):
    text = unicodedata.normalize("NFKC", text).upper()
    numbers = set()
    for match in _COLLECTOR_REF.finditer(text):
        def number(part):
            prefix, digits = re.fullmatch(r"([A-Z]*)([0-9]+)", part).groups()
            return prefix + str(int(digits))
        numbers.add(number(match[1]) + "/" + number(match[2]))
    # Grade and coded collector numbers must not masquerade as set context.
    stripped = _COLLECTOR_REF.sub(" ", text)
    stripped = core.GRADE_RE.sub(" ", stripped)
    sets = {match[1] for match in _SET_REF.finditer(stripped)
            if not re.match(r"^(?:PSA|BGS|CGC|ARS|PGC)[0-9]", match[1])}
    bare = set(re.findall(r"(?<![A-Z0-9])[0-9]{1,4}(?![A-Z0-9])", _SET_REF.sub(" ", stripped)))
    return {"numbers": numbers, "sets": sets, "bare_numbers": {str(int(n)) for n in bare},
            "characters": _named_characters(text)}


def _query_matches(query_context, title):
    candidate = _query_context(title)
    return (len(query_context["numbers"]) <= 1
            and (not query_context["characters"] or not candidate["characters"]
                 or query_context["characters"] == candidate["characters"])
            and (not query_context["numbers"] or candidate["numbers"] == query_context["numbers"])
            and query_context["sets"].issubset(candidate["sets"])
            and (bool(query_context["numbers"]) or not query_context["bare_numbers"]
                 or query_context["bare_numbers"].issubset(
                     candidate["bare_numbers"] | {number.split("/")[0] for number in candidate["numbers"]})))


def _primary_title(page):
    title = _meta_one(page, "og:title")
    if title:
        return title
    products = []
    for script in page.scripts[:25]:
        try:
            products.extend(node for node in _walk(json.loads(script))
                            if _typed(node, "Product") or _typed(node, "ProductGroup"))
        except (ValueError, RecursionError):
            continue
    return str(products[0].get("name") or page.title) if len(products) == 1 else page.title


def _snkr_used_item(page, url):
    """Decode public React Flight JSON only, binding the complete used-item path.

    No JavaScript execution, loose price regexes or unrelated product floor reads.
    The endpoint's displayed combined listed/bidding status is not stock proof.
    """
    match = re.fullmatch(r"/apparels/([0-9]+)/used/([0-9]+)", urlsplit(url).path)
    if not match:
        return None
    apparel_id, listing_id = map(int, match.groups())
    chunks = []
    for script in page.inline_scripts[:200]:
        push = re.fullmatch(r"\s*self\.__next_f\.push\((\[.*\])\)\s*;?\s*", script, re.S)
        if not push:
            continue
        try:
            value = json.loads(push[1])
        except (ValueError, RecursionError):
            continue
        if isinstance(value, list) and len(value) == 2 and value[0] == 1 and isinstance(value[1], str):
            chunks.append(value[1])
    matches = {}
    for line in "".join(chunks).splitlines():
        record = re.fullmatch(r"[a-fA-F0-9]+:([\[{].*)", line)
        if not record:
            continue
        try:
            for node in _walk(json.loads(record[1])):
                data = node.get("usedApparelData")
                item = data.get("apparelUsedItem") if isinstance(data, dict) else None
                if (node.get("apparelId") == apparel_id and node.get("listingId") == listing_id
                        and isinstance(item, dict) and item.get("id") == listing_id
                        and isinstance(item.get("apparel"), dict) and item["apparel"].get("id") == apparel_id):
                    matches[json.dumps(item, sort_keys=True, ensure_ascii=False)] = item
        except (ValueError, RecursionError, TypeError):
            continue
    return next(iter(matches.values())) if len(matches) == 1 else None


def _snkr_used_quality(item, title, evidence):
    """Extract claims only from this path-bound item, never platform assurances."""
    condition = item.get("displayWearCount")
    condition = condition.strip() if isinstance(condition, str) and len(condition) <= 512 else None
    code = item.get("wearCount")
    code = code if isinstance(code, str) and len(code) <= 160 else ""
    coded = re.fullmatch(r"tradingCardSingleCondition(PSA|BGS|CGC|ARS|PGC)(10|[1-9](?:\.5)?)", code, re.I)
    displayed = list(core.GRADE_RE.finditer(unicodedata.normalize("NFKC", condition or "")))
    explicit = (coded.group(1).upper(), coded.group(2)) if coded else (
        (displayed[0].group(1).upper(), displayed[0].group(2)) if len(displayed) == 1 else None)
    raw_claim = bool(not explicit and condition and re.fullmatch(r"raw|ungraded|未鑑定|鑑定前", condition, re.I))
    fields = {"seller_condition": condition}
    if explicit:
        fields.update(grade_company=explicit[0], grade_value=explicit[1])
    elif raw_claim:
        fields.update(grade_company="RAW", grade_value="raw")
    try:
        quality, review = marketplace_sources._quality(fields, title, evidence)
    except ValueError:
        quality = {"seller_condition": condition, "grade_company": explicit[0] if explicit else None,
                   "grade_value": explicit[1] if explicit else None,
                   "grade_evidence": "ambiguous_seller_title_claim", "evidence_ref": evidence,
                   "certificate_verified": False, "authenticity_verified": False,
                   "physical_inspection_performed": False}
        review = True
    # An explicit used-item condition is independently attributable seller
    # evidence even when the shared catalog/product title contains no grade.
    basis = "snkr_used_condition" if explicit or raw_claim else quality["grade_evidence"]
    detail = grade_details(quality["grade_company"], quality["grade_value"], title=title,
                           condition=condition, evidence=basis, raw_claim=raw_claim,
                           source_review=review and not (explicit or raw_claim))
    quality.update(grade_kind=detail["kind"], grade_evidence=detail["evidence"],
                   grade_review_required=detail["review_required"],
                   grade_review_reasons=detail["review_reasons"])
    return quality, detail["review_required"]


def _money(offer):
    amount, currency = offer.get("price"), offer.get("priceCurrency")
    if not currency and isinstance(offer.get("priceSpecification"), dict):
        amount = offer["priceSpecification"].get("price")
        currency = offer["priceSpecification"].get("priceCurrency")
    if currency not in CURRENCY_EXPONENTS or isinstance(amount, bool) or not isinstance(amount, (str, int, float)):
        return None, None
    text = str(amount)
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text) or len(text) > 24:
        return None, None
    try:
        minor = Decimal(text) * (10 ** CURRENCY_EXPONENTS[currency])
        if not minor.is_finite() or minor <= 0 or minor != minor.to_integral_value() or minor >= 2**63:
            return None, None
        return int(minor), currency
    except (InvalidOperation, ValueError):
        return None, None


def _primary_sold_out(page):
    # Match explicit unavailable/ended listing statuses, rather than seller prose or
    # recommendation snippets containing the words "sold out".
    return any(re.fullmatch(
        r"(?:(?:(?:this\s+)?(?:item|listing|product)\s+(?:(?:is|has)\s+)?)|(?:この)?商品は)?"
        r"(?:currently\s+)?(?:sold(?:\s*out)?|out\s*of\s*stock|unavailable|ended|"
        r"no\s+longer\s+available|not\s+(?:available|for\s+sale)|"
        r"売り切れ(?:ました|済み)?|在庫(?:切れ|なし)|販売終了|售罄|已售出)[\s.!。！]*",
        unicodedata.normalize("NFKC", text).strip(), re.I) for text in page.primary_stock_text)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        records = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        addresses = {record[4][0] for record in records}
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise CrawlBlocked("nonpublic_dns_address")
        # Connect the checked address directly; TLS still verifies the marketplace hostname.
        raw = socket.create_connection((sorted(addresses)[0], self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class PublicHTMLFetch:
    """No cookies, auth, automatic redirects, private APIs or browser challenge bypass."""
    def __init__(self, *, enabled=False, timeout=8, max_bytes=750_000, sitemap_urls=(), browse_urls=()):
        if type(enabled) is not bool:
            raise ValueError("network opt-in must be an explicit boolean")
        self.enabled = enabled
        self.timeout = min(10, max(0.1, float(timeout)))
        self.max_bytes = min(1_000_000, max(1024, int(max_bytes)))
        self.sitemaps = set(sitemap_urls)
        self.browse_urls = set(validate_ebay_browse_urls(browse_urls))

    def __call__(self, url):
        if not self.enabled:
            raise CrawlBlocked("network_disabled")
        p = urlsplit(url)
        purpose = ("robots" if p.path == "/robots.txt" else "browse" if url in self.browse_urls
                   else "search" if p.path in ("/search", "/sch/i.html")
                   else "sitemap" if url in self.sitemaps else "detail")
        _url(url, purpose=purpose, configured=self.sitemaps | self.browse_urls)
        connection = _PinnedHTTPS(p.hostname, timeout=self.timeout, context=ssl.create_default_context())
        try:
            connection.request("GET", p.path + ("?" + p.query if p.query else ""),
                               headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xml,text/plain",
                                        "Accept-Encoding": "identity"})
            response = connection.getresponse()
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise CrawlBlocked("response_too_large")
            return {"status": response.status, "body": body,
                    "headers": dict(response.getheaders()), "url": url}
        finally:
            connection.close()


class Crawler:
    def __init__(self, fetch: Callable | None = None, *, renderer: Callable | None = None, allow_network=False,
                 authorized_sources=("mercari", "snkrdunk"), snkr_seed_urls=(),
                 snkr_sitemap_urls=(), ebay_browse_urls=(), now=None, max_pages=8, max_bytes=750_000,
                 timeout=8, max_seconds=30):
        self.authorized_sources = {_source(s) for s in authorized_sources}
        self.max_pages = min(12, max(2, int(max_pages)))
        self.max_bytes = min(1_000_000, max(1024, int(max_bytes)))
        self.max_seconds = min(60, max(0.1, float(max_seconds)))
        self.ebay_browse_urls = validate_ebay_browse_urls(ebay_browse_urls)
        self.fetch = fetch or PublicHTMLFetch(enabled=allow_network, timeout=timeout, max_bytes=self.max_bytes,
                                             sitemap_urls=snkr_sitemap_urls, browse_urls=self.ebay_browse_urls)
        self.renderer = renderer
        self.now = now or (lambda: datetime.now(timezone.utc))
        if len(snkr_seed_urls) > 5 or len(snkr_sitemap_urls) > 5:
            raise ValueError("at most five configured seed or sitemap URLs")
        self.seeds = tuple(_url(u, source="snkrdunk")[0] for u in snkr_seed_urls)
        self.sitemaps = set(snkr_sitemap_urls)
        for url in self.sitemaps:
            _url(url, source="snkrdunk", purpose="sitemap", configured=self.sitemaps)
        self.discovery_urls = self.sitemaps | set(self.ebay_browse_urls)
        self._reset()

    def _reset(self):
        self._pages, self._started, self._robots = 0, time.monotonic(), {}
        self._html_cache = {}

    def _request(self, url, source, purpose, *, fetcher=None):
        url, _ = _url(url, source=source, purpose=purpose, configured=self.discovery_urls)
        if self._pages >= self.max_pages or time.monotonic() - self._started > self.max_seconds:
            raise CrawlBlocked("crawl_budget_exhausted")
        self._pages += 1
        response = (fetcher or self.fetch)(url)
        if time.monotonic() - self._started > self.max_seconds:
            raise CrawlBlocked("crawl_budget_exhausted")
        if not isinstance(response, dict) or type(response.get("status")) is not int:
            raise CrawlBlocked("invalid_fetch_response")
        final_url = response.get("url", url)
        checked_final, _ = _url(final_url, source=source, purpose=purpose, configured=self.discovery_urls)
        if checked_final != url:
            # A fetch implementation must not invisibly follow redirects.
            raise CrawlBlocked("unvalidated_redirect")
        body = response.get("body", "")
        if not isinstance(body, (str, bytes)) or len(body.encode() if isinstance(body, str) else body) > self.max_bytes:
            raise CrawlBlocked("response_too_large")
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        raw_headers = response.get("headers", {})
        if not isinstance(raw_headers, dict):
            raise CrawlBlocked("invalid_fetch_response")
        headers = {str(k).lower(): str(v) for k, v in raw_headers.items()}
        if headers.get("content-encoding", "identity").lower() not in ("", "identity"):
            raise CrawlBlocked("encoded_response_not_supported")
        return response["status"], body, headers

    def _allowed(self, url, source):
        origin = "https://" + urlsplit(url).hostname
        if origin not in self._robots:
            status, body, _ = self._request(origin + "/robots.txt", source, "robots")
            if status != 200:
                raise CrawlBlocked("robots_unavailable")
            robot = RobotsPolicy(body)
            self._robots[origin] = robot
        robot = self._robots[origin]
        if not robot.can_fetch(USER_AGENT, url):
            raise CrawlBlocked("robots_disallowed")
        # Do not silently exceed a publisher's requested pacing.
        if robot.requires_pacing(USER_AGENT):
            raise CrawlBlocked("robots_pacing_requires_scheduled_crawl")

    def _page(self, url, source, purpose="detail", *, fetcher=None):
        if source not in self.authorized_sources:
            raise CrawlBlocked("source_access_not_authorized")
        for hop in range(3):
            url, _ = _url(url, source=source, purpose=purpose, configured=self.discovery_urls)
            self._allowed(url, source)
            status, body, headers = self._request(url, source, purpose, fetcher=fetcher)
            if status in (301, 302, 303, 307, 308):
                if hop == 2 or not headers.get("location"):
                    raise CrawlBlocked("redirect_limit")
                url = urljoin(url, headers["location"])
                continue
            if status != 200:
                raise CrawlBlocked("http_" + str(status))
            content = headers.get("content-type", "").split(";")[0].lower()
            expected = {"application/xml", "text/xml"} if purpose == "sitemap" else {"text/html", "application/xhtml+xml"}
            if content and content not in expected:
                raise CrawlBlocked("unexpected_content_type")
            probe = _Page(body) if purpose != "sitemap" else None
            visible = " ".join(probe.visible_text) if probe else ""
            if ((probe and re.search(r"captcha|access denied|verify you are human|just a moment", probe.title, re.I))
                    or re.search(r"verify you are human|captcha challenge|robot check|access denied", visible, re.I)):
                raise CrawlBlocked("public_page_challenge")
            return url, body
        raise CrawlBlocked("redirect_limit")

    def _detail(self, url):
        url, source = _url(url)
        url, body = self._html_cache.get(url) or self._page(url, source)
        self._html_cache[url] = (url, body)
        page = _Page(body)
        if page.login:
            raise CrawlBlocked("login_required")
        objects = []
        for script in page.scripts[:25]:
            try:
                objects.extend(_walk(json.loads(script)))
            except (ValueError, RecursionError):
                continue
        # A Product explicitly nested under an Offer is its subject, not a
        # second page-wide primary product. It is read only after that Offer's
        # exact URL is bound below; unrelated Product nodes remain ambiguous.
        offer_subjects = {id(node["itemOffered"]) for node in objects
                          if _typed(node, "Offer") and isinstance(node.get("itemOffered"), dict)}
        products = [p for p in objects if _typed(p, "Product") and id(p) not in offer_subjects]
        groups = [p for p in objects if _typed(p, "ProductGroup")]
        product = products[0] if len(products) == 1 else groups[0] if not products and len(groups) == 1 else {}
        title = unicodedata.normalize("NFKC", str(product.get("name") or _meta_one(page, "og:title") or page.title)).strip()[:2000]
        if not title:
            raise CrawlBlocked("missing_product_title")
        offers = product.get("offers", [])
        offers = [offers] if isinstance(offers, dict) else offers
        offers = offers if isinstance(offers, list) else []
        snkr_used = source == "snkrdunk" and bool(re.fullmatch(r"/apparels/[0-9]+/used/[0-9]+", urlsplit(url).path))
        variants = bool(groups or any(
            (_typed(node, "Product") or _typed(node, "ProductGroup"))
            and any(key in node for key in ("hasVariant", "isVariantOf", "variesBy"))
            for node in objects))
        summary = variants or (source == "snkrdunk" and not snkr_used) or any(isinstance(o, dict) and (
            _typed(o, "AggregateOffer") or any(k in o for k in ("lowPrice", "highPrice", "offerCount"))) for o in offers)
        scope = "product_summary" if summary else "listing"
        reasons = []
        if variants:
            reasons.append("variant_unresolved")
        if len(products) > 1:
            reasons.append("product_identity_ambiguous")
        identities = ([product["url"]] if product.get("url") else []) + page.canonicals
        if _meta_one(page, "og:url"):
            identities.append(_meta_one(page, "og:url"))
        for identity in identities:
            try:
                if _url(urljoin(url, identity), source=source)[0] != url:
                    reasons.append("product_url_mismatch")
            except (ValueError, TypeError):
                reasons.append("product_url_mismatch")
        valid = [o for o in offers if isinstance(o, dict) and _typed(o, "Offer")]
        rsc_item = _snkr_used_item(page, url) if snkr_used else None
        rsc_money = []
        if rsc_item:
            amount, displayed = rsc_item.get("price"), rsc_item.get("commaPrice")
            # Only the path-bound used item and its exact yen display establish
            # listing money. A related product's catalog floor is another scope.
            if type(amount) is int and amount > 0 and displayed == "¥" + format(amount, ","):
                rsc_money = [{"price": amount, "priceCurrency": "JPY"}]
        currency_basis = "explicit_price_currency"
        meta_amounts = set(page.meta.get("product:price:amount", []))
        meta_currencies = set(page.meta.get("product:price:currency", []))
        # All these fields describe the current page's primary product. Do not
        # silently prefer one complete money claim over contradictory metadata.
        # Prices nested under related products/catalog floors are not included.
        if len(meta_currencies) > 1:
            reasons.append("price_evidence_conflict")
        meta_currency = next(iter(meta_currencies)) if len(meta_currencies) == 1 else None
        meta_money = [{"price": amount, "priceCurrency": meta_currency} for amount in (meta_amounts or [None])]
        meta_money = meta_money if meta_amounts or meta_currencies else []
        if not products and not meta_money and rsc_money:
            valid = [{"@type": "Offer", **rsc_money[0]}]
            currency_basis = "japanese_site_yen_display"
        if len(valid) > 1:
            reasons.append("individual_offer_ambiguous")
        for offer in valid:
            if offer.get("url"):
                try:
                    if _url(urljoin(url, offer["url"]), source=source)[0] != url:
                        reasons.append("offer_url_mismatch")
                except (ValueError, TypeError):
                    reasons.append("offer_url_mismatch")
        # Neither tier floors nor auctions nor variable catalog prices become listing asks.
        if summary:
            reasons.append("product_summary_not_listing")
        visible = unicodedata.normalize("NFKC", " ".join(page.visible_text))
        auction_cues = (r"\b(?:current|starting|winning|highest)\s+bid\b|"
                        r"\bauction\s+(?:ends?|ending|end\s+time)\b|"
                        r"\bplace\s+(?:a\s+)?bid\b|\b[0-9]+\s+bids?\b|"
                        r"\bbidding\s+(?:ends?|closes?)\b|現在(?:の)?入札|入札(?:数|件数|価格)|"
                        r"オークション(?:終了|形式)|競売")
        if (re.search(r"auction|\bbid(?:s|ding)?\b", json.dumps(product), re.I)
                or re.search(auction_cues, visible, re.I)):
            reasons.append("auction_not_fixed_price")
        price_evidence = valid + meta_money + rsc_money
        for offer in valid:
            if isinstance(offer.get("priceSpecification"), dict):
                price_evidence.append(offer["priceSpecification"])
        amounts = {_money(o) for o in price_evidence}
        if len(amounts) > 1:
            reasons.append("price_evidence_conflict")
        price, currency = next(iter(amounts)) if len(amounts) == 1 and not reasons else (None, None)
        states = {str(o.get("availability", "")).rstrip("/").rsplit("/", 1)[-1] for o in valid}
        availability = {"InStock": "in_stock", "OutOfStock": "out_of_stock", "SoldOut": "out_of_stock"}.get(
            next(iter(states)) if len(states) == 1 else "", "unknown")
        if reasons:
            availability = "unknown"
        # A primary, visible sold-out control/heading rules out stock even when
        # a stale JSON-LD Offer still says InStock. It must not reach a provider.
        if _primary_sold_out(page):
            if "InStock" in states:
                reasons.append("availability_evidence_conflict")
            availability = "out_of_stock"
        # Exact used-item sold/transaction state overrides stale generic Product
        # metadata. Status9 is awaiting arrival at SNKRDUNK, not an active ask.
        if rsc_item and (rsc_item.get("isDisplaySold") is True or rsc_item.get("status") == 9):
            availability = "out_of_stock"
        status = {"in_stock": "on_sale", "out_of_stock": "sold_out"}.get(availability, "unknown")
        if status == "unknown":
            reasons.append("availability_unknown")
        if price is None:
            reasons.append("price_unknown")
        stamp = self.now()
        stamp = stamp.isoformat() if isinstance(stamp, datetime) else str(stamp)
        evidence = "public-html:sha256:" + hashlib.sha256(body.encode()).hexdigest()
        # Only the exact path-bound used item or this one unambiguous Offer can
        # identify a seller. Product ratings, related items and page-wide seller
        # graphs cannot become this listing's reputation evidence.
        seller = None
        seller_conflict = False
        if scope == "listing" and not any(reason in reasons for reason in (
                "product_identity_ambiguous", "product_url_mismatch", "offer_url_mismatch",
                "individual_offer_ambiguous")):
            seller_candidates = []
            for value in ([rsc_item.get("seller")] if rsc_item else []) + (
                    [valid[0].get("seller")] if len(valid) == 1 else []):
                captured = extracted_seller(value, source, evidence, stamp)
                if captured is not None:
                    seller_candidates.append(captured)
            if len({json.dumps(seller_identity(value), sort_keys=True) for value in seller_candidates}) > 1:
                seller_conflict = True
                reasons.append("seller_identity_conflict")
            elif seller_candidates:
                seller = seller_candidates[0]
        try:
            quality, needs_review = (_snkr_used_quality(rsc_item, title, evidence) if rsc_item
                                     else marketplace_sources._quality({}, title, evidence))
        except ValueError:
            quality = {"seller_condition": None, "grade_company": None, "grade_value": None,
                       "grade_evidence": "ambiguous_seller_title_claim", "evidence_ref": evidence,
                       "certificate_verified": False, "authenticity_verified": False,
                       "physical_inspection_performed": False}
            needs_review = True
        certificate = re.search(r"(?:cert(?:ificate)?(?:\s*(?:no\.?|number|#))?|鑑定番号)\s*[:#：]?\s*([0-9]{6,12})(?![0-9])", title, re.I)
        quality["certificate_number_claim"] = certificate.group(1) if certificate else None
        needs_review = needs_review or seller_conflict
        size = rsc_item.get("size") if rsc_item else None
        count_label = size.get("localizedName") if isinstance(size, dict) else None
        listing_quantity = (int(count_label[:-1]) if isinstance(count_label, str)
                            and re.fullmatch(r"[1-9][0-9]?枚", count_label) else None)
        native = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
        listing_identity, listing_photos = None, []
        if scope == "listing" and not any(reason in reasons for reason in (
                "product_identity_ambiguous", "product_url_mismatch", "offer_url_mismatch", "individual_offer_ambiguous")):
            listing_identity, listing_photos = extracted_listing_evidence(source, native, url, stamp, evidence,
                item=rsc_item, offer=valid[0] if len(valid) == 1 else None)
        return {"source": source, "native_id": native, "url": url, "title": title,
                "price_minor": price, "currency": currency, "status": status,
                "availability": availability, "observed_at": stamp, "scope": scope,
                "grade_company": quality["grade_company"], "grade_value": quality["grade_value"],
                "certificate_number_claim": quality["certificate_number_claim"],
                "certificate_verified": False, "authenticity_verified": False,
                "identity_status": "unresolved", "variant_status": "unresolved" if variants else "not_asserted",
                "price_status": "known" if price is not None else "unknown",
                "currency_basis": currency_basis if currency else None,
                "source_status_text": rsc_item.get("statusText") if rsc_item else None,
                "listing_quantity": listing_quantity,
                "seller": seller,
                "listing_identity": listing_identity, "listing_photos": listing_photos,
                "evidence_ref": evidence, "marketplace_quality": quality,
                "quality_review_required": needs_review, "exclusion_reasons": sorted(set(reasons)),
                "purchase_action": None, "sold_sales_available": False}

    def detail(self, url):
        """Refresh one allowlisted public listing/catalog URL; no identity matching."""
        self._reset()
        return self._detail(url)

    def search(self, source, query, limit=5):
        """Discover public URLs and inspect a bounded number of their detail pages."""
        source = _source(source)
        if not isinstance(query, str) or not query.strip() or len(query) > 512 or re.search(r"[\x00-\x1f]|://", query):
            raise ValueError("bounded plain-text query required")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("limit must be 1..5")
        self._reset()
        result = {"source": source, "status": "ok", "message": "public_html_research",
                  "candidates": [], "listings": [], "errors": [], "product_summaries": []}
        query_context = _query_context(query)
        seed_fallback = False
        mercari_preload = False
        try:
            if source not in self.authorized_sources:
                raise CrawlBlocked("source_access_not_authorized")
            links = []
            if source == "snkrdunk":
                # This GET form and its `keywords` input were verified in public HTML.
                search_url = "https://snkrdunk.com/search?" + urlencode({"keywords": query.strip()})
                try:
                    base, body = self._page(search_url, source, "search")
                    page = _Page(body)
                    if page.login:
                        raise CrawlBlocked("login_required")
                    for href in page.links:
                        try:
                            links.append(_url(urljoin(base, href), source=source)[0])
                        except (ValueError, TypeError):
                            pass
                except (CrawlBlocked, OSError, TimeoutError) as exc:
                    result["discovery_error"] = str(exc)[:160]
                if not links:
                    seed_fallback = True
                    grounded = (len(query_context["numbers"]) == 1 or
                                (query_context["sets"] and len(query_context["bare_numbers"]) == 1))
                    if not grounded:
                        raise CrawlBlocked("query_mapping_required")
                    for seed in self.seeds:
                        seed_url, seed_body = self._page(seed, source)
                        self._html_cache[seed_url] = (seed_url, seed_body)
                        page = _Page(seed_body)
                        if page.login:
                            raise CrawlBlocked("login_required")
                        if (not _query_matches(query_context, _primary_title(page))
                                or not _seed_name_grounded(query, _primary_title(page))):
                            continue
                        parent = urlsplit(seed_url).path.split("/used/", 1)[0] + "/used/"
                        links.extend(urljoin(seed_url, href) for href in page.links
                                     if urlsplit(urljoin(seed_url, href)).path.startswith(parent))
                        links.append(seed_url)
                    for sitemap in sorted(self.sitemaps):
                        base, body = self._page(sitemap, source, "sitemap")
                        try:
                            root = ET.fromstring(body)
                            if root.tag.rsplit("}", 1)[-1] != "urlset":
                                raise CrawlBlocked("sitemap_index_requires_explicit_seed")
                            links.extend(node.text for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "loc" and node.text)
                        except ET.ParseError as exc:
                            raise CrawlBlocked("invalid_public_sitemap") from exc
                    if not links:
                        raise CrawlBlocked("query_mapping_required")
                    result["message"] = "query_bound_public_seed_research"
                else:
                    result["message"] = "public_search_query_discovery"
                # Public search commonly returns catalog cards before used listings.
                links.sort(key=lambda url: 0 if "/used/" in url else 1)
            elif source == "ebay_us" and self.ebay_browse_urls:
                # Exact publisher-facing browse pages are selected by an operator,
                # never synthesized from a query or used to bypass a denied /sch.
                # Read only collector/name-grounded item anchors, at most three.
                grounded = (len(query_context["numbers"]) == 1 or
                            (query_context["sets"] and len(query_context["bare_numbers"]) == 1))
                if not grounded or _seed_name_grounded(query, ""):
                    raise CrawlBlocked("query_mapping_required")
                for browse in self.ebay_browse_urls:
                    base, body = self._page(browse, source, "browse")
                    page = _Page(body)
                    if page.login:
                        raise CrawlBlocked("login_required")
                    for href, title in page.anchors[:2000]:
                        if not _query_matches(query_context, title) or not _seed_name_grounded(query, title):
                            continue
                        try:
                            link = ebay_listing_anchor(urljoin(base, href))
                            link, _ = _url(link, source=source)
                        except (ValueError, TypeError):
                            continue
                        if link not in links:
                            links.append(link)
                        if len(links) >= 3:
                            break
                    if len(links) >= 3:
                        break
                result["message"] = "query_bound_public_browse_research"
            else:
                base = ("https://jp.mercari.com/search?" + urlencode({"keyword": query.strip()}) if source == "mercari"
                        else "https://www.ebay.com/sch/i.html?" + urlencode({"_nkw": query.strip()}))
                base, body = self._page(base, source, "search")
                page = _Page(body)
                if page.login:
                    raise CrawlBlocked("login_required")
                links = [urljoin(base, link) for link in page.links]
                valid_links = []
                for link in links:
                    try:
                        valid_links.append(_url(link, source=source)[0])
                    except (ValueError, TypeError):
                        pass
                grounded = (len(query_context["numbers"]) == 1 or
                            (query_context["sets"] and len(query_context["bare_numbers"]) == 1))
                if source == "mercari" and not valid_links and grounded:
                    hints = preload_product_urls(page.inline_scripts)
                    if hints:
                        links = valid_links = list(hints)
                        mercari_preload = True
                        result["message"] = "public_primary_image_preload"
                if source == "mercari" and not valid_links and self.renderer is not None:
                    try:
                        base, rendered = self._page(base, source, "search", fetcher=self.renderer)
                        page = _Page(rendered)
                        if page.login:
                            raise CrawlBlocked("login_required")
                        links = [urljoin(base, link) for link in page.links]
                        result["message"] = "public_html_research_rendered"
                    except Exception as exc:
                        known = {"browser_renderer_disabled", "browser_renderer_unavailable", "browser_renderer_timeout",
                                 "browser_renderer_invalid_response", "browser_renderer_dns_unavailable",
                                 "browser_renderer_navigation_timeout", "browser_renderer_navigation_failed",
                                 "browser_renderer_source_unavailable", "browser_renderer_challenge",
                                 "browser_renderer_no_listing_links", "browser_renderer_request_budget_exhausted",
                                 "browser_renderer_deadline_exhausted", "browser_renderer_response_too_large",
                                 "browser_renderer_failed"}
                        code = str(exc) if isinstance(exc, CrawlBlocked) and str(exc) in known else "public_renderer_failed"
                        if code in known:
                            # The optional browser transport owns a closed numeric
                            # vocabulary. Never return arbitrary exception details.
                            from .marketplace_browser import _diagnostics
                            try:
                                diagnostic = _diagnostics(getattr(exc, "diagnostics", None))
                            except CrawlBlocked:
                                diagnostic, code = None, "browser_renderer_invalid_response"
                            if diagnostic is not None:
                                result["diagnostics"] = dict(diagnostic)
                        raise CrawlBlocked(code) from exc
            seen = set()
            queue = links[:2000]
            while queue and len(seen) < 20:
                link = queue.pop(0)
                try:
                    url, _ = _url(link, source=source)
                except (ValueError, TypeError):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                try:
                    row = self._detail(url)
                    if not _query_matches(query_context, row["title"]):
                        continue
                    if source == "snkrdunk" and seed_fallback and not _seed_name_grounded(query, row["title"]):
                        continue
                    if source == "ebay_us" and self.ebay_browse_urls and not _seed_name_grounded(query, row["title"]):
                        continue
                    if source == "mercari" and mercari_preload and not _seed_name_grounded(query, row["title"]):
                        continue
                    if source == "snkrdunk" and row["scope"] == "product_summary":
                        page = _Page(self._html_cache[url][1])
                        parent = urlsplit(url).path + "/used/"
                        children = [urljoin(url, href) for href in page.links
                                    if urlsplit(urljoin(url, href)).path.startswith(parent)]
                        if children:
                            result["product_summaries"].append(row)
                            queue = children[:20] + queue
                            continue
                    row["query_match_basis"] = ("collector_context" if query_context["numbers"] or query_context["sets"]
                                                else "public_search_query_identity_unverified")
                    row["name_match_status"] = ("recognized_character_context" if query_context["characters"]
                                                and query_context["characters"] == _named_characters(row["title"])
                                                else "identity_unverified")
                    result["listings"].append(row)
                    result["candidates"].append({"source": source, "url": url, "scope": row["scope"]})
                except (CrawlBlocked, OSError, TimeoutError) as exc:
                    result["errors"].append({"url": url, "message": str(exc)[:160]})
                if len(result["candidates"]) >= limit:
                    break
            if result["errors"]:
                result["status"], result["message"] = "partial", "some_public_pages_unavailable"
            elif not result["candidates"]:
                result["status"], result["message"] = "blocked", (
                    "query_mapping_required" if source == "snkrdunk" else
                    "public_browse_has_no_matching_listing_links" if source == "ebay_us" and self.ebay_browse_urls
                    else "public_search_has_no_listing_links")
        except (CrawlBlocked, OSError, TimeoutError) as exc:
            result["status"], result["message"] = "blocked", str(exc)[:160]
        return result

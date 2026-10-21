# Public listing research and forwarder handoff

The standalone commerce sidecar supports the agent's card-detail panel and an independent manual research page. It discovers marketplace product URLs, reads current seller asking prices and seller grade claims, binds an explicit selection, and refreshes the same listing before preparing a forwarder handoff. It does not write the catalog, approve identity, verify PSA certificates, place orders or take payment.

## Run locally

Use Python 3.11+ from this source checkout. Set a fresh server-only token of 24–1024 printable ASCII characters without spaces; supply it to both the sidecar and frontend. Do not use a `NEXT_PUBLIC_` variable.

```sh
export POKEMON_COMMERCE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 -m pokemon_index.commerce_service --allow-live-crawl --browser-renderer \
  --source mercari --source snkrdunk --source ebay_us --port 8767
```

Mercari search needs an operator-installed Node Playwright runtime and Chromium/Chrome. `NODE_PATH` may point to that runtime; this service never downloads it automatically. The renderer uses a new browser context, public DNS pinning, an exact host/path/method allowlist and bounded requests. The existing catalog Docker image is not a browser deployment package.

SNKRDUNK discovery uses its public HTML search form (`/search?keywords=…`), then individual used-listing pages. No seed is necessary. Optional `--snkr-seed-url` and `--snkr-sitemap-url` are restricted fallbacks: the query's card number/set and named context must be grounded in the detail title. Search results remain unverified candidates. Product summaries and individual listing asks stay separate. Public stock signals that do not establish availability remain `unknown`.

eBay has an adapter, but its public automated search was blocked by robots policy in the bounded live validation. That failure is displayed alongside successful source results. This implementation does not bypass it; a permitted API/feed is needed for complete eBay coverage.

The frontend calls the sidecar from its server using `POKEMON_COMMERCE_URL=http://127.0.0.1:8767` and the shared token. The proxy supplies the owner derived from its validated browser session. The sidecar binds only to loopback and rejects direct browser-origin requests. A bearer token and `X-Commerce-Owner` are required even for `/commerce/health`.

## Operations

- `POST /commerce/research`: `card_id`, `query`, optional `platforms` and exact `product_urls`. Three marketplaces and three inspected candidates per search keep the interactive path bounded. Each source returns its status independently.
- `POST /commerce/select`: `card_id`, `offer_id`, `expected_observed_at`, `expected_price_minor`, `currency`. The temporary selection is owner-bound and expires.
- `POST /commerce/handoff`: `selection_id`, `forwarder` (`buyship` or `other`), `destination` (`country`, optional `state`). The exact page is fetched again. Price, grade, certificate claim, condition, URL or availability changes invalidate the selection.

Unknown stock can produce a clearly labelled **manual URL handoff**. A provider quote requires an exact, priced listing with confirmed available stock. A delayed quote cannot outlive the refreshed evidence or selection.

The optional `--allow-live-buyship --quote-db <existing operator DB>` path uses the existing indexed approval and BNS resolve/quote adapter, with server-owned `BNS_PARTNER_BASE_URL`, `BNS_PARTNER_CLIENT_ID` and `BNS_PARTNER_CLIENT_SECRET`. Candidate research alone cannot satisfy indexed approval. This integration was tested with injected providers; no live BNS or PSA call was made. There is no order/payment endpoint. Without a configured provider, the UI prepares the exact URL for manual entry into Buy & Ship or another forwarder and shows no shipping total.

For an entirely offline walkthrough, use `--fixture` instead of live flags. Fixtures use reserved `.invalid` URLs. Fixture and live modes cannot be mixed and are visibly distinguished by the frontend.

## Frontend integration

The matching frontend changes are a separate patch against the byte-verified deployed 206-file source package, archive SHA256 `2c3eade060e7bdd3384e0048d9a60f26b135c69ecbf330e9b7915663872df322`. They add the commerce panel to the existing card view, a protected `/commerce/[operation]` server proxy, and local `/creator/pokemon-collector/research` mode for research without private catalog authentication. The frontend patch must be applied to that source baseline before a joint deployment is considered; this backend PR does not publish the UI.

## Offline validation

```sh
python3 -m unittest tests.test_marketplace_sources tests.test_marketplace_crawl tests.test_marketplace_browser tests.test_commerce_loop tests.test_commerce_service -q
node --test integrations/browser/renderPublicPage.test.cjs
```

These tests use fixtures/injected transports and loopback listeners. CI does not crawl marketplaces or call BNS/PSA. The new modules are outside the frozen catalog runtime source list. Release pin scripts and all 34 frozen runtime files remain unchanged.

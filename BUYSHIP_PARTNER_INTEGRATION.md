# Buy&Ship partner v1: URL-to-quote integration

Reviewed against the partner's `api-for-partners (5).md` overview supplied by the user. This is an implementation note, not a copy of the private API document.

## Supported shape

The partner API takes one product URL and resolves a product, one or more variants, availability and a native-currency price. A quote rechecks the merchant's live price and availability and returns a binding landed total, item price, local shipping, international shipping, duties and Buy&Ship service fee. The quote lasts about 15 minutes. Phase 1 accepts one item, quantity one, and US or HK destinations. A later order call accepts the quote ID and a delivery address, but payment, buyer confirmation and settlement are not described in this overview.

This is a checkout and landed-cost path, **not a listing search or catalog feed**. A marketplace listing URL must arrive from a separately authorized source. The legacy Mercari gateway is a separate contract and credential path. A partner quote is not a market-wide price observation, a paid sale or a source-native clearing price.

## Implemented preview

`pokemon_index.buyship_partner` provides a server-side OAuth client for resolve and quote, plus an offline fixture client. It has no order-creation method. The preview requires a fresh on-sale listing already resolved to an exact priceable unit and a source policy with `partner_handoff_allowed=true`. It rejects a changed product URL, multiple variants without an explicit key, unavailable variants, mismatched quote item, expired quote, destination/currency mismatch and non-reconciling totals. It returns source ask and timestamp separately from Buy&Ship's live quote, flags a native-price difference at resolve, and leaves `purchasable=false` and `purchase_action=null`.

The CLI intentionally exposes **only the fixture client**. A synthetic end-to-end demonstration is:

```bash
python3 -m pokemon_index --db /tmp/pokemon-buyship-demo.sqlite3 init
python3 -m pokemon_index --db /tmp/pokemon-buyship-demo.sqlite3 register-source examples/sources.jsonl
python3 -m pokemon_index --db /tmp/pokemon-buyship-demo.sqlite3 import-cards examples/cards.jsonl
python3 -m pokemon_index --db /tmp/pokemon-buyship-demo.sqlite3 import-observations examples/observations.jsonl
python3 -m pokemon_index --db /tmp/pokemon-buyship-demo.sqlite3 preview-buyship-fixture \
  examples/buyship_partner_preview.json ja:SV2A:173/165:standard \
  'ja:SV2A:173/165:standard|RAW|raw|a' licensed_fixture demo-2 \
  --destination HK --as-of 2026-09-22T09:05:00Z
```

The example uses the existing `licensed_fixture` source and `example.invalid` URL. It sends no request, creates no order and proves nothing about whether Buy&Ship supports a real marketplace.

For a price-only recommendation across two synthetic listings linked to the **same indexed card unit**, run `preview-buyship-shortlist examples/buyship_partner_shortlist.json` against the same initialized demo database. The lower delivered total is selected; seller reliability, card authenticity and image-based condition are not scored.

Adding `--store` to that command imports both synthetic quotes atomically into the existing landed-quote index and returns its price-only recommendation. This requires an additional source policy permission, `partner_quote_store_allowed=true`; it defaults to false for existing and real sources. The import binds the quote to the exact listing observation, URL, unit, partner reference, variant and expiry. Buy&Ship's five cost lines map to the index's existing landed-cost components; insurance, FX spread and other are zero because the binding grand total has no separate lines for them. A later listing observation invalidates the old quote for recommendations, even before its nominal expiry. Only the synthetic fixture source currently enables this storage permission. No raw partner response, product image or delivery address is stored.

Disabling quote storage permission removes stored Buy&Ship partner quotes for that source; ordinary source quotes are unaffected.

## Partner decisions before live use

1. Provide sandbox and production base URLs, client credentials, rate limits, timeout/retry guidance and an OpenAPI or equivalent detailed schema.
2. Confirm supported listing URL patterns for Mercari, Yahoo Japan, SNKRDUNK and eBay, including seller-scoped listings, graded cards and secondhand condition variants. Confirm how redirects and canonical URL changes should be interpreted.
3. Explain payment authorization, buyer confirmation, order expiration, cancellation, refunds, fulfillment failures and whether there is a hosted checkout or webhook. The overview's order `CREATED` response is not proof of payment or merchant purchase.
4. Confirm permission to submit each marketplace's listing URL to Buy&Ship, show returned product and quote details, retain quote history, and use photos in AI-based identity or condition checks.
5. Provide a separate listing search/catalog/feed or current legacy gateway contract with per-source data rights. Without that, our product can quote only URLs obtained elsewhere.

Until these are answered, the adapter stays an internal preview. Real order creation and a buyer-facing `purchase_action` remain disabled.

## 20 October offline handoff hardening

The source/access audit and ranked gaps are in [LIVE_C2C_BNS_QUOTE_AUDIT.md](LIVE_C2C_BNS_QUOTE_AUDIT.md).
The preview now fingerprints the current listing, exact observation, catalog
identity and source policy, and rechecks that binding after resolve and quote.
It refuses an active caller transaction, which could otherwise hide concurrent
updates, and refuses a historical clock that hides a newer observation. Explicit
card-number/grade contradictions in partner names are rejected; generic partner
names still do not prove card identity or authenticity.

Returned `evidence` includes observation, source snapshot, resolve-response,
quote-response and combined binding SHA-256 values. These are reproducibility
identifiers, not signed provider attestations. Source `listing.ask` remains
separate from `buyship.resolve_price` and the destination-currency quote.
`buyer_labels` says `raw, condition not assessed` or, for example,
`seller says PSA 10, certificate not verified`. Physical inspection, certificate
and authenticity verification remain false; real verified PSA inventory is 0.

`PartnerClient` defaults to denying its network transport; a future explicitly
authorized operator must set `live_authorized=True` in addition to satisfying
all source policies and access requirements. No live CLI was added. Injected
test senders are labelled as test transport. TLS verification remains enabled.

`FixturePartnerClient` accepts only a database whose listings use synthetic
fixture source names and `.invalid` hosts, including checks after each response.
Use a disposable fixture database. The safest new demonstration opens only an
in-memory database, denies socket connections and stores no quotes:

```bash
python3 -m scripts.rehearse_c2c_bns_quote --output /tmp/c2c-bns-offline.json
```

The historical CLI examples above remain preview-only. Old `--store` examples
now correctly refuse already expired quotes using the current clock. Unit
tests may supply `now=` directly to persistence/ranking only for isolated
synthetic fixtures; no live quote can be revived with a fixture clock. Storage
validates freshness, permissions, evidence and labels under an atomic SQLite
write lock. Database-backed ranking revalidates the current snapshot; stateless
ranking alone is not a current-inventory check.

No scheduler, source connector, PSA patch, order, payment, inspection or returns
implementation was added. All real source/handoff permissions remain pending.

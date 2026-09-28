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

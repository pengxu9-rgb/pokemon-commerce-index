# SNKRDUNK data partnership request

We have an independent Japanese Pokémon card identity index. We would like to map its set code, collector number and printing to SNKRDUNK's product pages, then offer users current listings and comparable prices by card condition and grading tier. The catalog does not need to come from SNKRDUNK.

SNKRDUNK's [current terms, Article 7(1)(13)](https://snkrdunk.com/terms) prohibit crawling and scraping. A public page or user account is not authorization for automated extraction. Please provide a written data agreement and an approved feed or API before we ingest listings or prices.

## Minimum feed and semantics

| Area | Requested fields or decision |
| --- | --- |
| Product identity | Stable SNKRDUNK product ID; product URL; set code; collector number; card name; rarity; printing or finish; language; sealed item versus single card |
| Offer identity | Stable listing ID; product ID; active/removed/sold state; first seen and updated timestamps; quantity; seller ID only if authorized |
| Price | JPY item ask; fees and tax inclusion; condition A–D; grading company and exact grade; whether a product-page “from” price is the minimum across all tiers |
| History | Whether closed listings, accepted offer amount and actual paid amount are available; cancellation and relist semantics |
| Operations | Bulk export or documented API; pagination; daily quota; permitted polling rate; update latency; change feed or webhooks; error and deletion handling |

## Rights to confirm separately

1. Internal storage of product IDs, listing IDs, titles, prices and timestamps; retention period and deletion requests.
2. Public display of current listing links, prices, condition and source attribution; image and text rights separately.
3. Per-card ask statistics and price history, including sample counts and freshness.
4. Comparison with other authorized marketplaces and Buy&Ship landed-cost quotes.
5. Human review and machine classification of product and listing metadata; any limits on third-party AI processing.
6. Use and display of sold status versus verified paid amounts; seller-level analysis if separately permitted.

For a pilot, a daily file containing approximately 50 agreed card products with live offer rows and tier definitions is enough. We can provide our card IDs and mapping review results. We will leave SNKRDUNK price ingestion disabled until the approved delivery method and rights are documented.

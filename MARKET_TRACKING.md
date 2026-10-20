# Independent marketplace price tracking

The operator tracker ingests saved Mercari, eBay and SNKRDUNK listing captures and returns per-card native asking prices, listing histories and unverified quality claims. It has no BNS dependency, HTTP route, live fetcher, credentials or order/payment operation. The source adapters, atomic ingestion and report are implemented and testable offline; ongoing marketplace collection still needs separately authorized producers and current source contracts.

## Source adapters

| Source ID | Payload schema | Input |
| --- | --- | --- |
| `mercari` | `pokemon.mercari-authorized-export.v1` | Project-owned export contract for individual fixed-price listings; independent of the legacy BNS gateway. |
| `ebay_us` | `ebay.browse.search.v1` or `ebay.browse.item.v1` | Saved native Browse search or item-detail response. Fixed-price USD listings remain subject to the existing photo-resolution gate. |
| `snkrdunk` | `pokemon.snkrdunk-authorized-export.v1` | Project-owned export contract for individual fixed-price listings, separate from product/tier floors. |

Mercari/SNKRDUNK export schemas are **our ingestion contracts**, not assertions about undocumented marketplace endpoints. A future authorized API/feed/browser producer must map its actual source data to this contract. No guessed private endpoints or automated browser extraction are included. Source permissions must independently cover ingestion, retention, display, statistics and cross-source use. Existing real source policies remain disabled; no source is granted rights by running the tracker.

Each source also has a `_fixture` variant accepting only `.invalid` listing URLs. Real adapters accept only canonical marketplace domains. Fixture and real inventories cannot share an import database. The three saved examples in [examples/marketplace_tracking](examples/marketplace_tracking/) contain synthetic data and historical timestamps; they establish no real listings or access. Use the disposable rehearsal for a current synthetic demonstration.

## Capture contract

Every saved JSON capture has exactly these envelope fields:

```json
{
  "schema": "pokemon.marketplace-capture.v1",
  "source": "mercari_fixture",
  "observed_at": "2026-10-20T12:00:00Z",
  "request": {
    "kind": "export",
    "target_card_ids": ["ja:SV2A:173/165:standard"]
  },
  "payload_schema": "pokemon.mercari-authorized-export.v1",
  "payload": {
    "listings": [{
      "listing_id": "m1001",
      "title": "ピカチュウ SV2a 173/165 PSA10 鑑定品",
      "language": "ja",
      "url": "https://mercari.example.invalid/item/m1001",
      "status": "on_sale",
      "price": {"amount_minor": 12000, "currency": "JPY"},
      "seller_condition": "seller says graded",
      "grade_company": "PSA",
      "grade_value": "10",
      "certificate_number_claim": "SYNTHETIC-0001"
    }],
    "page_complete": true
  }
}
```

Requests accept only `kind` (`search`, `detail`, `export`), optional `query`, positive integer `page`, and bounded `native_ids`, `product_ids`, `target_card_ids` arrays. These coordinates describe the captured request; target IDs never assign listings to cards. Auth fields and arbitrary URLs are not accepted as request coordinates. Never include credentials or tokens in captures.

Mercari/SNKRDUNK export payloads contain `listings`, optional `next_cursor` and boolean `page_complete`. Rows require stable `listing_id`, title, HTTPS URL, status and explicit native price. Supported statuses are `on_sale`, `trading`, `sold_out`, `gone`. A terminal row may have `price=null` with an explicit `currency`; this is not a paid-sale amount. Optional fields are `seller_id`, canonical `language`, `seller_condition`, `grade_company`, `grade_value`, `certificate_number_claim`. `record_type`, when supplied, must be `listing`; `sale_type` must be `fixed_price`. Auctions and product/tier summaries are rejected. Language is never inferred from marketplace location.

`amount_minor` is a nonnegative integer in the source contract's native minor units: the supplied JPY examples remain yen integers, while eBay USD decimal strings become exact cents. No blanket multiplication by 100 is applied to JPY exports. Invalid precision, floats/booleans where exact money is required, overflow and mixed price fields fail validation. Captures are limited to 2 MB and 100 rows; duplicate listing IDs/object keys, nonfinite JSON and unknown schema envelopes are rejected.

An empty search capture records coverage without changing existing listing statuses. Disappearance is never inferred as sold. Cursor/page metadata records that page only, not completeness of a marketplace or a card's inventory. Raw payloads are not retained in the database: observations, filtered seller claims, request/coverage metadata and SHA-256 references are retained under the source's policy. Hashes are reproducibility identifiers, not provider attestations.

Saved eBay responses with ended listings or explicit unavailable/unknown stock evidence are rejected instead of refreshing an active ask. These refusals do not infer a paid sale or silently delete an older observation; the previous observation retains its original timestamp and expires under its TTL. A separately confirmed terminal-state contract is needed before automating those transitions from a future eBay collector.

## Atomic state and quality evidence

`marketplace_ingest.initialize` explicitly prepares the existing worker tables plus `marketplace_capture` and `marketplace_observation_quality`. Imports own `BEGIN IMMEDIATE` and commit observations, immutable worker receipts, exact-observation seller claims, resolution demotions and capture coverage together. A conflicting replay or failed quality insert rolls the whole import back. Exact replay is idempotent and preserves a review performed after the original import. A new observation that needs grade/photo review invalidates an older human binding instead of silently retaining its old RAW/PSA bucket.

Quality evidence is keyed by source, listing ID and observation timestamp, with an evidence reference equal to the observation's. Structured grader/grade claims can support a reviewed unit but cannot override contradictory title or condition text. Title-extracted metadata cannot masquerade as independent structured evidence. Raw cards, different grades, finishes, languages and condition buckets stay separate. The tracker rejects unreadable slab/grader cues in a previously bound RAW listing.

Outputs say **seller says PSA 10; certificate not verified**, or **raw; condition not assessed**. A certificate number is a seller claim. Certificate, authenticity, physical inspection and physical-condition verification remain false; no PSA calls or AI image-grade inference are added. Source condition text is preserved without inventing a mapping between platform tiers. RAW/unknown medians provide asking-price context across unassessed condition claims, not a comparison of verified physical quality. Existing external PSA certificate-matching/deduplication work is not recreated.

## Local operation

Create an empty local operator database, or prepare an existing isolated operator copy that already has the base catalog schema:

```bash
python3 -m scripts.market_tracker --db /tmp/market-operator.sqlite3 init
# For an existing operator database instead:
python3 -m scripts.market_tracker --db /path/to/operator.sqlite3 prepare
```

`init` refuses an existing path. `prepare` adds state tables without granting source rights or changing catalog identities. Register approved source policies and import the reviewed catalog using the existing operator commands. Then replay authorized local captures and read one card:

```bash
python3 -m scripts.market_tracker --db /path/to/operator.sqlite3 replay /path/to/capture.json
python3 -m scripts.market_tracker --db /path/to/operator.sqlite3 report \
  'ja:SV2A:173/165:standard' --source mercari --source ebay_us --source snkrdunk
python3 -m scripts.market_tracker --db /path/to/operator.sqlite3 purge
```

Every command denies DNS/socket connections. There is no live switch. Real imports use the current clock; an old capture cannot be revived with a supplied historical clock. `purge` uses existing source retention, cascades quality deletion with its observation, and removes old capture metadata. Approved collection producers can later feed the existing bounded worker; no recurring scheduler or source transport is enabled here.

Reports open a fresh read-only/query-only transaction, so an existing caller cursor cannot hide committed revocations. They return separate platform × currency × exact-unit groups with current listing count, minimum, exact decimal-string median, URLs, timestamps, claim evidence and bounded timelines. Listing counts count distinct source/listing IDs, not polls or verified physical copies; cross-platform slab deduplication remains unavailable. Native currencies are never pooled or silently converted, and landed costs remain unknown.

Stale, terminal, held, unresolved, conflicting or rights-blocked offers do not contribute current asks. Historical unit attribution uses resolution-record effective timestamps and each observation's own quality/photo evidence; it never backdates a later human override or asserts actual system knowledge time. Declared card-target capture coverage is shown separately from inventory and stays `live_collection_verified=false`. A source with no observed eligible ask is not represented as a successful empty live search. Reports are bounded to 500 scoped listings, 10,000 events and 1–30 history days, additionally limited by source retention.

## Validation and release boundary

```bash
python3 -m unittest discover -s tests -p 'test_market*.py' -v
python3 -m scripts.rehearse_market_tracking --output /tmp/market-rehearsal.json
```

Tests deny sockets and cover all three adapter-to-importer-to-report paths, money precision, exact units/currencies, observation/grade changes, historical attribution, immutable replay/rollback, retention, rights revocation, fresh validation connections and fixture isolation. The synthetic rehearsal creates a disposable database with three platforms, RAW/PSA9/PSA10, repeated observations, edits and stale/sold/withdrawn listings; no quotes, paid-sale records or purchases are created. eBay captured claims remain unresolved until the existing photo gate is satisfied.

This operator implementation adds no collector HTTP route and changes none of `collector_journey.RUNTIME_SOURCES` or the four release-pin scripts. It does not establish live marketplace coverage, enable collection, merge or deploy anything.

# Live C2C offers → Buy & Ship quote: audit and offline build plan

Audit date: 20 October 2026. Base: `claude/grade-integrity-20261020`,
`e502473bbaa34d5b25b7cc0ddfa15e08cef3f83f` (PR #16 still open when checked).
The owner's existing checkout and its uncommitted release pins are excluded.
This audit used repository files only; GitHub was contacted to check PR state.
No marketplace, BNS, PSA, image service or other source endpoint was contacted.
File:line references in the audit sections below refer to that base commit;
the implementation receipt at the end describes the completed changes.
The implementation is now rebased onto PR #16 head
`6399f790f3eca97cbff208faf6bb687ac40ac58c`, inheriting Claude Code's four reviewed
release-pin updates unchanged. The audit's original code references still apply
because that follow-up changed only the pins and backend note.

## Finding

The catalog is an identity index, not an enabled C2C crawler. The existing
partner preview already implements eligible offer → product URL → BNS resolve
→ BNS live-price/availability recheck and landed quote. BNS's partner API is
URL-in, not discovery (`BUYSHIP_PARTNER_INTEGRATION.md:7-11`). We can own listing
discovery and refresh once authorized; browser automation would not confer
collection or redistribution rights. Today's real-source access remains closed.

## Discovery and authorization

These are repository-recorded states, not new legal determinations or claims
that an application was submitted. No source permissions were changed.

| Source | URL-producing code today | Status and missing authority |
| --- | --- | --- |
| Mercari | Legacy BNS gateway search/item/batch normalizer constructs `https://jp.mercari.com/item/{id}`; Gate 0 permits at most three probes (`pokemon_index/buyship_mercari.py:24-25,34-74,138-180,196-214`). | **Requested/pending; live blocked.** Current contract, credentials, quotas, source-specific collection/storage/display/handoff scope and owner go-ahead required. Request packet exists; submission/approval not evidenced (`SOURCE_ACCESS_REQUEST.md:5,11-18,22-38`). Legacy HMAC opt-in is not production approval. |
| Yahoo! Auctions | No maintained Yahoo adapter in this repository. A request packet asks BNS for search/detail access. | **Requested/pending; live blocked.** No direct Auctions public-key route in the recorded assessment; obtain a specific partner feed (`API_ACCESS_APPLICATIONS.md:13-23`). Auction bids are not fixed purchase prices. |
| Yahoo! Flea Market | No adapter, documented current response contract, approved policy or authorized feed. | **Blocked pending explicit source scope.** Do not treat Auctions, Shopping and Flea Market as interchangeable APIs. Request separate listing IDs, URLs, status, prices and rights. |
| SNKRDUNK | No enabled listing connector. A prepared partnership request describes a product-and-listing feed. | **Scraping blocked; partner access requested/pending.** Repository assessment records an explicit scraping prohibition (`SNKRDUNK_ACCESS_REQUEST.md:5-7`). Product-page minimum prices cannot substitute for individual condition/grade-scoped offers (`SNKRDUNK_ACCESS_REQUEST.md:11-15`). |
| eBay | Offline Browse fixed-price normalizer emits `itemWebUrl` and unresolved observations; bounded search probe (`pokemon_index/ebay_browse.py:48-94,128-188`). | **Requested/pending; production blocked.** Production approval and the specific data-use scope are separate gates. No live eBay work is authorized here. Pending policy disables ingestion/display/AI; title-only resolution stays closed (`EBAY_ACCESS_AND_PILOT.md:7-9,27-37`, `examples/ebay_source_policy_pending.jsonl:1`). |
| Synthetic fixtures | `licensed_fixture` and `example.invalid` in examples. | **Authorized for isolated offline tests only**, never evidence of real inventory or a live quote (`examples/sources.jsonl:1`, `BUYSHIP_PARTNER_INTEGRATION.md:28-32`). |

`listing_candidates.retrieve` searches the local identity catalog for photo
review candidates, including match-disabled identities. It neither discovers
marketplace listings nor grants price matching (`pokemon_index/listing_candidates.py:1-5,43-49,85-100`).

## Freshness and ingestion

- `listing` stores identity, URL, seller, first/last seen and current ask/status;
  `observation` stores timestamped title, URL, currency, ask, evidence and poll
  reason (`pokemon_index/schema.sql:427-458`). Latest observation drives offer
  state; stale arrivals do not replace newest title/URL/status/ask
  (`pokemon_index/core.py:1375-1437`, PR #16).
- Poll reasons are `discovery`, `tracking`, `panel`, `auction_end`; statuses are
  `on_sale`, `trading`, `sold_out`, `gone`. A terminal observation removes an
  offer; search nonappearance is not proof of sale. Mercari's legacy adapter
  currently accepts only the first three statuses, so authorized deletion or
  withdrawal semantics still need a contract (`pokemon_index/core.py:19,1382-1386`,
  `pokemon_index/buyship_mercari.py:25,44-46,77-99`).
- `offers` uses the most recent observation at the requested time, accepts only
  on-sale rows, requires display rights/photo approval and excludes rows older
  than the source's `listing_ttl_hours` (`pokemon_index/core.py:1629-1667`).
  eBay TTL is capped at six hours (`pokemon_index/core.py:500-501`). A TTL is a
  freshness limit, not a guarantee of availability through purchase.
- The bounded worker has immutable receipts, atomic ingestion/job completion,
  daily call budgets including retries, leases, exponential retry and monitoring,
  but no enabled connector or scheduler (`pokemon_index/ingestion_worker.py:1-5,22-35,58-98,101-160`).
  Its discovery-coordinate envelope does not yet carry explicit poll reasons,
  endpoint/cursor semantics or request IDs (`pokemon_index/ingestion_worker.py:38-55`).
- The direct observation importer uses `INSERT OR IGNORE` for a duplicate
  timestamp; it is not an immutable conflict detector. The worker adds that
  protection. Quote binding must therefore fingerprint both the observation and
  current listing row, including evidence, and recheck them during the request.
- Add an owner-authorized scheduler with per-source quotas/concurrency and
  backoff; deduplicated discovery pagination/cursors; hot-listing detail refresh
  before selection; explicit status updates; retention/deletion jobs and stale
  age/error/coverage monitoring. Schedule `purge`, which already removes source
  evidence by retention (`pokemon_index/ingestion_worker.py:163-172`,
  `pokemon_index/core.py:1871-1913`). No cadence can be promised before quotas
  and source latency are known.
- Shipping payer/local shipping fields, full request/run provenance, live
  native-currency precision examples and a currently approved listing feed are
  still missing from the legacy observation adapter. Preserve unknown costs;
  confirm whether legacy JPY `price` is already minor units before live use
  (`pokemon_index/buyship_mercari.py:50-74`, `OFFER_CONDITION_CONTRACT.md:9-21`).

## Identity and grade eligibility

Only a current, display-permitted offer for an exact, match-eligible card and
priceable unit may be forwarded. Existing title rules distinguish set, number,
language, finish and grade, reject ambiguous bundles and aspirational/former
grades, and leave slabs without a readable grade unresolved
(`pokemon_index/core.py:1241-1360`). PR #16 demotes title-derived bindings when
newest text no longer supports them and refuses unit switches without review
(`pokemon_index/core.py:1391-1437`). eBay/photo-gated sources need exact
observation-bound visual approval (`pokemon_index/core.py:1654-1656,1691-1696`).

Grader and grade are **seller claims**. No PSA certificate lookup, physical-copy
verification or cross-seller slab deduplication is implemented in this path.
`collector_inventory` explicitly reports physical verification false and no
live offers (`pokemon_index/collector_inventory.py:64-74,93-101`). Real verified
PSA inventory supported by this repository: **0**. This is not a count of all
seller-claimed PSA listings. Do not recreate the pending cloud PSA patch.

Buyer labels must say “seller says PSA 10, certificate not verified” (or the
actual grader/grade), or “raw, condition not assessed.” An imported raw condition
bucket does not establish physical condition. Authentication and inspection
remain unverified. Missing grade/slab identity produces refusal, not a raw quote.

## Quote binding and evidence

The v1 contract resolves URL → reference/variants/native price/availability;
quote selects reference + variant + quantity one + destination, rechecks the
merchant and returns an OPEN quote, expiry, currency, item and five cost lines
(`pokemon_index/buyship_partner.py:106-117,168-275`). Quote expiry is authoritative;
the overview's approximately 15 minutes is not a hardcoded validity period.

Already implemented: handoff permission, source TTL/exact unit eligibility,
HTTPS/same URL, explicit selection for multiple variants, stock, quote-item
identity, destination/currency/expiry and component arithmetic checks. Quote
storage has a distinct permission; later observations invalidate recommendation
eligibility (`pokemon_index/buyship_partner.py:323-394`,
`pokemon_index/core.py:1670-1683,1759-1773`). Source ask and BNS current price must
remain separately labelled; a refreshed price is not a catalog observation.

Gaps to close offline: observation evidence/fingerprint in the result; current
snapshot/permission checks after resolve and quote, including changes during
calls; final expiry/storage checks against current state rather than historical
quote time; unverified buyer labels; fixture isolation; explicit live-call gate.
Reject changed URLs/units/observations, ambiguous selection, unavailable items,
malformed/mismatched quotes and missing costs. A changed native price can be
shown with a discrepancy flag; it does not silently replace the source ask.

The partner contract does not provide independently verified PSA/card identity
or a merchant-content revision/lock. URL/reference/variant equality proves
binding to the reported listing, not physical authenticity or that the seller
cannot edit it. Retain this limitation in evidence; require partner clarification
before claiming a stronger guarantee. Hashes identify evidence, not signatures
or proof a provider call occurred.

## Responsibilities and boundaries

- Implemented: resolve, quote, validation, offline fixtures and optional,
  permission-gated landed-quote storage. No order method exists
  (`pokemon_index/buyship_partner.py:1-5,56-117`).
- Described only/unimplemented: BNS inspection/authentication, receiving
  evidence, return eligibility/cancellation/refunds, buyer payment/settlement,
  hosted checkout and order-status webhooks
  (`BUYSHIP_PARTNER_INTEGRATION.md:7,38-44`). Do not imply these are integrated.
- BNS is the intended merchant of record; Pivota holds no customer funds
  (`integrations/pivota/INTERNATIONAL_NEXT3000_BACKEND_NOTE.md:26,33`). Quote results
  keep `purchasable=false`, `purchase_action=null`, `order_created=false`.

## Ranked gaps blocking the first real quote

1. **Authorized listing URL and fresh observation:** approved Mercari route and
   data-use/handoff/display scope; no current approval evidenced. A gateway or
   browser login alone does not meet this requirement.
2. **BNS detailed contract/access plus explicit owner go-ahead:** approved URL
   support, native price precision, sandbox/base URL, credentials provisioned
   outside code, quotas, redirects and quote display/history scope. No live
   request is authorized by this handoff.
3. **Reliable observation refresh:** source connector and scheduler/detail refresh,
   status/deletion semantics, immutable evidence and operational monitoring.
4. **Fail-closed quote evidence and buyer labels:** build below using synthetic
   responses; this can be completed before any live access.
5. **Purchase/certificate/inspection capabilities:** separate later work; honest
   unverified labels permit a quote preview, but not a verified-slab claim or
   purchase/payment flow. Pending PSA export/account work remains external.

## Build plan (recorded before implementation)

1. Harden the existing preview rather than create a second partner integration:
   snapshot fingerprint and evidence, newest-title grade checks, revalidation
   after each partner step, strict quote validation and buyer labels.
2. Make network transport opt-in and keep CLI live access absent. Restrict
   synthetic client responses to synthetic `.invalid` listings in isolated
   fixture data. Add a disposable in-memory offline demonstration with no
   production database argument and no quote-storage side effects.
3. Test success and every new refusal, including source rights, stale/sold/gone,
   unresolved/contradictory grade, URL/variant/currency/fees/expiry mismatch,
   in-flight changes, storage drift and synthetic/real data mixing. Transport
   spies must prove rejected preflight requests make zero calls.
4. Run relevant ingestion/identity/quote tests and appropriate broader checks.
   Record source/data revisions and leave all four reviewed release pins
   untouched. Open a branch PR based on PR #16; no merge/deploy or live requests.

## Implementation receipt

Implemented in `pokemon_index/buyship_partner.py` and exercised by
`scripts/rehearse_c2c_bns_quote.py`:

- Snapshot/evidence binding covers exact card/unit, newest listing/observation,
  evidence reference and source policy. Every resolve/quote response is followed
  by a fresh eligibility/binding check. An active caller transaction, stale,
  unavailable, conflicting or match-disabled identity is refused.
- Newest-title grader/grade checks apply even to manually retained bindings.
  Explicit partner card-number/grade contradictions are rejected. Price changes
  remain visible as discrepancies and are not written into source observations.
- Quote response and request evidence hashes, expiry, cost lines and unverified
  buyer labels are returned. Inspection/certificate/authenticity remain false;
  real verified PSA inventory is 0. Hashes are not provider signatures.
- Missing fees, malformed money, boolean quantities, changed variants/options,
  wrong URLs/destinations/currencies, closed/expired quotes and changed evidence
  are refused. Persistence revalidates at the current time under a write lock;
  database-backed ranking also revalidates the snapshot.
- Default live transport is disabled without explicit operator authorization.
  Fixtures require exclusively synthetic `.invalid` listing data. The new
  rehearsal accepts no production database, denies socket connections, creates
  raw and seller-claimed PSA previews, and persists no quotes/recommendations.

Validation: **91 tests pass**, including 43 partner/rehearsal tests and existing
identity, ingestion, money, eBay, Mercari fixture and offer-comparison coverage.
Focused validation denies socket connections. A separate SQLite-connection
regression confirms a rights revocation during resolve is visible and prevents
the quote call. The rehearsal returns four fixture method calls, zero network
calls, zero stored quotes, no order and no purchase action.

Offline rebuilds of both frozen input manifests passed input hashing. No files
in `collector_journey.RUNTIME_SOURCES` changed from PR #16 head `6399f79`.
The resulting source/data revisions are recorded in
`integrations/pivota/INTERNATIONAL_NEXT3000_BACKEND_NOTE.md`. All four release-pin
scripts remain byte-for-byte unchanged from `6399f79`; their reviewed runtime
pins match the computed revisions. This quote patch neither changes those pins
nor weakens the existing release qualification checks.
The operator-only quote adapter is outside the existing collector runtime source
hash list; no collector HTTP route or frontend integration was added here.

The first real quote still needs the approvals/access and explicit owner
go-ahead ranked above. No claimed source authorization, actual quote or verified
PSA inventory was manufactured by this implementation.

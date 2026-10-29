# Live-offer pilot preparation

This build prepares the existing comparison → explicit selection → fresh detail
recheck → BNS variant choice → quote-review journey. It performs no activation,
source onboarding, credential provisioning, cloud mutation, order or payment.

The first milestone is 5–10 exact listings from one independently authorized
source. Start with an API when it covers the operation; use separately permitted
crawling for sources without supported API coverage. API errors, authentication
denial, budget exhaustion and empty results never trigger crawl fallback.
Every seller and native listing stays separate. Compare item asks in their native
currency within compatible printing/grade/condition groups. Destination-dependent
BNS totals are a second comparison layer. A quote is never treated as stock
reservation, payment authorization, or physical-card authentication.

## Configuration remains off

The existing private Pot beta deliberately requires live providers off. This
change does not loosen beta/authentication gates or repoint the creator release.
A live runtime needs a separately reviewed access boundary and private release;
changing the current beta's flags is not an activation procedure.

The standalone commerce service requires all of the following before a live
marketplace adapter can be constructed:

- `--approved-source-routing`, explicit `--source` and matching `--source-route`.
- Finite `--source-request-budget` and `--source-window-seconds` shared across
  actual HTTP requests, including API token and crawler robots requests.
- A per-source `--source-access-approval source=operator-record-reference`.
  This is an operator assertion referencing independently obtained authority; a
  CLI string does not grant access or prove a partner agreement.
- Existing API/crawl opt-ins and the adapter's own credentials, rights and bounds.
  eBay retains its production/display approval gates and 20-request maximum.
- Separate optional `--source-photo-display source=approval-reference` and
  `--source-partner-handoff source=approval-reference`. Read permission implies
  neither. Missing photo permission removes seller image URLs before responses;
  missing handoff permission prevents BNS calls for that source.
- Optional exact canonical `--source-listing-url` entries for direct onboarding.
  Browser-supplied arbitrary URLs cannot create this allowlist.

Legacy live flags alone now fail closed. There is no implicit Mercari/SNKRDUNK
allowlist. SNKRDUNK's published terms prohibit crawling/scraping (Article 7);
it requires separate permission or partner access and is not an approved pilot
source by this build. References: <https://snkrdunk.com/terms> and the official
eBay inventory guide <https://developer.ebay.com/develop/guides/buy/inventory-discovery-and-refresh-guide>.

`source_readiness` is safe metadata on guarded commerce results and health:
source, status (`not_configured`, `configured_offline`, `enabled`), method,
listing-read capability, photo-display authority, fixed blocker and message.
It never contains credentials, approval references, source URLs or policy bodies.
It reads current state without requests or counter consumption. Network capacity
and photo-display permission are independent: an exhausted session may retain
display authority for already captured photos, whereas source revocation removes
it. Seller-supplied photos remain unverified depictions, not proof of actual-copy
ownership or authenticity; no catalog artwork substitutes for a seller photo.

## Freshness and revocation

The router pins detail calls to the source method and listing identity that
produced discovery. Direct onboarding requires the server allowlist. Price,
seller, grading/identity or availability changes prevent use of the old selection.
Nonzero eBay variations never collapse into a parent listing; only `v1|id|0`
may bind the matching canonical numeric eBay URL for BNS preview.

`ApprovedSources.revoke(source)` is a server-only operation independent of the
adapter lock. Marketplace HTTP clients recheck source authority after connection
setup and immediately before sending each HTTP request, and recheck before
publishing the returned evidence. Existing transports retain bounded timeouts;
the common deadline cannot preempt in-flight DNS/TLS/socket work.

The existing BNS worker is one bounded authorized token/resolve/quote operation.
Per-source handoff authority is checked immediately before worker launch and
again for every outcome, including variant refusals, before anything is returned
or retained. Each worker HTTP request checks its own deadline. A parent revocation
cannot preempt an in-flight child request; it suppresses the returned result.
No claim of instantaneous cross-process cancellation is made.

## BNS and acceptance still needed

BNS must supply/confirm a sandbox base URL, secure credential reference, supported
card listing/merchant/destination and nonfulfillment test data. Confirm buyer
authorization, funding/payment, order idempotency and timeout reconciliation
semantics before implementing order creation. The current client still has no
order-creation method; previews always have `purchasable=false`,
`purchase_action=null`, and `order_created=false`.

Run the synthetic HTTP journey with `python3 -B -m tests.live_offer_rehearsal`.
It emits JSON only, exercises real loopback endpoints and source/BNS validators,
denies and audits external sockets/DNS, and proves explicit variant selection,
exact-listing quote binding, and changed/sold/seller-change refusal. Provider
responses, permissions, prices, photos and the trusted catalog are synthetic.
It does not prove source rights, live stock, BNS support, real authentication or
transaction completion. Focused regressions:
`python3 -B -m unittest tests.test_live_offer_pilot -q`.

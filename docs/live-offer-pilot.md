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

Browse search summaries are discovery hints only. Before publishing API offers,
the router retrieves exact details for each bounded hit through the same guarded
client, preserves source/native-ID/URL identity and uses only that detail response
as the selection baseline. Token, search and each detail consume request budgets.
Unavailable details, exhausted budgets or revocation publish no summary or partial
binding; API failure never triggers crawling. The rehearsal deliberately omits
grader, printing aspects and detailed stock from its search responses.

`ApprovedSources.revoke(source)` is a server-only operation independent of the
adapter lock. Marketplace HTTP clients recheck source authority after connection
setup and immediately before sending each HTTP request, and recheck before
publishing the returned evidence. Existing transports retain bounded timeouts;
the common deadline cannot preempt in-flight DNS/TLS/socket work.

The existing BNS worker is one bounded authorized token/resolve/quote operation.
Its private selected-offer binding retains available structured listing language,
set code, collector number, finish and edition claims. Explicit contradictions in
BNS resolve/quote names or the chosen variant options refuse the preview before
quote review. Raw and slab claims must also remain compatible. Missing dimensions
remain unknown; matching provider text never authenticates the printing, grade or
physical card. These private claims are not added to the public quote contract.
Common labelled fields and option aliases are checked together with their values.
Negative property booleans such as `First Edition=No` exclude the retained claim;
they do not invent an Unlimited edition or a different finish. Labelled canonical
values remain meaningful when followed by grade text. A collector numerator alone
does not supply a missing denominator. Grader readiness and scoped `not graded`
wording do not claim a slab, while separate explicit slab/grade evidence still
refuses a raw listing. This is bounded assertion parsing, not general language
understanding; absent and unsupported claims remain unverified.
Property booleans keep their polarity across ordinary wrappers, punctuation and
prose suffixes; those suffixes are checked independently. Company-specific
negations such as `not PSA graded` and `not graded by PSA` are compared with the
retained grader before their own text spans are masked. They contradict a PSA
slab claim, while remaining compatible with a raw claim or another named grader.
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
Printing and raw/slab contradiction regressions:
`python3 -B -m unittest tests.test_bns_printing_identity -q`. The module's
`--report` mode emits the original and fresh-review negative HTTP journeys for
frontend validation; `compatible_raw_report()` supplies native raw-card positive
controls and `printing_controls_report()` supplies the second review's partial
collector and known normal/Unlimited controls. Each row declares its checked
stage and expected provider-path count.
Both use fake HTTPS/BNS responses and audited external-network denial.

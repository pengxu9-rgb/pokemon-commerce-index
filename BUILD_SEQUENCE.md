# Active build sequence — 1 October 2026

## Product objective

Help a collector explore Pokémon cards, choose an exact printing, compare fresh authorized offers and destination-specific landed costs, and hand the selected URL/quote to Buy&Ship. Merchant recommendations must explain their price and condition evidence; reliability scores require fulfillment outcomes.

The [holistic alignment decision](HOLISTIC_ALIGNMENT_20260930.md) is the current plan. The [independent adversarial review](ADVERSARIAL_ALIGNMENT_REVIEW_20260930.md) challenges its assumptions and the implementation. Earlier review rounds and question cohorts remain historical diagnostics, not competing current schedules.

## Current implementation

The 1 October catalog expansion adds 14,838 source-declared English versions, enriching 9,135 existing number groups and adding 26 new groups. See [coverage and Japanese follow-up](CATALOG_COVERAGE.md). The next catalog batch targets 1,000 Japanese evidence candidates, with results separated into metadata support, identity gaps and printing uncertainty. Live feed work remains held for Buy&Ship.


| Layer | Evidence | Main remaining gap |
|---|---|---|
| Catalog | 70,005 internal source-version/family records; 45,437 language/set/number groups; 33,543 structurally eligible; 532 official rarity corrections; 100 source-bound metadata targets, three release overlays and six vocabulary records | Physical finish/copy evidence and real listing precision remain unverified; supported metadata does not approve automatic joins |
| Graph | Character/artist facets, structural version neighbors, three official evolution families; 657 proposed card-pair artwork assertions; 13 active official collector declarations and 142 proposed visual findings | Independently audited depictions, artwork/counterpart relationships and exact printing coverage; zero verified pair relation events |
| Bilingual retrieval | 122 reviewed aliases and 460 review events included in the new ordered deployment manifest | Translation evidence is not printing equivalence; real marketplace vocabulary recall remains unmeasured |
| Agent discovery | Authored 30-task replay; first source cohort has 16 qualified questions; a second fresh 30-question cohort has eight catalog partials and 22 evidence blockers; stateless inventory comparison; 20 bounded collector journeys / 59 prefix requests; Node caller and eight new source-led development journeys | Active Pivota registration/service identity, artwork/region/printing evidence and an independent held-out outcome evaluation; no real-user answer quality score |
| Pricing | Observation/resolution/index contracts; ask, last-list-at-transition and paid amounts separate | Zero live observations; separate authorized listing feed, real matching audit and sustained freshness |
| Merchant/checkout | 100-target synthetic ingestion rehearsal; complete quote, restart, expiry and URL preview checks; Pivota contract | Real offer-bound quotes, condition/fulfillment evidence, confirmed payment/order lifecycle |
| Cloud | Recorded private read-only catalog deployment | Recoverable market/session storage, ingestion/retention scheduling and monitoring before live use |

Public card display approvals remain zero. Catalog-only internal work can proceed; a public shopping product cannot yet launch.

Implementation evidence and commands: [SUPPORTED_DISCOVERY_IMPLEMENTATION.md](SUPPORTED_DISCOVERY_IMPLEMENTATION.md). The 100 targets deliberately cover one audited modern release (SV4A). Their finish labels remain pinned-source declarations. This is a narrower metadata milestone than a physical-printing allowlist. The original physical verification gate is still open.

## Next sequence while Buy&Ship's feed is unavailable

### 1. Make one identity slice dependable

Select 100 modern Japanese exact-printing targets and the English identities required by collector journeys. This is an engineering cohort, not measured market coverage.

- Add an explicit, evidence-backed supported allowlist; omitted/unverified eligibility must fail closed through imports, migrations and re-imports.
- Audit each supported name, release, number and physical variant. Correct known release metadata conflicts, including SV4A's set title, using official evidence.
- Add sourced printed codes, localized set names and marketplace aliases shared by discovery, matching and feed queries.
- Include selected reviewed bilingual aliases and their review events in an ordered manifest. Translation is not printing equivalence.

**Done when:** every supported target has positive evidence and no unresolved identity conflict, ambiguity abstains, and local/container/staging membership and alias counts agree.

### 2. Execute collector discovery tasks

Connect natural-language facts to an actual result: exact-card clarification, character/artist retrieval, a scoped cross-language family checklist, structural printing neighbors and separately labelled artwork/counterpart evidence. Record sources and omissions; unknown dates and unsupported cameos remain visible.

Reuse existing graph primitives. AI can collect evidence and review routine cases; disagreement escalates and confident approvals also need a random audit. AI agreement is not an accuracy score. Keep weak links proposed under the existing verification policy.

Fix mixed planned-purchase/resale facts only enough to preserve the task and avoid invented paid costs. Defer broader selling economics, store directories and another generic taxonomy round.

**Done when:** a frozen 30-question suite tests returned card IDs/results and useful clarification, with a proposed internal target of 27 useful outcomes and zero unsupported market, same-printing or completeness claims. This is task acceptance, not population accuracy. Hand-authored structured constraints alone do not satisfy it.

**Development implementation delivered:** raw authored questions execute without manual fact translation; the first run was 28/30 and retained, and the corrected replay is 30/30. A second fresh source-qualified diagnostic now has 30 originals (18 English, 12 Japanese); first runtime 7/30, corrected replay eight catalog partials plus 22 evidence blockers. The sampling-size milestone is met, but source selection and fixes were performed with knowledge of the implementation. This is not an independent held-out acceptance measurement or evidence of complete answers. Stateless owned-inventory comparison is implemented without physical ownership claims or persistence. See [the implementation and diagnostic](COLLECTOR_INVENTORY_IMPLEMENTATION_20261001.md).

### 3. Rehearse the commerce path on the same slice

Exercise exact target → normalized offer → immutable observation → versioned resolution → fresh ask → bound landed quote → price-only recommendation → Buy&Ship URL preview with explicitly synthetic fixtures. Verify mutation, expiry, unknown costs, bundles and ambiguous condition behavior.

Add recoverable storage, bounded retry/quota controls, freshness monitoring and permission-driven retention cleanup before scheduled live ingestion. Cloud Run's catalog file remains a read-only snapshot; it cannot persist observation or session writes.

**Done when:** a source-independent rehearsal produces a fully traceable recommendation or a specific evidence blocker, survives restart/retry, and does not present fixtures as live prices.

**Offline rehearsal delivered:** 100 synthetic listings resolve to the same target coordinates; 14 checks cover restart/replay, conflicting observations, bundles, condition separation, missing costs, quote expiry/invalidation, freshness and retention. A persistent operator-owned SQLite queue now reserves source call budgets before adapter calls, leases work and bounds retries. It has no enabled live adapter or cloud schedule. Managed durable storage, operational monitoring and provider-specific quotas remain necessary before live ingestion.

## Next implementation and measurement

1. The source-bound evidence expansion now has 100 frozen image targets across seven Japanese releases: 94 qualified reviews, six excluded/unresolved targets, a deterministic ten-image Codex audit and fresh Gemini replication. The ledger has 190 historical events, 13 active official declarations and 142 active AI proposals; eight cameo scopes return official-description partials. Three official named cameos were still omitted by the fresh model, and four Codex sample cases show positive differences/uncertainty. Keep AI findings proposed and require exact card/copy evidence for finish or edition approval. Scoped discovery and inventory are now connected through caller-owned multi-turn replay; see [the journey implementation](COLLECTOR_JOURNEY_IMPLEMENTATION_20261001.md). Preserve the first 2/16 and second 7/30 initial outputs; further acceptance measurement must use held-out questions. See [the expansion and calibration](COLLECTOR_EVIDENCE_EXPANSION_20261001.md).
2. The controlled journey now has a dependency-free Node caller and a default-disabled, caller-authorized `collector.explore` wrapper, prepared for Pivota registration. Eight newly opened source situations produced a frozen 26/37 first run, then 33/37 on unchanged expectations after intent repairs. Two declared fixture defects were repaired and two recovery steps added; all 39 revised development steps pass through real HTTP. All 59 original journey prefixes and 30 original question memberships/tasks remain unchanged; 412 Python and 11 Node tests pass. See [the caller implementation](PIVOTA_COLLECTOR_ADAPTER_20261001.md). Confirm the current Pivota repository/entry and service identity, register the operation, then exercise the authenticated agent entry. Operator-token staging checks do not establish deployed Pivota integration. Independent question selection/labels/outcome measurement remain open. Keep unknown versions, AI leads and unsupported exclusions blocked. Independently evidence physical finishes before any live-offer approval; current automatic-live-join-ready count remains zero.
3. Select managed market storage and a separate ingestion worker deployment. Add provider-specific adapter, pagination, request timeout, quota and retention behavior only against the confirmed feed contract. Keep market/session state outside the read-only catalog image.
4. Execute the external feed and real-listing gates below when access arrives. No catalog totals or fixture scores substitute for them.

## When external access arrives

1. Confirm source-specific discovery/search, detail, stable IDs, statuses, quota, storage/display/statistics/media-AI scope and partner URL support. Run actual Gate 0 probes. Buy&Ship's URL-to-quote API is a separate transaction capability, not a listing feed.
2. Freeze an authorized real listing sampling frame and evaluate exact printing/grade precision. Use [AI-first review](AI_FIRST_REVIEW.md) plus uncertainty escalation and random approval auditing. The [existing proposed gate](BLIND_LISTING_BENCHMARK.md) requires at least 300 fully evaluable accepted joint labels, a Wilson 95% lower bound of at least 0.98, and zero accepted multi-card listings. Preserve failures, unknowns and abstention in reporting.
3. Run a narrow ask-only pilot with exact units, source, sample count, timestamp and freshness. Attach live destination-specific landed quotes where available.
4. Run the original sweep-fidelity Gate 1, including sample-size and panel-representativeness checks, before transition-price or liquidity claims. A passed sweep does not establish paid prices; those require settlement evidence.
5. Connect Pivota's agreed identity/offer/quote contracts and confirmed checkout lifecycle. Fulfillment evidence and calibrated condition assistance precede comprehensive merchant ranking.

## Main progress measures

Track source-backed supported printing coverage, useful executed collector outcomes, independently evaluated graph coverage, real exact-unit match precision/abstention, fresh offer coverage, valid landed quotes and eventual sale/fulfillment evidence. Catalog totals, AI agreement and engineering test counts are supporting diagnostics.

Detailed rationale, acceptance criteria and evidence: [HOLISTIC_ALIGNMENT_20260930.md](HOLISTIC_ALIGNMENT_20260930.md), [SQL evidence](HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json). Earlier plan: [ASTRA_REVIEW_AND_PLAN.md](ASTRA_REVIEW_AND_PLAN.md). Earlier independent review response: [INDEPENDENT_REVIEW_RESPONSE.md](INDEPENDENT_REVIEW_RESPONSE.md).

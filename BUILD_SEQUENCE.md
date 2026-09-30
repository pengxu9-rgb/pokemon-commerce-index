# Active build sequence — 30 September 2026

## Product objective

Help a collector explore Pokémon cards, choose an exact printing, compare fresh authorized offers and destination-specific landed costs, and hand the selected URL/quote to Buy&Ship. Merchant recommendations must explain their price and condition evidence; reliability scores require fulfillment outcomes.

The [holistic alignment decision](HOLISTIC_ALIGNMENT_20260930.md) is the current plan. The [independent adversarial review](ADVERSARIAL_ALIGNMENT_REVIEW_20260930.md) challenges its assumptions and the implementation. Earlier review rounds and question cohorts remain historical diagnostics, not competing current schedules.

## Current implementation

| Layer | Evidence | Main remaining gap |
|---|---|---|
| Catalog | 55,167 internal identities; 33,543 structurally eligible; reproducible manifest; 532 official rarity corrections | Positive supported-printing allowlist, localized release metadata and marketplace vocabulary; eligible is not validated accuracy |
| Graph | Character/artist facets, structural version neighbors, 657 proposed artwork assertions in the current manifest | Executable family/checklist tasks, independently evaluated relationships; zero verified relation events |
| Bilingual retrieval | 122 reviewed aliases in research artifacts | Current deployed-manifest snapshot contains zero alias revisions; import selected aliases with evidence and manifest checks |
| Agent discovery | Local structured exploration and frozen question-routing diagnostics | Actual catalog results from natural-language requests; no real-user answer quality score |
| Pricing | Observation/resolution/index contracts; ask, last-list-at-transition and paid amounts separate | Zero live observations; separate authorized listing feed, real matching audit and sustained freshness |
| Merchant/checkout | Synthetic landed-cost ranking and Buy&Ship URL-to-quote preview; Pivota contract | Real offer-bound quotes, condition/fulfillment evidence, confirmed payment/order lifecycle |
| Cloud | Recorded private read-only catalog deployment | Recoverable market/session storage, ingestion/retention scheduling and monitoring before live use |

Public card display approvals remain zero. Catalog-only internal work can proceed; a public shopping product cannot yet launch.

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

### 3. Rehearse the commerce path on the same slice

Exercise exact target → normalized offer → immutable observation → versioned resolution → fresh ask → bound landed quote → price-only recommendation → Buy&Ship URL preview with explicitly synthetic fixtures. Verify mutation, expiry, unknown costs, bundles and ambiguous condition behavior.

Add recoverable storage, bounded retry/quota controls, freshness monitoring and permission-driven retention cleanup before scheduled live ingestion. Cloud Run's catalog file remains a read-only snapshot; it cannot persist observation or session writes.

**Done when:** a source-independent rehearsal produces a fully traceable recommendation or a specific evidence blocker, survives restart/retry, and does not present fixtures as live prices.

## When external access arrives

1. Confirm source-specific discovery/search, detail, stable IDs, statuses, quota, storage/display/statistics/media-AI scope and partner URL support. Run actual Gate 0 probes. Buy&Ship's URL-to-quote API is a separate transaction capability, not a listing feed.
2. Freeze an authorized real listing sampling frame and evaluate exact printing/grade precision. Use [AI-first review](AI_FIRST_REVIEW.md) plus uncertainty escalation and random approval auditing. The [existing proposed gate](BLIND_LISTING_BENCHMARK.md) requires at least 300 fully evaluable accepted joint labels, a Wilson 95% lower bound of at least 0.98, and zero accepted multi-card listings. Preserve failures, unknowns and abstention in reporting.
3. Run a narrow ask-only pilot with exact units, source, sample count, timestamp and freshness. Attach live destination-specific landed quotes where available.
4. Run the original sweep-fidelity Gate 1, including sample-size and panel-representativeness checks, before transition-price or liquidity claims. A passed sweep does not establish paid prices; those require settlement evidence.
5. Connect Pivota's agreed identity/offer/quote contracts and confirmed checkout lifecycle. Fulfillment evidence and calibrated condition assistance precede comprehensive merchant ranking.

## Main progress measures

Track source-backed supported printing coverage, useful executed collector outcomes, independently evaluated graph coverage, real exact-unit match precision/abstention, fresh offer coverage, valid landed quotes and eventual sale/fulfillment evidence. Catalog totals, AI agreement and engineering test counts are supporting diagnostics.

Detailed rationale, acceptance criteria and evidence: [HOLISTIC_ALIGNMENT_20260930.md](HOLISTIC_ALIGNMENT_20260930.md), [SQL evidence](HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json). Earlier plan: [ASTRA_REVIEW_AND_PLAN.md](ASTRA_REVIEW_AND_PLAN.md). Earlier independent review response: [INDEPENDENT_REVIEW_RESPONSE.md](INDEPENDENT_REVIEW_RESPONSE.md).

# Adversarial implementation alignment review — 2026-09-30

## Decision

**Continue the project, redirect the immediate build toward an executable collector-discovery slice, and keep market activation behind a separate evidence gate.** The implementation has a credible catalog and useful safety contracts. It does not yet demonstrate a price-index or merchant-recommendation product, and broad AI agreement counts do not establish either exact-printing accuracy or discovery usefulness.

The original Claude plan made observation fidelity the decisive experiment for a clearing-price index. The later decision to build discovery ahead of Buy&Ship access is reasonable: it supplies an independent workstream. That workstream now needs an outcome users can inspect—actual scoped checklists, related-card results and a defensible exact target—rather than further expansion of question-routing labels.

This is a read-only review of code, committed evidence and the local corrected catalog. No deployment, marketplace call, external message, model inference or new factual web research was performed. Severity below means priority for this product, not a claim that staging is unsafe. `[V]` denotes locally verified behavior or data; `[D]` a documented observation not independently repeated; `[I]` an inference or recommendation.

Reviewed implementation baseline: `f6cd01b`. The subsequent alignment documents change the active plan; they do not change that reviewed runtime baseline.

## Verified baseline

Read-only SQLite queries against `catalog-index-rarity-v2.sqlite3` independently returned:

| Measure | Result | What it establishes |
|---|---:|---|
| Internal catalog identities | 55,167 | Breadth of the ingested identity collection, not complete coverage of all physical printings |
| Structurally match-eligible | 33,543 | Current software eligibility flags, not marketplace match precision |
| Public-display approvals | 0 | No externally displayable catalog under the current policy |
| Same-artwork assertions | 657 proposed, 0 verified | Internal candidate leads; no verified counterpart or price equivalence |
| Bilingual concept revisions | 0 | Research alias work is absent from this particular build |
| Listings / observations / verified sales | 0 / 0 / 0 | No market evidence in the inspected staging catalog |
| Cards missing a localized release date | 9,788, including 441 eligible | A chronological checklist cannot silently claim complete dates |
| Eligible Japanese identities without same-set/number second-source records | 4,056 | Evidence coverage gap; this does **not** prove those identities are wrong |

The database SHA-256 is `7c707e5d7b3b886b2af4c69fcf7713667e60be25e4c7bd383c7340e63e0dd222`. The current manifest hash is `eb9893b0fbec76d428f25e0db9955f865ad20955b88f48c828d671d8c3a2e0ff`, matching the recorded deployment receipt at `cloud-deployment-20260930.json:51`.

`Dockerfile:6–13` uses that manifest. Its `import-ai-artwork-proposals` operation and expected 657 assertions are explicit at `catalog-build-manifest-rarity-v2.json:85–111`; the builder rejects non-proposed artwork inputs at `scripts/build_catalog_snapshot.py:16–23`. **The current build includes proposed artwork leads.** The older statement that the deployed snapshot excludes proposed edges in `INDEPENDENT_REVIEW_RESPONSE.md:11` is stale historical text, not the current configuration. The receipt establishes what was recorded for revision `pokemon-commerce-index-00010-w7b`; this review did not independently query Cloud Run's present traffic or image contents.

## What has held up under challenge

1. **Canonical identities and market observations are separate.** `schema.sql:21–35` defines catalog identity; `schema.sql:298–353` separates listings, observations, raw item evidence and resolution history. Cross-language artwork links do not collapse units.
2. **Market claims remain constrained.** `core.py:1391–1400` names asks, last observed list prices at transitions and verified paid evidence separately. `core.py:1357–1365` excludes transitions later observed reverting to on-sale, respecting the knowledge cutoff. This addresses the central risk of manufacturing sales from disappearance.
3. **Recommendation semantics are honest.** `core.py:1271–1288` selects complete landed quotes for one exact unit and labels the result `price_only`. `core.py:1231–1268` calls seller overlap inventory coverage, not fulfillment trust. These are valuable foundations, but currently synthetic.
4. **Historical review defects have meaningful fixes.** The grade/slab, ambiguous edition, stale-photo and quote-binding fixes are visible at `core.py:883–941`, `core.py:1374–1384` and `core.py:1291–1312`. Their existence is verified; their accuracy on fresh real listings is not.
5. **A graph database is unnecessary now.** Typed relations and facets fit the existing relational design. Storage technology is not the current limitation; evidence coverage and executed user tasks are.

## Findings

### P1 — The team is measuring routing correctness while the core discovery task remains unexecuted [V/I]

`buyer_questions.py:15–18` exposes six question types for an already identified card. `plan_card_question` explicitly returns an evidence plan, not an answer (`:25–28`). There is no checklist, evolution-family enumeration or collection-completion question type here. `question_routing_v7.py:65–186` preserves seller tasks and blocked capabilities, but does not implement the requested catalog or merchant retrieval.

The fresh v11 evidence records a concrete failure of useful discovery: case 006's cross-language chronological family checklist maps to `other` and general explanation; case 015's deck-building purchase also gets a coarse general action (`QUESTION_ROUTING_V11_DIAGNOSTIC.md`, “Gaps and disagreements”). An allowed goal label can therefore pass without accomplishing the user's task.

The 10 journey / 15-step evaluation supplies hand-authored structured constraints directly to saved exploration state (`scripts/evaluate_discovery_journeys.py:39–53`). Only 3 of the 15 steps require a specific returned card ID. It tests state/clarification regressions, not natural-language interpretation or checklist recall. This is correctly disclosed at `:93`; it must not become a readiness metric.

**Action:** select a small number of collector tasks and execute them end to end. Measure actual returned identities, coverage, ordering, exclusions and exact-target selection. Another broad seller-goal taxonomy round is lower priority unless it directly fixes a selected journey.

### P1 — Catalog breadth is ahead of printing-confidence and marketplace vocabulary [V/D/I]

`core.py:244` substitutes `standard` for missing variants. `core.py:307–308` defaults missing match eligibility to true; `schema.sql:32` does the same. The prior independent review response still lists fail-open seeds, vintage Japanese eligibility and incomplete special-printing audits as open (`INDEPENDENT_REVIEW_RESPONSE.md:25–29`). Thus 33,543 eligible rows are not 33,543 positively certified physical printings.

The local SV4A set title remains `レイジングサーフ`; its individual Mew rarity was corrected, but that does not repair the set's identity metadata. Missing release dates and the 4,056 eligible Japanese rows lacking an exact-number second-source record add useful audit priorities, not a reason to delete all of them.

`listing_candidates.py:18–40` has a few hard-coded legacy aliases and a special set-name rule. The exact matcher relies chiefly on literal set codes, fractions and card-name substrings (`core.py:856–875`, `:924–925`). The eBay cohort explicitly remains `not_ready_marketplace_alias_required` (`EBAY_ACCESS_AND_PILOT.md:30`). Even a perfect broad catalog cannot answer titles that omit or phrase its coordinates differently.

**Action:** establish explicit source-backed evidence status and a narrow positive matching scope. Preserve the broad catalog for discovery. Audit set titles, number namespaces, finish/edition context and real marketplace names for that scope; do not expand the raw count as the headline goal.

### P1 — The graph is useful as candidate retrieval, but verified cross-region identity remains absent [V/I]

It is wrong to conclude that the graph contains nothing: `discovery_graph.py:236–242` exposes structural printing neighbors; `:278–312` exposes character and illustrator retrieval. The 657 proposed artwork leads are returned separately, with `price_comparable=false` (`:263–277`, `:316–319`). These are appropriate internal discovery features.

It is equally wrong to treat those leads as proven counterpart coverage. There are zero verified edges, and verified-link answers consequently cannot serve a verified counterpart. `buyer_questions.py:53–74` correctly retains AI artwork leads as proposals. Character IDs do not encode evolution membership; matching a character does not establish an image cameo; sharing an image does not establish matching finish or pricing behavior.

Research alias counts also overstate deployed capability if read without a build boundary: this snapshot has zero bilingual concept revisions, while `catalog_question_resolver_v2.py:25–40` requires approved revisions for name translation.

**Action:** build explicit source-backed character-family membership and scoped checklist operations, import only the needed reviewed aliases through the same reproducible manifest, and curate a bounded high-value cross-language relationship slice. AI can collect evidence and independently inspect routine cases; confident agreement alone must not be the reference truth. Keep ambiguous finishes and disputed links unresolved, with targeted exception review.

### P1 — A real price and purchase slice still has two independent external gates [V/D]

Buy&Ship's partner API is URL-to-product/quote/transaction handoff, not listing discovery (`BUYSHIP_PARTNER_INTEGRATION.md:7–9`). It cannot find the first URL for an arbitrary target. A separate feed remains necessary. The repository's eBay document records unresolved production/data-use permission; this review has not rechecked current legal terms and does not offer a new legal conclusion.

No authorized observation corpus means no measured marketplace precision. The blind benchmark is thoughtfully designed (`BLIND_LISTING_BENCHMARK.md:9–11`, `:48–52`) but unrun. No feed also means the original sweep-fidelity experiment is unrun. `calibration.py:87–102` appropriately returns insufficient evidence without quotas, sale counts and a power-analysis threshold; it does not implement a deployed capture panel or a corrected price series.

**Action:** track feed discovery/rights and quote credentials as separate dependencies. Do not describe partner API access as permission to publish a multi-market index. Build the offline pipeline and exact query vocabulary now; run the real sampling and Gate 0/1 only after usable access arrives.

### P2 — Production operating behavior remains a scaffold, despite staging deployment [V/D/I]

The private service opens a read-only catalog for each GET (`cli.py:29–36`) and exposes catalog/evidence-plan routes (`:56–75`). It is not a persistent exploration or continuous ingestion service. Durable user identity, ownership, deletion, history, ingestion schedules, quota control, monitored freshness and automatic retention enforcement remain outside the deployed slice (`CLOUD_RUN.md:23`; `INDEPENDENT_REVIEW_RESPONSE.md:30`).

The original differentiation—marginal consolidated landed cost and fulfillment-grounded merchant quality—is not delivered by a lowest-quote sort or seller overlap. It needs basket quotation semantics and fulfillment labels. It should stay in the roadmap; it should not trigger a general merchant-discovery directory project before the buyer path works.

**Action:** define the first feed worker and persistence boundary, exercise failure/recovery offline, and add production infrastructure only for that bounded path. Do not deploy session writes into ephemeral Cloud Run storage.

### P2 — AI independence and evidence provenance need stronger operational proof [V/I]

`offer_comparison.py:98–107` validates an operator-supplied model family and provider-shaped response hash. It does not authenticate the actual provider response. `AI_FIRST_REVIEW.md:7` acknowledges this. Two claimed model families can pass the contract without proving that two independent calls occurred. Requiring review on each observation can also create unnecessary expense when images are unchanged (`EBAY_ACCESS_AND_PILOT.md:34`).

**Action:** retain actual response evidence and bind executed provider/model identity. Separate photo evidence validity from price/status freshness, with invalidation on changed images/identity-bearing description, so unchanged photography need not be reinterpreted on every price poll. Test this before real automatic approvals.

### P2 — Evolving documents need a current-state boundary [V/I]

The earlier review response and architecture notes contain older build/edge counts and priorities. They are useful history but misleading if interpreted as current deployment truth. The current manifest and deployment receipt resolve the proposed-edge contradiction, while the latest routing diagnostic resolves the remaining task gaps.

**Action:** add one current status/decision document that links each active metric to a build or evaluation and marks older reviews historical. Do not rewrite frozen evidence or present development replays as new holdouts.

## Revised next three milestones

The numbers below are proposed scope bounds and acceptance targets, not claims of existing accuracy or forecasts of delivery time.

### 1. Trusted pilot scope and current-state ledger — independent of Buy&Ship

Deliver an explicit, source-backed pilot of approximately 100 modern Japanese targets plus a small set of English comparison anchors. Choose them for documented collector journeys and available evidence, not invented GMV. Preserve all broad catalog rows as research/discovery candidates.

Acceptance:

- Every pilot target has stable ID, source provenance, scoped collector number, corroborated name/set metadata, explicit variant/finish evidence status and a reason for matching eligibility or exclusion.
- Every pilot set has a source-backed title and release-date status; unknown dates remain unknown. Correct SV4A through a provenance-bearing overlay.
- Source-backed printed/set-name aliases and search terms are recorded for at least 20 selected target queries. Missing marketplace vocabulary is an explicit blocker, not an executable guessed query.
- Seed omission cannot silently authorize a pilot target for automatic matching. The build reports trusted pilot coverage separately from total and structurally eligible rows.
- One status ledger distinguishes deployed catalog, offline research graph, question diagnostic and market readiness, with hashes and actual counts.

### 2. Executable collector discovery and graph slice — independent of Buy&Ship

Deliver actual scoped family/character checklists, variant inspection and cross-language artwork leads, followed by exact-target selection. Keep the first experience private/internal until display scope is resolved. Add family/evolution relations from explicit evidence; do not infer them from common names or artwork. A proposed relationship may be shown as an internal lead without becoming a counterpart.

Acceptance:

- At least five collector journeys return inspectable identities and provenance: same-character across JA/EN; family checklist including a branching family; chronological list with missing dates separated; same-artwork lead versus verified counterpart; same-number finish selection.
- A frozen development set checks exact expected IDs, missing/excluded releases, language, variant ambiguity, date ordering and incomplete coverage. Metrics report each task separately rather than a primary-goal agreement rate.
- A fresh task set is collected only after freezing the implementation. Independent reference evidence is assembled without seeing retrieved candidates; measure expected-member recall, unsupported-member errors, target-selection success and clarification usefulness within the declared catalog scope. Report AI-reference limitations and unresolved items.
- Reviewed aliases needed by these journeys appear in the deployed manifest, with their evidence/revisions; research counts do not substitute for this check.
- Zero automatic cross-printing price pooling, zero invented counterpart/finish/cameo claims, and clear no-live-price status throughout.

### 3. Feed-ready buyer commerce pipeline — offline preparation now, live activation conditional

Deliver one reusable path: exact target → source query/detail → versioned observation/resolution → fresh asks → complete destination quote → reviewable product URL handoff. Exercise it with recorded authorized examples if available, otherwise openly synthetic contract fixtures. Such a replay is engineering verification, not market precision.

Acceptance before access:

- One source-specific contract and bounded query plan separates listing-feed rights from partner-quote rights. Verify which existing adapters still match the actual contract when credentials arrive.
- Failure simulations cover duplicate/reordered pages, 429/retry, interrupted restart, partial detail failure, changed price/photo, cancellation, stale quote and retention expiry. The worker produces quota/freshness/coverage evidence and never converts unknown fields to zero.
- Persistence and provider-response evidence have explicit boundaries; no session or observation state depends on a Cloud Run container's lifetime.
- The original blind sampling frame, frozen matcher and AI-first audit process are ready to run. Report real joint identity/variant/grade accuracy only after authorized real evidence exists.

Acceptance after access:

- Run Gate 0, then a bounded ask/quote pilot. Publish freshness, sample counts, abstention and failures, with a source-specific positive auto-join scope and the pre-agreed precision gate.
- Confirm URL resolution and quote binding for the exact product before transaction handoff. Payment/order confirmation remains explicit.
- Run a powered, representativeness-aware Gate 1 separately if sold observations are available. No paid-price, liquidity or popularity conclusions from asks, forum comments, graph degree or disappearance.

## Work to defer

- Further catalog expansion outside concrete pilot gaps.
- More thousand-pair AI review rounds without an independent reference and retrieval-coverage objective.
- Broad seller profit/buyback/store-directory routing before the selected buyer journeys execute.
- A graph database migration, public chat launch, merchant trust score, or trend/cross-region-price product without their corresponding evidence.

## Overall alignment

The project remains aligned with Claude on exact identities, append-only observations, source rights, price semantics and conditional clearing-price publication. It has intentionally moved discovery earlier. The implementation drift is that discovery evaluation has concentrated on safe planning and labels rather than returned useful card results. Correct that now. The immediate milestone should be **a verifiable collector journey over a trusted catalog slice**, with the real-market lane ready for activation but measured separately.

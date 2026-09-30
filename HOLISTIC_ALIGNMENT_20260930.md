# Holistic product alignment — 30 September 2026

## Decision

Continue the product, with a narrower next milestone: **make a trusted catalog slice produce useful collector discovery results, then attach an authorized offer feed to that same slice.**

The intended product remains:

`collector question → explainable catalog/graph exploration → exact printing target → fresh offers → destination-specific landed quotes → evidence-based merchant choice → confirmed transaction handoff`

The catalog, graph and commerce layers should share exact printing IDs and evidence. A larger catalog, additional AI votes or better intent labels cannot replace an executed result. Keep the broad catalog as research coverage; make a deliberately supported subset dependable.

This document is the active alignment decision. Earlier review documents describe their own reviewed commits and remain historical evidence. See the [independent adversarial report](ADVERSARIAL_ALIGNMENT_REVIEW_20260930.md) and [reproducible SQL measurements](HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json).

The independent reviewer agrees with this priority change: source-backed pilot identity, executable collector tasks, then feed-ready commerce. Both reviews identify default eligibility, absent deployed aliases and unexecuted checklist requests as concrete gaps. No runtime behavior or deployment was changed in this review; the implementation work below is the decided next sequence.

## Evidence checked

- Reviewed baseline: `f6cd01b`, with the original user-supplied Claude plan, the 28 September independent review and the response to that review.
- Fresh local rebuild of `catalog-build-manifest-rarity-v2.json`: all expected counts reproduced across 19 ordered, hash-checked import steps.
- Current local snapshot SHA-256: `7c707e5d7b3b886b2af4c69fcf7713667e60be25e4c7bd383c7340e63e0dd222`.
- All **330 engineering tests passed** on the installed Python 3.14.7. Unclosed test-connection warnings remain. This does not establish real listing precision, user usefulness or verification on every supported runtime.
- The saved private Cloud Run receipt references the same build-manifest hash. Cloud was not queried or redeployed during this review.
- Read-only database measurements and their exact SQL are in [HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json](HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json).

## Where implementation stands against the overall plan

| Product layer | What is implemented and evidenced | What has not been demonstrated | Alignment |
|---|---|---|---|
| Canonical catalog | 55,167 internal identities; 543 card-bearing language/set combinations; source references, number-conflict holds and 532 official rarity corrections; reproducible build | Exact physical-printing accuracy across the catalog; reliable marketplace vocabulary; public display approval | Substantial research foundation; a supported identity slice is still needed |
| Relationship graph | Character/artist retrieval, structural version neighbors, typed append-only relationship assertions; current manifest contains 657 proposed artwork events | Any verified cross-language relationship; counterpart recall/precision; executable evolution-family and chronological collection checklists | Useful primitives, incomplete collector product |
| Agent discovery | Local structured exploration state and candidate-driven clarification; frozen question extraction/routing diagnostics | An end-to-end natural-language question returning a useful, validated catalog result; durable authenticated user sessions | Brought forward legitimately by the user; recent effort has overfocused on routing |
| Price index | Authorized observation import, versioned resolution, separate ask/list-at-transition/paid series, knowledge cutoff and calibration calculations | Any live marketplace observations, measured exact-unit precision, sustained freshness, duplicates/relist handling or an actual Gate 1 run | Engineering prototype; external data access is still the commercial dependency |
| Merchant recommendations and checkout | Same-unit `price_only` landed-quote comparison, inventory overlap, synthetic Buy&Ship URL-to-quote preview and Pivota contract | Live fee/FX/quote binding, actual fulfillment quality, condition-calibrated ranking, payment and order lifecycle | Contracts and fixtures; no real merchant recommendation product yet |
| Operations | Recorded private read-only Cloud Run deployment and manifest-based container build | Recoverable market/session storage, scheduled ingestion and retention cleanup, monitoring, account authorization | Suitable for controlled internal catalog use |

### Important count and deployment distinctions

- **33,543 `match_eligible` is a structural flag, not a measured accuracy result or launch allowlist.** Import and migration defaults still allow eligibility without a positive verification record.
- **4,056 eligible Japanese identities have no reference at the same set/number.** This is a source-coverage gap, not proof that all 4,056 are incorrect.
- **9,788 identities lack a release date; 441 of these are eligible.** A chronological checklist must show undated entries separately and cannot claim completeness.
- **122 reviewed bilingual aliases exist in research artifacts; the current deployed-manifest snapshot contains zero alias revisions and zero concept-review events.** Research success is not yet deployed functionality.
- The current build **does include 657 proposed artwork assertions**, and has **zero verified relationship events**. Older statements that deployment excludes all proposed relationship assertions are superseded.
- Current snapshot: **zero listings, observations, verified sales, landed quotes and listing visual reviews; zero public-display-approved cards**.

## What we retain from Claude's plan

1. Clean project and explicit provenance rather than inheriting the old demo architecture.
2. Separate catalog identities, exact priceable units, marketplace observations and versioned resolutions.
3. Keep asking prices, last observed list prices before a status transition and verified paid amounts separate. Disappearance is not a sale.
4. Treat Buy&Ship URL-to-resolve/quote as a transaction path; it does not supply marketplace discovery. The legacy search gateway requires its own current contract and credentials.
5. Make landed cost and eventual fulfillment evidence the basis of merchant differentiation. Marketplace stars and AI-generated seller opinions are insufficient.
6. Keep Gate 0 and the original sweep-fidelity Gate 1. Gate 1 controls transition-price/liquidity claims, with power and representativeness checks; it does not block collector discovery or an authorized ask-only pilot.

## Where we revise the order

The user explicitly brought collector exploration and cross-region relationships forward while Buy&Ship is unavailable. That is a reasonable adjustment: people need help choosing a printing before shopping. However, broad seller advice, store discovery, net-profit planning and repeated intent-taxonomy revisions have grown faster than executable collector discovery.

The v11 diagnostic illustrates the difference: a cross-language Ralts-family checklist can receive an acceptable goal label while returning only a general-explanation plan. A correct route is an intermediate output; the product must return a useful checklist, candidate set, number explanation or clarification grounded in its own catalog.

Preserve the sandbox and frozen failures. Use it to select tasks and challenge assumptions. Resume question collection after an actual new capability exists, and evaluate returned results as well as intent labels.

## Dependency-ordered next milestones

### 1. Supported identity and vocabulary slice — can start without Buy&Ship

Start with **100 modern Japanese exact-printing targets**, plus English identities needed by selected collector journeys. This is a manageable engineering cohort, not a claim about demand or GMV coverage. Keep unsupported vintage, sealed products, bundles and uncertain finishes outside its automatic matching scope.

Work:

- Separate broad structural eligibility from a positive, evidence-backed launch allowlist. Make omitted eligibility fail closed for new imports/migrations; migrate pinned seeds deliberately rather than accidentally enabling or disabling everything.
- For each supported target, record official name, release/set, printed number, variant/finish, category and source evidence. Audit known incorrect set names, including SV4A; do not infer a correct set title from a corrected rarity.
- Add sourced localized set names, printed codes and marketplace aliases. Use the same vocabulary in question resolution, listing retrieval and matching, with ambiguous aliases requiring clarification.
- Import the selected reviewed bilingual aliases through a versioned, hash-checked manifest, including their review evidence. Alias approval does not create a printing-counterpart edge.

Exit criteria:

- Every supported target has an explicit reason for inclusion and no unresolved identity conflict; unsupported entries remain available as clearly marked discovery candidates.
- Omitted or unverified eligibility cannot silently enter the supported slice after a seed re-import or migration.
- Local, container and recorded staging manifest agree on supported membership, alias counts and corrections.
- A development corpus covers real printed names/codes, missing finish, ambiguous edition/grade phrases and negative/bundle cases. Report failures and abstention; do not call synthetic or old-demo examples fresh marketplace precision.

### 2. Executable collector discovery — can start without Buy&Ship

Support a small set of concrete tasks:

1. Identify a card from scoped number/name clues and ask one relevant next question when a printing remains ambiguous.
2. Retrieve cards for a character or artist with explicit retrieval basis.
3. Build a scoped Japanese/English family checklist in release order. Add source-backed family membership; distinguish evolution lineage, forms, multi-character cards and artwork cameos. Missing dates and unsupported cameo coverage remain visible.
4. Return structural finish neighbors and separately labelled artwork/counterpart evidence. Do not transfer prices across related printings.
5. Save an exact target or shortlist in controlled internal use for a later offer search.

Work:

- Connect facts → task planning → actual catalog/graph execution → result with provenance and coverage. A task name or capability flag alone is not an executed result.
- Reuse current facets and assertions. Add relation types only where a supported task requires them; a new graph database is not justified yet.
- Use AI for evidence collection and routine review, preserving inspected inputs, model responses and uncertainty. Independent AI agreement supports triage; it is not an accuracy measurement. Uncertain cases escalate, and any automatic verification policy also audits a random sample of confident approvals.
- Promote source-backed relation claims only under the existing verification policy; preserve proposed status where evidence is insufficient. The collector slice can work with typed structural and character relations before any counterpart is verified.
- Address planned purchase/resale and proposed-versus-paid cost facts only enough to preserve mixed tasks and prevent unsafe market execution. Broad selling-economics and store-directory features stay deferred.

Exit criteria:

- Freeze **30 independent questions with expected catalog results and permissible uncertainty before running the implementation**; cover Japanese/English, numbers, family/artist requests, printings, missing evidence and unsupported scope.
- Each supported question yields sourced card IDs/results or a specifically justified clarification. Catalogue omissions, mistaken results and failures remain in the denominator.
- Proposed target for the first internal slice: at least **27/30 useful outcomes** under prewritten criteria and **zero unsupported price, availability, same-printing or completeness claims**. This is a task-suite acceptance target, not a population accuracy estimate.
- Report result precision/completeness and clarification usefulness by task; evaluate relationship recall@K only where independently established positive answers exist.
- An internal reviewer can reproduce results from the exact deployed catalog/alias manifest. Hand-mapped structured constraints alone do not pass this milestone.

### 3. Feed-ready commerce rehearsal, then live ask pilot

Before external access:

- Exercise the same supported targets through normalized fixtures: discovery ID → exact-unit resolution → immutable observations → freshness/expiry → ask series → bound landed quote → `price_only` result → Buy&Ship URL handoff preview.
- Cover price/status/image changes, inconsistent quotes, bundles, missing costs, ambiguous condition and repeated/relabeled listings. Keep fixture outputs explicitly synthetic.
- Provide recoverable observation storage, restart/retry behavior, bounded quotas, ingestion/freshness monitoring and permission-driven retention cleanup before scheduled live collection. Avoid assuming writable Cloud Run SQLite will persist.
- Keep Pivota at a stable ID/offer/quote/evidence handoff contract; reuse its account/checkout infrastructure after owners confirm mappings. There is no reason to build a second payment system.

With source credentials and scope:

- Run Gate 0 on actual endpoints, statuses, URL patterns, quota and data semantics. Obtain the separate listing discovery capability; partner quote access alone enables only supplied-URL quotation.
- Freeze a real authorized listing sampling frame. Use independent AI review for routine labels, uncertainty escalation and random confident-approval auditing as documented in `AI_FIRST_REVIEW.md`.
- Preserve the existing proposed release gate: at least **300 accepted predictions with fully known joint printing/grade labels**, Wilson 95% lower bound at least **0.98**, and zero accepted multi-card listings. Choose the initial sample size to achieve that accepted denominator; 300 input titles may be insufficient. Report unknown fields, abstention and unsupported strata separately.
- Run an ask-only pilot on the supported slice; publish source, exact unit, sample count, timestamp/freshness and applicable landed quote evidence.
- Evaluate Gate 1 separately before last-list-at-transition/liquidity claims. Paid-price claims still need authorized settlement evidence even if sweep coverage passes.

## Work to defer

- Broad catalog expansion to hit a headline count; additional thousand-pair AI-consensus rounds without a supported task and independent outcome measure.
- Another general seller taxonomy version before a collector task returns real catalog results.
- Merchant reliability scores, counterfeit certification, photo-derived professional grades, demand/popularity or price forecasts without their respective evidence.
- Public display, real user session writes, notification scheduling, new marketplace assumptions and live transaction execution until their own existing evidence/access gates are met.

## Progress measures from here

| Measure | Baseline / next evidence |
|---|---|
| Source-backed supported printing targets | No separate launch allowlist yet → milestone 1 cohort with per-target evidence |
| Useful executed collector outcomes | Not measured → frozen 30-question result suite |
| Supported graph coverage and correctness | 657 proposals, zero verified events → typed task coverage and independently labelled results |
| Exact listing/unit precision and abstention | Not measured → authorized blind frame and approval audit |
| Fresh live offer coverage | Zero → source/slice-specific counts, age and quota logs |
| Valid landed recommendations | Fixtures only → fresh exact-offer bound partner quotes |
| Sale/fulfillment evidence | Zero → settlement and outcome data, plus original Gate 1 where relevant |

These measures replace catalog breadth and model-agreement counts as the main implementation milestones. They retain the original commerce objective while giving us a useful, testable product step that does not wait for Buy&Ship.

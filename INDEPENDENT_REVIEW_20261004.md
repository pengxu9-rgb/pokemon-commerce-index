# Independent whole-project review — 4 October 2026

## Scope and baseline

Reviewed `pengxu9-rgb/pokemon-commerce-index` at `f499b46f7f0898c5c0478c53fef960d435f1765f`, its implementation delta from `e44c2fd5d6bb60868254bb404e418c5a06f1fa0e`, and the discovery proposal originally anchored at `ad7bd216ae4511b8993deb24176498607e73d6c8`. This review covers the collector state machine, recommendation ranking and explanations, identity/graph boundaries, inventory, caller contracts, future commerce contracts, performance and private rollout procedure. It is not a new physical-card audit or live-market validation.

The initial commit's CI run [37160347776](https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/37160347776) succeeded, including Docker build. The Python log says 626 tests run with 2 skipped, not 626 executed passes. The initial workflow did not explicitly execute Node contract tests or the HTTP-to-Node recommendation rehearsal; this review adds both, real-catalog diagnostics and retained receipts.

## Product and architecture assessment

The direction is coherent: collector questions, sourced graph/catalog exploration and explicit targets are useful before a listing feed exists. The new loop meaningfully implements the earlier proposal: validated collecting preferences, deterministic facet-backed ranking, coordinate diversity without version merging, feedback, evidence-only comparison, exact focus and separate catalog selection. It is bounded deterministic parsing and ranking, not a general conversational reasoning system.

Three boundaries must remain explicit:

1. **Research catalog → supported catalog target.** Broad discoverability and structural matcher eligibility do not prove a record is an accurate physical printing. The existing source-supported cohort consists of 100 Japanese SV4A records, 90 names, all carrying an unverified source-declared holo label. Broad English Mew examples can be name-relevant while containing identity-held records; relevance, inspectability and selectability are different denominators.
2. **Catalog target → verified offered copy.** Typed artwork relationships, numbered-part/source-family facts and regional coordinates do not establish the same physical printing, condition, grader/grade or price comparability. Source fact warnings and identity holds stay attached through selection.
3. **Verified offered copy → commerce.** Fresh authorized offers, destination quotes, merchant evidence and a confirmed Buy&Ship handoff require the missing listing/search feed. The partner URL-quote API does not supply that feed. Its recorded first-phase scope is one item/quantity one for supported US or HK destinations; European coverage, baskets and consolidation are not established here. The Python container does not deploy/register the Node caller or provide authenticated durable customer sessions.

The price architecture usefully distinguishes current asks, last observed list prices at a status transition and evidenced paid prices. Landed comparisons require scoped current quote/copy evidence and compatible conditions/currency; the cheapest quote remains a price-only decision, not merchant reliability. No live merchant recommendation or purchase has been demonstrated.

## Prioritized findings and fixes

### P1 — negative preferences became positive matches

A fresh catalog fixture reproduced `Recommend Japanese Pikachu cards` → `I do not like Mew` returning Mew candidates. The first corrective attempt exposed a second authority defect: an unresolved warning disabled the displayed selection flag but a direct select action could still create a target. The final implementation makes pending clarification part of derived authority, cache keys and direct selection gates. Unrelated feedback, no-op refinement, money/notes/mode changes, inventory, pagination, comparison focus and yes replies cannot silently resolve it. Exact relevant structured preference/refinement or a new goal can resolve it. Common `except`, `other than` and `anything but` forms are held conservatively rather than inverted.

### P1 — stale comparison authority survived preference changes

An original free-text comparison could be recomputed from the old question after context invalidation, allowing `choose_comparison` to reuse it. Raw and explicit comparisons now use the same active-context authority and require an explicit restart after invalidation. Focus still does not select; catalog selection is a separate action.

### P1 — valid bounded sessions exceeded caller/runtime budgets

On a disclosed synthetic 70,000-record catalog with a 10,000-record candidate pool, 20 paginated turns took approximately 17 seconds and 204,335 SQL statements; inventory exceeded a 35-second test deadline. Batched facet reads, one request-local context-bound pool, cached baseline work, deduplicated name facets and page-only inventory materialization reduce the serial pagination case to approximately 1.3 seconds/3,449 statements and inventory to approximately 0.5 seconds/2,736 statements in this environment. Dedicated tests cover ownership, context invalidation, bounded batches and page semantics.

**Release hold:** 16 simultaneous synthetic requests still exceeded a 40-second diagnostic deadline. This is not a Cloud Run measurement, but it means the historical 1-CPU/concurrency-16 configuration is not validated. Serial CI results cannot approve promotion. Stage without traffic, measure actual cold/warm and concurrent behavior against the Node caller budget, and review any required resource/concurrency change separately. No timeout or Cloud Run setting was silently increased.

### P1 — dormant money inputs silently coerced invalid amounts

Observation and verified-sale imports accepted booleans, strings and fractional values through `int()`, including negative fractions becoming zero. They now require nonnegative integer minor units within SQLite's range before persistence; unknown observation price remains supported. Tests prove invalid inputs cannot create monetary evidence. This hardens a dormant future feed boundary and does not enable ingestion or payments.

### P2 — deeply nested JSON dropped the HTTP connection

A 20,001-byte nested JSON request was under the body-size cap but raised an uncaught recursion error, causing a transport failure and caller retry. The parse boundary now returns a generic bounded HTTP 400; an actual local HTTP test verifies rejection and continued service health.

### P2 — dismissals became impossible to undo

Scope/preferences cleared shown-card membership while retaining feedback, so a dismissed and now-hidden card could never be cleared. Clearing an already stored reaction is now permitted across relevant context resets; it cannot introduce arbitrary unseen feedback. New-goal behavior and separate ownership assertions remain explicit.

### P1 — hard species exclusions treated unknown membership as safe

A release-positive recommendation could include a source-classified Pokemon without a dex facet despite an explicit species exclusion. Such unknown-membership records (including unclassified records) are now withheld while the hard exclusion is active unless qualified character evidence exists. Current, provenance-bound Trainer/Energy records remain outside the primary-Pokemon species constraint. Coverage states withheld counts and does not claim exclusion of artwork cameos. The six qualified name affiliations participate consistently in positive matching, liked examples and exclusions.

### P2 — hard release language was softened

A supported `only from <one known release>` constraint now becomes hard release scope. Ambiguous or unknown exclusive-release language remains a durable clarification gate rather than silently broadening to other releases. Soft release preferences retain union/ranking behavior and are not converted into hard filters.

### P1 rollout guard — old deployment helper was unsafe for this handoff

The older helper could create a service account after a failed describe and immediately move traffic. The new existing-service helper and runbook use exact immutable images, no-traffic staging, private-access/configuration/identity checks, artifact-backed acceptance, explicit promotion and bounded rollback ownership. They create no accounts, grants or credentials. Local mocked and real local HTTP-to-Node checks validate helper behavior; they do not prove live IAM, image provenance or cloud readiness.

### P1 — legacy exploration overstated offer readiness

The older graph exploration response derived `ready_for_offer_tracking` from structural `match_eligible`, unlike the new catalog-only journey. It now keeps offer/physical/transaction/public flags false and exposes catalog selection and structural eligibility as separate facts. Exact catalog selection remains possible; no source or copy authorization is added.

### P1 — real-catalog character discovery missed supported ex records

The first expanded CI run at `873740df` found **27/34** frozen tasks passing: all 100 supported records were exact-ID selectable, but seven character-continuation/inventory tasks returned no required anchors. Six affected SV4A ex source files omit `dexId`; current facet-only candidate generation correctly excluded them, exposing a discovery-coverage gap rather than an identity failure. The initial receipt is preserved at `sandbox/collector_journeys/supported-pilot-review-v1/initial-873740df-summary.json`. Frozen question expectations and physical/selection gates remain unchanged. The follow-up adds only six exact-source-bound name affiliations, with inspected pinned Pokemon/EX source text, current support/identity and rights bindings, and unanimous current Japanese base-name anchors. They carry a distinct derived-evidence reason; they are not dex IDs asserted by the target source, stored dex facets, physical equivalence or approvals. The original stored catalog and import manifest remain unchanged. Runtime revision now binds this helper, its frozen bindings and source classification. Further cohort character gaps remain separately visible.

## Remaining activation and product gates

- Centralize a positive physical-printing/copy authorization predicate before enabling any marketplace source. Legacy title/visual resolution still ultimately depends on structural `match_eligible`; collector safety does not authorize those older ingestion paths.
- A supported cohort is not a procurement allowlist. Audit exact printing/copy evidence separately before any offer join.
- Real-user usefulness remains unmeasured. The supported-pilot diagnostic is independently authored after code inspection, not a blinded evaluation or population accuracy estimate. Its report retains failed tasks, partial anchor recall, facet relevance, provenance correctness and selectability separately.
- Authenticated durable sessions, resume UX, stale-revision restart/reconfirmation and actual Pivota operation registration remain application work. Caller-owned transcripts are not authenticated persistence.
- Public catalog display, live marketplace ingestion, automatic offer joins, physical approval, purchasing, payment and transaction readiness remain disabled.

## Legacy compatibility adjustment

The original eight-journey, 39-action suite remains intact. The compatibility version changes only three English Yuka Morii page expectations to require blocked selection and identity holds on every candidate. This is a justified tightening if the real-catalog replay confirms those pages; it is not improved recommendation accuracy. Original failed receipts remain distinct from the versioned success report.

## Validation and delivery evidence

Follow-up local focused aggregate: **196 Python tests passed**, **16 Node tests passed**, and **13 journeys / 42 original Python HTTP-to-Node prefix requests passed**, with synthetic database bytes unchanged. Additional actual HTTP-to-Node tests exercise the six pinned targets with synthetic current anchors, malformed proof rejection and feedback/exclusion behavior. Independent reviews reran overlapping subsets; counts must not be added. The first pushed CI executed 688 Python tests with 2 skips, Node 15, HTTP 42 and real-catalog legacy 39 successfully, then correctly failed the initial 27/34 pilot diagnostic. The follow-up exact-commit CI must prove the unchanged real-catalog questions, bounded runtime and final container.

Final exact-commit CI and diagnostic receipts are the authoritative aggregate result. Local source materialization was Git-blob-SHA verified but incomplete for ten manifest inputs over the connector's size limit, so local full-suite errors caused by missing historical/catalog inputs are not reported as passes. The expanded CI rebuilds the real pinned catalog and runs the full Python suite, Node tests, 13-journey/42-prefix HTTP rehearsal, 8-journey/39-prefix identity-holds compatibility suite, supported-cohort diagnostic, bounded runtime measurement and Docker build. Catalog input files and manifests are unchanged by these patches.

Deployment is handed to the user's existing Pokémon session because no authenticated GCP execution route is available here. No cloud revision, image deployment, traffic promotion or live IAM verification is claimed. The historical rollback receipt names `pokemon-commerce-index-00043-2x6`; the operator must verify the actual live state before staging. See `PRIVATE_STAGING_ROLLOUT.md` and the revised `BUILD_SEQUENCE.md`.

Report engineering correctness, collector usefulness, data coverage, physical-printing accuracy and live-market readiness separately. A green test suite establishes none of the latter four by itself.

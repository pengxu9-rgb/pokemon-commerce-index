# Discovery continuation — 4 October 2026

## Baseline and scope

This continues the independently reviewed `024a72d79f30198301ca538cc818d07577343195` implementation. It addresses the supported cohort's 21 character-evidence gaps and the HTTP concurrency failure, and freezes a fresh 30-question collector evaluation before executing it. It does not enable public display, marketplace ingestion, physical-copy approval or Buy&Ship transactions.

## Source-qualified character coverage

All 21 missing supported SV4A records are exact-source-pinned Japanese ex records. Their upstream files explicitly declare Pokemon/EX but omit `dexId`. The review checked every target's SHA-256 and Git blob SHA and 90 exact-base-name upstream anchor files representing 115 catalog variants. Names and current single-species facets agree, including the exact regional name パルデア ドオー; no broad substring or generic name fallback was introduced.

The existing six bindings are unchanged. Twenty-one additional bindings use the same identity, support digest, classification, rights and unanimous-current-anchor checks. Target/support/rights drift, a conflict among current anchors, or loss of all qualifying anchors withdraws the derived affiliation. Reasons explicitly state that the target source did not assert a dex ID. No stored target dex facts, source catalog bytes, catalog imports, identity holds or physical/offer permissions change.

The first full-catalog CI at 7382318 confirmed 63 explicit character facets, 27 separately labelled derived affiliations, zero unresolved Pokemon records and 10 non-Pokemon records. The new 21-target diagnostic passed 21/21; the unchanged pilot passed 34/34. The local 21/21 diagnostic uses actual source-backed targets/anchors in a partial reconstruction; it exercises structured character preferences and is not natural-language recall or population accuracy.

Source receipt: `catalog/character-affiliation-gap-review-v1.json`. Full-catalog check: `python -m scripts.audit_character_affiliation_gaps --db <pinned-db> --output <new-report.json>`.

## Bounded HTTP work and caller behavior

The old threaded HTTP server allowed every request to start expensive catalog computation. On the same synthetic 70,000-record database and 10-second client budget, the original 024a72d implementation timed out all 16 burst clients; work continued after the clients stopped waiting, and the subsequent recovery request also timed out. The original failure and preflight failure receipts are preserved.

The revised server defaults to one active catalog computation and at most four briefly waiting requests, with a 0.25-second queue wait. Excess work receives an explicit `503 catalog_busy`. An eight-second cooperative computation budget interrupts SQL and checks bounded Python work on completion; it is not a hard preemptive wall-clock guarantee. For the internal catalog service, snapshot replacement or ordinary mutation causes a fail-closed response requiring restart. This protects computation, not the total count of HTTP connections or threads, and is not adversarial file attestation. Health requests bypass catalog work. Compute capacity is released before response delivery, including client disconnects.

Only three fixed parser vocabularies are reused inside a single request. No user session, preference, ranking or inventory state is cached across requests. Currentness checks include main/temp schema and transaction changes. The runtime revision binds the new helper, so prior sessions require restart and target reconfirmation.

The Node caller does not automatically retry explicit computation-budget or snapshot-change errors. Busy responses can delay the single retry according to a numeric Retry-After hint, capped at one second; other transient errors retain the configured delay. It retains the existing 10-second per-attempt budget; timeout inflation was not used as a fix.

### Local synthetic HTTP evidence

Under one-CPU affinity, a 16-client burst with one compute worker accepted one request and rejected 15 as busy; the accepted work completed in approximately 0.61 seconds, with about 65 MiB process peak RSS. Two workers accepted two/rejected 14 in 1.25 seconds, about 85 MiB; four accepted four/rejected 12 in 2.55 seconds, about 130 MiB. More threads reduced accepted throughput in this environment.

These are load-shedding and recovery results, not 16 successful collector tasks and not a Cloud Run capacity test. They support the protective one-worker default. Actual staging cold-start, sustained throughput, overload rate, user-visible recovery and memory still require deployment measurement. No Cloud Run configuration was changed.

Receipts and reproducible commands are in `sandbox/collector_journeys/runtime-admission-v1/`. CI adds the same actual-HTTP benchmark against the complete pinned catalog and retains its counts for accepted, overloaded, deadline, transport and other outcomes separately.

## Frozen independent collector evaluation

The new 30-case suite was frozen before any case execution or implementation tuning against it. It uses raw collector questions and separately evaluates candidate relevance, evidence honesty, clarification usefulness, continuity and task progress. It includes preference changes, exact illustrator/release requests, comparison followed by separate selection, and unknown budget/grade/aesthetic/market facts.

Questions SHA-256: `2c6013fe0362e0eb9164063e7184ad264ae337c363a15e2eb9b17e4ca0a03ab1`.

The baseline preflight found 55 of 65 manifest inputs locally available. All 30 cases in that local preflight are explicitly **not executed**. Do not convert missing execution into passes, failures or a usefulness percentage. CI executes both the immutable 024a72d baseline and current implementation against the same full pinned snapshot, retaining separate raw prefix responses and scoring sheets. Historical baseline failures are diagnostic; current safety/execution/integrity failures fail the job. Product limitations remain in the denominator; engineering CI may pass while product constraints fail. Actual human collector evaluation remains outstanding even after an independent agent scores these receipts.

## Full-catalog failure retained and corrective work

The first continuation CI [37168912488](https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/37168912488) correctly failed at `7382318`. Source qualification passed, but the new 27-pin helper repeatedly materialized the full corrected-facet view: direct recommendations took 12.46–17.40 seconds and hit the eight-second HTTP budget. Legacy replay finished 33/39; one failed initial request left five follow-ups unexecuted. The 30-case evaluation recorded 15 new timeouts plus two existing routing errors, compared with two routing errors at the unchanged baseline. No safety violation was observed. The original receipts and SHA-bound failure summary are retained; these failures must not be replaced by small-fixture successes.

The helper correction batches complete current-anchor and target-facet evaluation instead of rescanning the effective view for every pin/name. An exact published-code oracle verifies identical complete proof objects, representative anchors and hashes under ordinary, stale and conflicting metadata. The effective corrected view is preserved; raw facets are not substituted. Recommendations with no positive collecting axis defer unused affiliation work. Subjective notes remain explicitly unapplied to ranking, so their changes can reuse a request-local candidate pool while regenerating the displayed notes and still withdrawing prior target/comparison authority. A literal substring rejection avoids compiling a boundary regex for catalog names absent from the question; the original boundary regex still decides possible matches. More than 4,000 equivalence cases cover Unicode, punctuation, empty terms and embedded-name boundaries. A denser synthetic fixture with 70,000 distinct names, 2,497 active official overlays and 10,000 candidates retains its initial failures; its corrected actual-HTTP page and note-update requests take approximately 1.6–1.7 seconds, pending full-catalog confirmation.

The original fresh questions are now disclosed development diagnostics. Their results exposed two routing failures (a reviewed English release name with an exact coordinate, and a two-number comparison with one shared explicit scope), plus ignored suffix/conjunction constraints and broken clarification continuation. Any corrections must retain the frozen questions and expectations and be rescored using actual responses. Later independent acceptance requires a fresh cohort; current agent scoring is not human collector testing.

The bounded routing corrections now include:

- A single reviewed English rendering, “Shiny Treasure ex,” bound to the existing exact corrected Japanese release row, official page hash, evidence and rights. Responses disclose that the English rendering was reviewed rather than publisher-provided. Any bound-record drift disables it; original upstream source text remains unchanged.
- A two-number comparison may share one explicit language/release across a bare conjunction. Conflicting or absent scope remains unresolved. Comparison, exact focus and separate selection retain distinct authority.
- An explicit ex qualifier filters source catalog titles. English requires a separate token, so ordinary Toxapex does not qualify merely because its name ends in those letters. This is not a new verified mechanic or physical-copy fact.
- Explicit species-by-illustrator wording intersects current evidence, including qualified derived affiliations; typed optional preferences retain their existing soft behavior. Unknown or multiple artists prompt a selection-blocking clarification. Only a later explicit current artist answer resolves that hold; stale preferences cannot self-authorize it. Changes still invalidate selection/comparison authority.
- A general collecting goal can continue through a current exact illustrator reply. Aesthetic notes remain explicitly unverified and unapplied to ranking.

A one-day-retention private CI artifact now preserves a compressed, read-only diagnostic snapshot and hashes to reproduce full-catalog problems. The database is not committed to Git and no public catalog access is enabled.

## Release and next steps

1. Require exact-commit Python, Node, legacy, source-gap, runtime, frozen-evaluation and Docker checks. Inspect failures rather than updating frozen expectations to make them pass.
2. Independently score the new evaluation's actual responses; choose the next discovery improvements from concrete failed collector tasks.
3. Deploy privately through the user's existing Pokémon session, with no-traffic staging and the existing rollout gates. Verify source/image/runtime provenance and coordinated caller rollout. Overload responses are unsuccessful work and cannot count toward the required completion rate.
4. Continue authenticated task persistence, refinement/comparison UI and a small actual collector trial. Catalog coverage and machine diagnostics do not replace a useful user experience.
5. Keep fresh offers, physical-copy verification, landed costs, merchant reliability and confirmed Buy&Ship handoff dependent on separately authorized evidence/feed work.

Report engineering correctness, collector usefulness, catalog coverage, physical-printing accuracy and live-market readiness separately. Full-catalog final CI and deployment receipts supersede local partial/synthetic results only for the claims they actually measure.

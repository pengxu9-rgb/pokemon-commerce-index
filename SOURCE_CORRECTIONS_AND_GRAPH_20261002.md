# Source corrections and artwork graph — 2 October 2026

## Delivered

The runtime now uses [47 immutable, ordered inputs](catalog-build-manifest-corrections-v1.json). It contains **70,006 internal source-version/family records**, including one new source-only 154/SV-P family. There are 45,438 language/set/number groups, 27,095 Japanese records and 42,911 English records. These counts do not establish a complete physical-card catalog.

[Thirteen correction events](catalog/source-corrections-v1/corrections-v2.jsonl) restore ten printed artist credits to effective retrieval, scope two professor subtitles to 021/SV-P and 022/SV-P, and correct the 153/154 reference boundary. Raw seeds, HTML disagreements and all previous evidence remain intact. The original PTCG reference 45644 still records153 in the audit table; effective153 exposes only 45643, and new source namespace `official-printed-coordinate:45644` belongs to 154. The new family has unknown rarity and no matching/display permission.

The ten corrected artists increase effective illustrator coverage from 45,500 to 45,510 source identities. Raw HTML/seed conflicts remain separately reported. Professor subtitles are exact Japanese publisher-image readings, not globally translated aliases or physical-copy approval. A generic professor title prompts clarification; wrong numbers, multiple professors and unsupported named English professors abstain.

## Evidence and invalidation

Corrections bind complete raw card/reference/facet snapshots, exact latest printing-source parent JSON and actual source-image reviewer records. SQL recomputes current evidence per request. Seed, membership, facet, permission or parent drift removes the positive correction. Known wrong artists/references remain quarantined rather than reappearing through stale fallback. A missing correction-aware view fails closed on a correction-capable snapshot.

Original rows are preserved: 70,005 cards, 24,039 references, 86,302 facets, 2,497 official metadata events, 280 coordinate-family events and 23 printing events. Only one card and one reference are added. [Source preservation](catalog/source-corrections-next-v1/source-preservation-v2.json) checks full rows; all 45 earlier manifest steps are unchanged.

154 remains a source-only family even after a mutable attribute, provenance or version field drifts. Historical evidence and the reserved source namespace guard direct selection from broad browsing. Actual correction creation time is recorded; earlier timestamp drafts are retained and excluded from the runtime manifest.

## Artwork expansion

A [frozen 20-pair cohort](catalog/relationship-expansion-v2/cohort.jsonl) spans 20 Japanese releases and distinct subjects. Forty pinned source files and 40 actual source-image hashes were checked. Two distinct AI agents inspected the images separately; the root did not open first-review verdicts before saving its own review. All 20 agreed on artwork composition and printed coordinates. One transient image-fetch failure recovered on a bounded retry and remains recorded.

There are now **23 verified artwork-only pairs and 634 proposed pairs** among 657 latest pair states. Thirty-six proposals still touch disabled identities. Stock-image differences such as foil patterns remain explicit: every new finish outcome is `not_comparable`. No localization equivalence, price comparability, physical edition, copy condition, live-offer or public-display approval is added.

These agents inherit the same model. Separate verdicts are useful review evidence, not proof of independent model errors or a population accuracy score.

## Rehearsals and quality

The 24 new authored questions were frozen before execution. A source-qualified fixture typo in one English Abra variant was corrected before any query execution; both versions remain. The pre-correction catalog supports 8/24 expectations. The first integrated pass supports 22/24: two failures exposed card-ID language prefixes being interpreted as the requested target language. On unchanged expectations, the corrected pass supports 24/24.

An integrated regression initially lost two earlier “which professor is printed” questions by treating “professor is” as a named-person constraint. That initial report remains. The final replay supports all 24 new expectations and preserves 20 printing-source questions, 18 release-name questions, 20 family queries, 31 graph responses, 14 exact catalog-detail checks and the new source-family selection guard. [Final replay](catalog/source-corrections-next-v1/final-integration-rehearsal-v2.json).

Adversarial checks exposed and repaired attribute-only family selection, fabricated reference rarity, missing-view raw fallback, wrong/unknown artist constraints, conflicting professor names and artist inquiry regressions. **494 Python and 11 Node tests pass.** Tests verify invalidation and source constraints, not real-marketplace precision. [Validation](catalog/source-corrections-next-v1/integration-validation-v1.json).

[Whole-catalog audit](catalog/source-corrections-next-v1/whole-catalog-quality-v2.json) verifies 47 input hashes, no structural/foreign-key failures and 3,038 cached official-page extraction comparisons. Existing gaps remain: 20,090 unverified version labels; 7,745 missing Japanese release names and 8,114 missing dates across 200 groups. The 597 official pages without a rarity icon remain unknown.

Six additional mixed natural-language collector questions are retained as a separate [diagnostic](catalog/relationship-expansion-v2/natural-question-diagnostic-v1.json). Five ask for release/card clarification; one requires market evidence. No complete answer is claimed. The graph contains useful facts, while a multi-card comparison/orchestration path remains necessary to answer those whole questions.

## Next steps

1. The [scoped two-card comparison tool and agent flow](TWO_CARD_COMPARISON_20261002.md) is now implemented. Six existing source-led questions meet their frozen expectations, preserving three release confirmations. Continue fresh question evaluation and qualified graph coverage while keeping physical-copy and market evidence separate.
2. Continue qualified artwork expansion and prioritize explicit source conflicts rather than approving proposals by similarity alone.
3. When Buy&Ship supplies an authorized search/listing feed, credentials and data-use scope, run real-listing exact-card/variant/grade calibration, freshness/quota measurement and URL transaction handoff. Ask indexing and seller/landed-cost ranking still have no live observations.

The staging service is a private, read-only catalog snapshot. Pivota's default-disabled caller contract is prepared; actual service registration/identity and authorized market ingestion remain open. [Deployment](CLOUD_RUN.md).

The first cloud card-detail comparison stopped on one field: `rarity_correction.applied_at` differs because local and container snapshots were rebuilt at different times. [Both original responses and the exact difference](cloud-verification-20261002-source-corrections-card-difference-v1.json) remain. Only that import bookkeeping field is excluded from semantic comparison; source retrieval, review, correction creation, coordinate and rarity evidence remain exact. Two additional focused comparison tests pass. No deployed runtime or data changed for this repair.

Private staging revision `pokemon-commerce-index-00030-x8r` passes [160 authenticated logical checks](cloud-deployment-20261002-source-corrections-v1.json), with two unauthenticated 403 checks. No transport errors were recorded in the final run. Final source, graph, card-detail and source-family selection behavior agrees with the local snapshot.

# Artwork difference and version-boundary calibration — 2 October 2026

## Delivered

The graph now has **63 verified same-artwork pairs, 594 proposals and 11 source-qualified artwork differences** across 668 latest pair heads. Thirty-six proposals with identity blockers stay held. The eleven differences are append-only `same_artwork/rejected` events with structured review evidence; a rejection or absent edge alone is never interpreted as a different-artwork fact.

`/card-comparison` exposes `reviewed_difference_links` only for those exact source endpoints. `/catalog-neighborhood` returns them separately as `reviewed_artwork_differences`, outside the positive relationship list. Changed endpoint snapshots, identity blockers or a newer pair decision invalidate their use. Sibling versions do not inherit either a same-artwork approval or a reviewed difference. Physical printing, finish, actual-copy condition, price equivalence, display and automatic live-offer permissions remain unapproved.

Catalog counts remain **70,006 internal source-version/family records**, 45,438 language/set/number groups and 33,543 structurally eligible records. The [49-input manifest](catalog-build-manifest-artwork-controls-v1.json) preserves all 48 previous steps. [Preservation proof](catalog/artwork-controls-v1/source-preservation.json) checks fourteen original raw/evidence tables and all 720 earlier graph events. Only proposed AI import application timestamps are excluded from graph equivalence; actual source/review fields remain compared.

## Source and image reviews

[Eighteen frozen pairs](catalog/artwork-controls-v1/cohort.jsonl) comprise twelve same-single-Pokémon challenges assembled from different coordinate candidates, and six previously reviewed same-artwork controls. All thirty distinct pinned source files and thirty distinct image hashes were checked across thirty-six endpoint memberships. Images remain local temporary inspection files and are excluded from GitHub and the runtime image. One existing Pokémon TCG image source required an explicit bounded PNG source rule; the original allowlist hold and recovery remain recorded.

The root/OpenAI reviewer inspected all six actual image sheets and saved eighteen verdicts before Vertex began. Gemini 3.8 Flash received only frozen source images and expected identities, with no earlier review verdicts. Initial results were eight qualified differences, six positive-control agreements and four identity holds. Three holds showed matching numerical readings with different zero padding, but the model still declared mismatch. One bounded clarification review covered all four uncertain identities, explicitly allowing leading zeros and forbidding an invented denominator. Original findings and prompt protocols remain intact.

Final results are **eleven qualified differences, six positive controls and one hold**. The six controls add no new positive approvals. Model-family provenance, actual Gemini model versions, source/response/protocol hashes and full review-record hashes remain bound. The root's exact serving model version is not exposed. [Quality and chronology](catalog/artwork-controls-v1/quality-summary.json), [first adjudication](catalog/artwork-controls-v1/review-summary.json), [final adjudication](catalog/artwork-controls-v1/review-summary-final.json).

### The retained promo-number hold

For `en:SVP:037/225:holo_set_logo`, both reviewers observe only **037** printed on the English Cleffa image. The source catalog's denominator **225** is not printed there. Although both images show different scenes, that complete claimed printed coordinate is unconfirmed, so no graph difference is imported for this pair. Raw catalog identifiers and variant labels stay preserved; this is a bounded review hold, not a global rejection of promo cards.

Catalog coordinates can contain source inventory conventions. They must be separated from observed printed number text before broader promo-number matching or physical printing conclusions. Ball/mosaic/foil looks in other stock scans also remain observations rather than approvals of their declared physical variants.

This deliberately constructed cohort is not a random marketplace sample or independent ground truth. Root familiarity with the positive controls, shared source errors, correlated model mistakes and selection bias remain limitations. No agreement percentage is claimed as accuracy.

## New question diagnostic and routing repairs

[Fifty-four questions](catalog/artwork-controls-v1/questions-frozen-v1.jsonl) were frozen before image inspection and execution: thirty-six authored visual questions, twelve sibling-version questions and six blocked-identity questions. Visual wording includes English, Japanese and Chinese, reversed endpoints, shared names, same numbers, regional equivalence, foil, PSA/condition, scarcity and current price. The sibling/hold questions reuse limited templates, so these are not fifty-four independent language patterns or held-out user questions.

The original diagnostic mistakenly called the task `card_comparison`; the API task is `two_card_comparison`. The untouched original file/report and [uniform contract correction](catalog/artwork-controls-v1/question-contract-correction-v1.json) preserve that mistake. The original zero matching labels is a diagnostic contract error. Against the correct task name, initial routing was **47/54**. One Chinese “比较” phrase and six alphanumeric exact catalog IDs exposed actual routing gaps. After the parser repairs, all **54/54** route to scoped two-card comparison. Questions, coordinates and approval constraints were not rewritten.

The [final local replay](catalog/artwork-controls-v1/local-replay-v2.json) passes **105/105 checks**: fifty-four questions, thirty unique exact pairs, six actual Node caller journeys, eleven negative-evidence neighborhoods, catalog status and three rejected malformed requests. All six sibling controls remain unapproved, blocked identities do not gain artwork approval, and the promo hold receives no invented difference. These are engineering acceptance checks, not complete collector answers or measured real-listing precision.

**527 Python tests and twelve Node tests pass.** Four initial focused errors exposed SQLite-row/dictionary validation input handling and were repaired before final execution. Tests cover difference provenance, snapshot/head drift, missing evidence, disagreement, model failures, sibling boundaries, withdrawals, newer decisions, explicit alphanumeric IDs and missing promo denominators. [Test evidence](catalog/artwork-controls-v1/test-validation.json).

The previous forty-pair expansion preserves 102 local checks, the earlier six comparisons preserve thirty, and the combined source regression preserves 82 questions, 31 graph responses and fourteen exact card details. These remain engineering regressions; current cloud replays are recorded separately below.

## Private staging

Revision **`pokemon-commerce-index-00033-kkh`** serves all private staging traffic. The [completed control cloud replay](catalog/artwork-controls-v1/private-cloud-replay-v3.json) passes **107/107 checks**, including two unauthenticated 403 denials. Runtime, snapshot and evidence bindings agree with the local result; no final transport errors are recorded. Actual Node calls use the existing client timeout/retry policy.

The first cloud report stops on a recorded Node `catalog_timeout` after 84 successful HTTP checks. A subsequent diagnostic attempt fails while saving its report because a route variable shadows the question-file path. That diagnostic bug was fixed and the entire suite rerun on the same deployed image; unsaved results are not counted as proof. [Original failures and hashes](catalog/artwork-controls-v1/diagnostic-failures.json). No serving permissions or data were changed for those diagnostic repairs.

The current revision also passes the [previous expansion replay](catalog/artwork-controls-v1/legacy-expansion-cloud-v1.json) **104/104** and [six-comparison replay](catalog/artwork-controls-v1/legacy-six-cloud-v2.json) **32/32**. Together the three completed cloud reports record **243 passing engineering checks**, including six repeated unauthenticated 403 checks, rather than 243 unique user scenarios. The first six-comparison cloud attempt also recorded a Node timeout; both timeout failures remain preserved and only complete reruns count toward the passing total.

A [sample of 35 received journey requests](catalog/artwork-controls-v1/cloud-latency-scope.json) records HTTP 200 responses and a maximum service request latency of 0.107 seconds. Those logs cover received service requests only: they do not locate the client timeouts or establish end-to-end availability or latency. The existing ten-second client timeout policy remains unchanged. [Delivery validation](catalog/artwork-controls-v1/delivery-validation.json) binds all four final local/cloud reports to the current runtime and snapshot, verifies all 49 input hashes, and preserves the previous 48 manifest steps.

## Next priorities

1. Add a source-qualified number-evidence model separating canonical inventory coordinates from observed printed numbers, especially promo prefixes and unprinted denominators. Preserve old identifiers and quarantine ambiguous mappings.
2. Scale qualified same/different artwork review with harder controls: similar scenes, reprints/crops, artist and character ambiguity, and unclear surface/stamp evidence. Report coverage, disagreements and abstention without treating AI agreement as population precision.
3. Broaden independently sourced collector question wording and register an authorized internal Pivota pilot caller. Existing operator replays do not establish active production registration.
4. When an authorized listing feed and data-use scope arrive, calibrate real listing/card/version/grade and freshness, then add fresh asks, landed quotes and Buy&Ship URL handoff. Live observations remain zero; paid-price and liquidity claims still require separate evidence gates.

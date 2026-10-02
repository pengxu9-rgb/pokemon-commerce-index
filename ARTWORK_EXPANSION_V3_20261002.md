# Cross-region artwork evidence expansion — 2 October 2026

## Delivered

Forty additional Japanese/English pairs across twenty Japanese releases now have two separately recorded image reviews. The latest graph has **63 verified artwork-only pairs and 594 proposals** among 657 pair heads. Thirty-six proposals with identity blockers remain held. There are no new physical-printing, condition, price-equivalence, public-display or automatic-offer approvals.

The catalog remains **70,006 internal source-version/family records**, 45,438 language/set/number groups and 33,543 structurally eligible records. It is not a complete physical-card or commerce catalog. [Source preservation](catalog/relationship-expansion-v3/source-preservation.json) confirms fourteen raw/evidence tables, all 680 prior graph events and the previous 47 manifest inputs are preserved. Only proposed AI import application timestamps differ between rebuilt snapshots; original evidence and review fields remain identical.

The new [48-input manifest](catalog-build-manifest-artwork-v3.json) appends one immutable file of forty qualified events. Original source and review artifacts remain intact; rejected or missing evidence would stay proposed/held rather than being converted into a negative graph fact.

## Review evidence and limits

The [cohort](catalog/relationship-expansion-v3/cohort.jsonl) selects two currently eligible proposals per Japanese release, with a deterministic diversity ordering. All eighty pinned source files and all eighty actual image hashes were checked. One image connection failure recovered; the original failed attempt and retry remain recorded. Source images remain in local temporary inspection files and are not published in the runtime image or GitHub repository.

The root reviewer inspected actual images at original resolution in ten labeled sheets and saved its complete findings before Vertex review started. Vertex Gemini **3.8 Flash** received only those source-hashed images and expected printed identities; it received no first-review verdicts. Both printed names and numbers must match before an artwork decision qualifies. Three initial Vertex calls timed out; separate retry records recovered, preserving the failures and linking their hashes into the final reviews.

All forty pairs agree on illustrated composition and coordinates. Records now preserve model family, actual Gemini model version, prompt/response/protocol hashes where available, and both full review-record hashes. The root's exact serving model version is not exposed and is recorded as unknown. [Quality summary](catalog/relationship-expansion-v3/expansion-quality-summary.json).

This cohort is drawn from existing AI same-artwork proposals and excludes blocked identities. It is enriched for likely matches. Forty agreements are **not** an accuracy score, a random sample, real listing precision or proof of independent model errors. Shared source errors and systematic model mistakes remain possible.

Several stock scans have gold textures, mosaic patterns or ball motifs that differ across regions. Three Japanese scans show a surface overlay even though their selected source record says `normal`. Those observations remain explicit in the review notes; they do not justify changing raw variant labels or approving physical-copy identity. Identical numbers on Paras/Omanyte also stay in distinct language/release namespaces.

## Fresh authored question diagnostic

[Fifty new questions](catalog/relationship-expansion-v3/questions-frozen-v1.jsonl) were frozen before image inspection and before execution: forty complete pair scopes and ten explicit unknown-release controls. They include English, Japanese and Chinese, reversed comparison order, print-run questions, physical-version questions and requests for today's cheaper card.

The forty pair questions use four wording templates with different coordinates; the ten unknown-release controls use one template. This tests data/scope variation across five patterns, not fifty independent language patterns or broad natural-language generalization. The next diagnostic should broaden wording and include visual negative controls.

The [first pre-import replay](catalog/relationship-expansion-v3/question-replay-before-artwork-v1.json) meets 44/50 scope expectations. Six failures exposed decimal release codes matching shorter prefixes: examples include `SWSH12.5`, `SV03.5` and `ME02.5`. The code matcher now respects periods and hyphens, and preserves explicit unknown `SWSH` codes. Expectations and questions were unchanged.

The [final local replay](catalog/relationship-expansion-v3/local-replay-v1.json) passes **102/102 checks**: fifty natural questions, forty exact reviewed pairs, six actual Node caller journeys, three legacy source/scope guards, catalog status and two rejected malformed requests. All fifty questions meet the frozen task/scope expectations. The ten unknown releases return no approved artwork link; physical/price claims remain false throughout. This is authored development acceptance, not independent held-out user accuracy or complete answers.

The six prior comparison questions also preserve their thirty local checks. The existing combined source regression preserves 82 questions, 31 graph responses, fourteen exact card details and source-only family selection guards. **513 Python tests and twelve Node tests pass**, including dotted/hyphenated release guards and three new Vertex/provenance parsing tests. [Test evidence](catalog/relationship-expansion-v3/test-validation.json).

## Private staging and delivery

Revision **`pokemon-commerce-index-00032-rdq`** serves all private staging traffic. The [new cloud replay](catalog/relationship-expansion-v3/private-cloud-replay-v1.json) passes **104/104 checks**; one transport failure recovered through bounded retry and remains recorded. The [six prior comparison cases](catalog/relationship-expansion-v3/legacy-six-cloud-v1.json) also pass **32/32 checks**, with no transport errors. Both cloud reports include two unauthenticated 403 checks and agree with local semantic responses. These are 136 engineering checks across two reports, including four repeated authentication denials; not 136 distinct user scenarios.

The [delivery validation](catalog/relationship-expansion-v3/delivery-validation.json) binds both cloud reports to the new revision and local snapshot, verifies runtime/evidence hashes and all 48 manifest input hashes, and confirms preservation of the original 47 steps. Cloud access remains private; active Pivota registration, listing feeds and price/transaction evidence are still pending. The full prior 160-check source-correction cloud suite was not rerun on this revision; the existing 82-question source regression was rerun locally.

## Next sequence

1. Add source-qualified same-Pokémon/different-artwork controls and conflicting version cases. Measure disagreement/abstention before scaling positive approvals from a selected queue.
2. Expand qualified artwork coverage while keeping source labels, physical finish, localized counterparts and price units separate. Prioritize observed collector requests when independent demand evidence exists.
3. Register a deliberately authorized internal Pivota caller for a collector pilot. The existing Node connector is prepared; active production registration and service identity are still pending.
4. When Buy&Ship supplies an authorized listing/search feed and data-use scope, calibrate actual listing identity/variant/grade, freshness and quota, then add prices and URL/quote handoff. Current live observations remain zero.

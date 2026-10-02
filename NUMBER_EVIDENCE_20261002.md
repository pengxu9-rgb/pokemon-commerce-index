# Catalog coordinates and visible number evidence — 2 October 2026

## Delivered

The private catalog now separates **catalog coordinates** from **observed stock-image number text**. Existing card IDs, collector numbers, numbering keys and graph decisions are preserved. The `printed_number` field and database column remain for compatibility, with `printed_number_semantics=legacy_catalog_coordinate_not_visual_evidence`. Explicit `catalog_number` and `number_basis=catalog_coordinate_only` fields prevent that legacy name from implying visual verification.

Exact `/catalog-card` and `/catalog-neighborhood` number contexts expose `observed_printed_number` separately. `/card-comparison` exposes each side's `observed_printed_numbers` with exact record IDs; coordinate alignment is explicitly based on catalog coordinates. A sibling version with no review gets no inherited reading. Matching catalog numbers do not establish matching printed text, regional identity, physical printing, price comparability or scarcity.

## Source readings

[Thirty number-evidence events](catalog/number-readings-v1/evidence-v1.jsonl) are extracted from the previous eighteen pairs' separate root/OpenAI and Gemini 3.8 Flash image inspections. This is reuse of existing actual image readings, **not a new AI audit**. All original pinned source bytes and temporary image hashes were checked again, as were the complete review memberships, source references, endpoint snapshots and review-record hashes. Six reused endpoints retain both pairs' review groups; disagreement across any group would become a reading hold rather than picking a favorable result.

The [compiler report](catalog/number-readings-v1/compilation-v1.json) records **29 catalog-text agreements and one catalog-denominator-not-observed result**. Numeric leading zeros are normalized for comparison, but original readings remain visible. Alphanumeric prefixes and denominators are never synthesized or removed to manufacture agreement. Unreadable or conflicting text is held. The evidence is exact source-image text, not assignment of the image to a claimed finish or actual seller copy.

### Cleffa example

For `en:SVP:037/225:holo_set_logo`:

| Field | Value |
|---|---|
| Catalog coordinate | `037/225` |
| Actual recorded image readings | `037`, `037` |
| Number evidence status | `catalog_denominator_not_observed` |
| Printed denominator established | false |
| Catalog identity confirmed by this observation | false |
| Artwork relationship changed | no |
| Physical version, live-offer or price approval | none |

This records what the reviewers could read without overwriting the seed or adding a missing denominator. It does **not** claim that no denominator exists on every physical copy, prove the catalog's denominator convention or remove the previous artwork/identity hold. A later source-qualified mapping or new artwork adjudication needs its own evidence.

## Architecture and guards

`card_number_reading_evidence` is append-only, with consecutive revisions, complete exact endpoint snapshots, source/image hashes and two distinct model-family inspections per review group. Import is atomic and idempotent. Incomplete provenance, substituted image hashes, permission overclaims, stale endpoints and forged outcomes are rejected. Latest holds supersede older usable readings; endpoint drift withholds observed text. No reading is backfilled from metadata. The serving path remains read-only with no AI/network calls.

The evidence table and module are included in collector journey revision binding, so a stale resumed journey cannot silently reuse a different numbering proof. The [50-input manifest](catalog-build-manifest-number-readings-v1.json) appends one evidence input to the unchanged prior 49 steps. Only frozen number evidence enters the container; images, review queues and diagnostic outputs are excluded.

[Preservation checks](catalog/number-readings-v1/preservation-v1.json) compare all 42 prior tables. The only excluded differences are explicitly identified import application times: `applied_at` on identity exceptions, denominator conflict rules and rarity corrections, plus `asserted_at` on imported proposed AI artwork events. Every excluded before/after value is retained. Source/review fields and graph decisions remain compared.

## Coverage and next research

The [coverage report](catalog/number-readings-v1/coverage-v1.json) records **70,006 catalog records, 45,438 catalog coordinates, and only 30 exact source records/coordinates with this number-reading evidence**. The remaining 69,976 exact records are unobserved by this new layer, not automatically invalid or conflicting. Prior Japanese printed-source/alias evidence is still exposed through its existing modules; it is not silently converted into this two-model schema.

[The next 50 research targets](catalog/number-readings-v1/next-promo-research-targets-v1.jsonl) contain 25 English and 25 Japanese coordinates whose source metadata labels them Promo with a fraction coordinate. Selection is deterministic by language/set/number, capped at ten per release namespace, excludes already reviewed coordinates, and records its [selection and hash](catalog/number-readings-v1/next-promo-research-selection-v1.json). These are pending research targets, not 50 completed audits, probable errors or a random population sample. The next task is source-image acquisition and separate number readings, then evidence-backed mapping where the full printed coordinate differs from catalog inventory conventions.

## Verification

**541 Python and 12 Node tests pass.** Fourteen new tests exercise promo denominators, numeric zero formatting, coded prefixes, no metadata backfill, sibling boundaries, stale sources, source/permission/reviewer guards, conflicting readings, revision supersession, atomic import and journey revision invalidation. The initial focused run passed its non-HTTP checks but the HTTP test could not bind a local port under the initial sandbox permissions; the original failure is retained and the complete suite passed after network permissions were granted.

The number layer passes [55 local HTTP checks](catalog/number-readings-v1/local-replay-v1.json): thirty exact source records, eighteen pair comparisons, six untouched siblings and catalog status. The existing artwork diagnostic also passes [105 local checks](catalog/number-readings-v1/artwork-regression-local-v1.json), including the 54 frozen authored questions and six actual Node caller journeys. These are engineering regressions, not measured marketplace precision, complete collector answers or independent ground truth.

Private staging revision **`pokemon-commerce-index-00034-gvg`** serves all traffic. The [number cloud suite](catalog/number-readings-v1/private-cloud-replay-v1.json) passes **57/57** and the [artwork cloud regression](catalog/number-readings-v1/artwork-regression-cloud-v1.json) passes **107/107**: **164 logical engineering checks**, including four repeated unauthenticated 403 denials. One first-attempt `/collector-discovery` connection error recovered through bounded retry and remains in the report. The six actual Node journeys pass using the unchanged caller policy. These counts are not independent user scenarios or service reliability measurements.

[Delivery validation](catalog/number-readings-v1/delivery-validation-v1.json) binds all four complete local/cloud reports to current runtime and snapshot hashes, the exact private deployment image and all 50 input hashes. Live observations remain zero. Fresh asks, landed quotes and Buy&Ship transaction handoff still require the authorized feed and data-use contract.

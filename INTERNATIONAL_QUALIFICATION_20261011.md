# International coverage — second offline implementation stage

This continues the local patch on `codex/international-coverage-20261011`, based on `f499b46f7f0898c5c0478c53fef960d435f1765f`. The original checkout remains untouched. No creator frontend, push, deployment, cloud permission, live ingestion, purchase or payment changes.

## Implemented behavior

The next proposed Japanese batch is now a reproducible **held evidence queue**: 65 existing records across SMH (17), DS (16), SC (16) and LL (16). These scopes come from the committed release-gap audit. Selection evenly bounds the first existing coordinates in each scope; it is not a measured customer-demand or supplier-availability ranking. All 65 source files and the existing reviewed MIT metadata license were checked against the pinned PTCG Git revision and baseline SHA-256 provenance. Source IDs are provider-namespaced; the existing card IDs and references are retained.

All 65 records have unresolved physical printing labels. Their source files contain product-name text, but that text does not prove a product binding or a finish. Four exact cached official card pages have valid historical receipt hashes and coordinates, and **none has a product link**. The other 61 selected coordinates have no cached official card page in this batch. Consequently **zero release names, dates or new physical identities are admitted**. Missing images, offers and physical identities are not interchangeable explanations for these holds.

Stage-3 clarification: the statement above reflects stage 2's narrower `/ex/` and `/products/` product-page allowlist. The later [publisher-caption audit](INTERNATIONAL_PRODUCT_TEXT_20261011.md) finds an SMH `/info/` news article link outside that allowlist. Historical held events remain intact; the news link is not a verified product-release binding.

`coverage_qualification` registers append-only candidates separately from positive release evidence. Each candidate binds the full existing identity/rights snapshot, coordinate siblings, provider references and localized release snapshot. Source revision/hash, inspected time, license hash, rights status, historical retrieval-time uncertainty, provider product-text leads, cached receipt times and explicit hold reasons remain visible as evidence. Source-file retrieval time was historically unrecorded and stays null; the October 11 inspection time does not replace it. `region=ZZ` preserves unknown physical distribution region, while `provisional:ja:<set>` identifies only the existing language/set numbering scope.

The importer can register held evidence work only. It has no admission or automatic promotion branch. Even a later supplied official link must pass the separate existing release-metadata review/import path. Test-only baseline records, malformed fields, missing snapshots, forged approvals, changed sources/references/releases and mismatched coordinates fail closed. Valid ambiguous records and invalid submissions enter quarantine. Re-import adds neither duplicate evidence nor duplicate quarantine entries. Changed source, sibling, reference, release or test-only status marks old candidates stale and retains history.

Internal `catalog-card`, `catalog-search` and `catalog-status` responses expose optional qualification context. Held source product text adds **no search alias**, counterpart edge, release date, source mapping or commerce capability. Matching IDs remain language/variant scoped; shared artwork, translated names, repeated numbers, promos and foil/stamp differences cannot transfer this evidence to siblings. Offers, stock, grading/condition, asking/sold prices and landed quotes remain separate. Buy&Ship remains the intended merchant of record; Pivota does not hold customer funds.

## Before and after this stage

| Measure | Stage 1 | Stage 2 |
|---|---:|---:|
| Internal source-version/family records | 70,006 | 70,006 |
| English / Japanese records | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Distinct internal identity tuples | 70,006 | 70,006 |
| Source-declared variants excluding unverified labels | 49,916 | 49,916 |
| Unresolved labels / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical printing count | Unknown | Unknown |
| Structural matching eligibility | 33,543 | 33,543 |
| Display / image display / automatic offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Catalogue image files packaged | 0 | 0 |
| Inspected source-image subjects / distinct hashes | 1,141 / 1,141 | 1,141 / 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Scoped localization bindings | 60 | 60 |
| Japanese records missing release name / date | 7,745 / 8,114 | 7,745 / 8,114 |
| Held qualification events / distinct subjects | 0 / 0 | 65 / 65 |
| Current / stale qualification events | 0 / 0 | 65 / 0 |
| Quarantine entries | 0 | 65 |

These are internal source inventory and evidence counts. Whole-catalog image availability remains unmeasured. Stage 2 creates no additional translated retrieval gain; the 60 stage-1 scoped bindings remain intact. All 65 selected native-name searches return the same IDs before/after, and explicit English filtering excludes those Japanese targets. The existing resolver is unchanged. Pocket/digital records remain excluded, and the French fixture remains test-only outside the real manifest.

The opt-in `catalog-build-manifest-international-qualification-v1.json` has 67 steps: the exact 65 ordered source-binding inputs, the unchanged stage-1 locales input, and one hash-bound held-queue input. Dockerfile still selects `catalog-build-manifest-source-binding-v1.json`; the snapshot CLI's older default is not used.

## Verification

The final suite runs **654 Python tests: 652 pass, two existing skips**, plus **15 passing Node tests**. The 33 focused qualification/international/release tests pass, including 13 new qualification tests. Read-only CLI/HTTP checks preserve database file bytes. Independent review uses GPT-6.1 Sol high and corrected two findings: a test-only baseline could be counted as a held real candidate, and an audit could pass without checking installation in the actual after snapshot. Both have regression coverage.

The stage-2 audit verifies all 67 input hashes and both preserved prefixes, exact installed queue payloads, exact appended quarantine records/history, all legacy data and 65 unchanged native searches. Idempotent re-import returns `inserted=0, unchanged=65, rejected=0`. Incremental append changes only the new qualification table and appends 65 quarantine entries; **every pre-existing catalogue/trading column remains exact**, including historical timestamps.

Independent full rebuilds generate different timestamps through four existing importers: 657 relationship `asserted_at`, 19 identity-exception `applied_at`, 532 rarity-correction `applied_at`, and two number-rule `applied_at` values. Only those four named bookkeeping columns are excluded from independent-rebuild comparisons. All other old rows/columns match. The incremental append comparison excludes no historical timestamp column.

## Reproduce and rollback

Use fresh output paths and an offline checkout:

```sh
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-pilot-v1.json --db /tmp/pokemon-stage1.sqlite3
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-qualification-v1.json --db /tmp/pokemon-stage2.sqlite3
python3 -m scripts.audit_international_release_queue --before /tmp/pokemon-stage1.sqlite3 --after /tmp/pokemon-stage2.sqlite3 --output /tmp/pokemon-stage2-audit.json
python3 -m unittest discover -s tests
node --test integrations/pivota/*.test.cjs
```

To recompile the queue, supply the existing pinned `ptcg-public` checkout and `release-metadata-next-v1-cache` directory to `scripts.build_international_release_queue`, with `--inspected-at 2026-10-11T10:37:00Z`, `--limit 65`, a stage-1 database and a fresh `--output-dir`. It performs no network calls and refuses changed source bytes, cache receipts or licenses. Raw official HTML is local evidence and is not added to the cloud image. A new inspection produces new immutable candidate events rather than overwriting old evidence.

Rollback this stage by continuing to use the 66-step stage-1 manifest/database and stage-1 application patch, discarding the stage-2 scratch database. Rollback both stages by building from the explicit original source-binding manifest and original commit. Do not delete historical evidence from a shared runtime or reset another session's checkout. The delivered cumulative patch can be reversed only in an isolated checkout where it was applied cleanly. No cloud rollback is required.

## Next justified work

The next batch is evidence completion for this fixed queue, not another arbitrary 65 cards. First qualify exact card-to-product links for the four cached anchors: PTCG IDs 35030 (SMH), 27836 (DS), 28616 (SC) and 26001 (LL). Reuse authorized cached text or reviewed, pinned metadata with receipts; do not manufacture links from names, matching artwork, numbering similarity or TCGdex headers. Product dates must retain language/region and initial-release scope, with missing or multi-product dates left unknown. Obtain exact coordinate text for the remaining 61 selected records only through an authorized source route. Physical finish/edition claims require a separate printing review and do not follow from product metadata.

Customer/query demand and Buy&Ship-confirmed authorized supplier coverage remain missing for real third-language admission. Traditional Chinese is still only a conditional readiness study. This stage does not justify any real language, marketplace-price or artwork import, broad batch or deployment.

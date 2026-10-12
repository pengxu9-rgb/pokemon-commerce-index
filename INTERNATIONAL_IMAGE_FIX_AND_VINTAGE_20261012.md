# Offline identity holds and vintage retrieval expansion — 12 October 2026

This local stage adds 100 Japanese and 25 English localized retrieval bindings to existing records and puts 44 legacy IDs with source-declared size loss on an explicit identity hold. All IDs, source references and historical evidence remain intact. Nine previously structurally eligible records lose that eligibility. No canonical replacement, standard-size sibling substitution, physical verification, new artwork, price, offer or trading permission is created.

Work continues on `codex/international-coverage-20261011`, based on `f499b46f7f0898c5c0478c53fef960d435f1765f`. The preceding staged checkpoint is tree `d00b2a7e21c0a05bc46cec03710934f2daf54e5e`; the final stage14 tree is recorded in the delivery receipt. This is an isolated checkout with local, uncommitted changes. The original checkout and creator frontend were not edited.

## Reproduced coverage

The October 2 source-binding baseline still totals 70,006 internal source-version/family records: 42,911 English and 27,095 Japanese, across 45,438 language/set/number groups. There is no difference in those totals. The table's historical `printings` label does not establish 70,006 independently verified physical cards. The 70,006 internal identity tuples include 49,916 source-declared/normalized variant records and 20,090 unresolved label/family rows. The physical-printing total remains unknown; the new 44 holds concern legacy labels among the source-declared records, rather than 44 new cards.

| Measure | Stage13 | Stage14 |
| --- | ---: | ---: |
| Source/family records; internal identity tuples | 70,006 | 70,006 |
| English / Japanese source records | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Source-declared/normalized variant rows | 49,916 | 49,916 |
| Unresolved family/label rows | 20,090 | 20,090 |
| Independently verified physical printings | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,534 |
| Localized bindings / source mappings | 1,782 | 1,907 |
| Japanese / English localized bindings | 1,582 / 200 | 1,682 / 225 |
| Explicit size-loss held IDs | 0 | 44 |
| Quarantine ledger entries | 65 | 109 |
| Release coverage candidates | 65 | 65 |
| Archived source-image fact events / subjects | 1,449 / 1,141 | 1,449 / 1,141 |
| Current exact scan-evidence subjects, including number-only evidence | 1,171 | 1,171 |
| New packaged images or image bindings | 0 | 0 |
| Catalogue / image display permissions | 0 / 0 | 0 / 0 |
| Automatic offer / purchase approvals | 0 / 0 | 0 / 0 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |

Dockerfile and `catalog-build-manifest-source-binding-v1.json` remain byte-identical to HEAD. The original 65 ordered, hash-bound inputs and all stage1–13 inputs are preserved. Stage14 explicitly appends the hold ledger as input77, then the vintage locale bindings as input78. The builder's default remains `catalog-build-manifest-discovery-v1.json`; always pass an explicit manifest.

Japanese underrepresentation includes retrieval gaps, incomplete localized set metadata, unresolved variant families and missing exact scan evidence. This stage closes 125 target-ID translation gaps through 97 distinct queries, using already reviewed full names. Structured resolution reports 102 unique outcomes and 23 multiple-candidate outcomes; ambiguous variants remain separate. English queries for Japanese cards, Japanese-name queries for English cards, Unicode normalization and wrong-language exclusions are exercised. Missing set names still affect 7,745 Japanese source rows; unknown release dates affect 8,114. Those counts are unchanged. A promo family need not have one release date. Missing images do not imply missing identities, and absent offers do not imply absent catalogue rows. Pocket/digital-only records remain excluded.

## Bounded metadata selection

The frozen stage13 plan, SHA256 `658a8197a3286553ff8049dd05f84422988aad8cf1616b5f7b55a9b9980f1170`, supplies exactly 100 Japanese records across PMCG1(44), PMCG2(20), PMCG3(23), E3(5) and E5(8). They cover 72 coordinate groups and 67 existing name concepts. Complete eligible variant groups are retained; the five unresolved image-target groups are excluded. These are measured retrieval gaps in existing records, rather than invented translations or new physical-card claims.

The 25 disjoint English comparison records span SV03.5(11), SWSH10.5(2), SM9(4), SM7.5(1), SM3(1), SM115(2), SM3.5(1), SV02(1) and SV03(2). Among 697 preliminary English candidates, 678 qualified and 19 with nonliteral variant structures were held. Selection checks 490 pinned source entries, including the retained metadata licence.

Only the existing authorized TCGdex checkout at revision `a211f11f3ba57d56c65c5ac33be35b77d3280757` is used. Every inventory entry has a Git blob, SHA256 and byte count. Git lazy fetching is disabled. Locale records carry source namespace, revision/hash, inspection time, retained rights reference, confidence scope and conflicts. Historical retrieval time and physical distribution region remain unknown where the cache does not establish them. The metadata licence does not confer artwork/display rights. No concepts, review events, counterpart relationships, card identities or release dates are newly asserted.

## Identity and media behavior

The prior size audit found 44 English legacy IDs whose source declares a jumbo size omitted from the legacy variant label. This stage freezes their exact raw identity and source text in immutable revision1 hold evidence, using 43 pinned inventory entries including the licence. The importer verifies actual lexical variants, source hashes/blobs, provenance, prior flags and metadata-only rights before applying all rows. It adds an indexed quarantine entry and retention triggers, keeping both `match_eligible` and `display_allowed` false even after direct flag updates or exact reimport. Source drift keeps the hold active. A changed/rehashed event cannot silently lift it.

`en:BASE1:058/102:normal` is retained and reports source-declared `jumbo`, `identity_hold`, and no canonical replacement or replacement relationships. Its cached first-edition scan is incompatible with that exact size-loss identity; no image is transferred from a sibling. The four Japanese priority IDs remain explicit `missing_source_scan_evidence`:

- `ja:PMCG5:036/096:normal`
- `ja:PMCG1:035/102:normal`
- `ja:PMCG1:035/102:normal_no_rarity`
- `ja:PMCG2:024/048:normal`

Existing authorized cached documents do not establish compatible reviewed scans for those exact targets. This is a cache-scope statement, not a claim that such images cannot exist elsewhere. The prior audit's 138 size-declared variants without a matching legacy row, 296 unsupported source structures, and 19,906 records from other provenance remain unresolved. No new IDs are guessed for them.

Catalogue search, discovery and comparison expose `media_availability`; held IDs also expose `variant_dimension_hold`. Primary source-image facts take precedence. If no primary exists, exact current agreed number-reading evidence may qualify. Stale primary evidence never falls through to a secondary/sibling scan. Number reading holds and coordinate conflicts are excluded. Observed source numbering and its namespace remain visible; an unobserved PMCG denominator is not invented.

The final 70,006-row partition is 1,171 current scan-evidence subjects, 68,791 with missing exact evidence, 44 identity holds, zero stale and zero held scan subjects. Of the current union, 1,141 use primary image facts and 30 use number-only evidence. The previous 1,141 primary and all existing number contexts are unchanged. This is archived evidence availability, not successful live fetching, permission to display artwork, or physical verification.

`with_source_scans=true` filters the entire constrained pool before count and pagination. Only exact lowercase `true`/`false` are accepted. Generic recommendation uses scan evidence as a tie-break after explicit and liked relevance, before coordinate diversification. Hard set/number/variant/exact-ID scopes retain their identities. Exact IDs containing unlimited/first-edition labels remain catalogue lookups; a separately requested graded/edition physical copy still requires evidence.

The original broad request `help me find some pikachu cards` returns five current exact scan-evidence bindings with no warnings: HGSSP HGSS03 holo; ME02.5 057 holo; SMP SM04 normal; SV02 063 holo; SV04.5 018 normal. Their inspection tiers are three `two_image_model_families` and two `ocr_and_image_model_screening`, respectively. They retain advisory status and all approval flags false. There is no Pikachu-specific ranking rule or source URL substitution. Full-pool Pikachu scan filtering yields16 records; English filtering yields6.

## Verification and local integration

The full suite ran840 tests:838 passed and2 existing skips, in71.592s. All19 new synthetic tests passed; the focused93-test run and16 Node tests passed. Independent GPT-6.1 Sol high review cleared its findings after rechecks. Tests cover idempotent imports, IDs, Unicode/localized resolution, namespace collisions, cross-language negatives, shared artwork, repeated numbers, promos, finish/stamp/size distinctions, missing fields, stale evidence, exact-edition IDs, quarantine guards and prebound trading paths. Synthetic evidence does not create real reviews or licensed artwork.

Both incremental snapshots and independent manifest rebuilds pass integrity/foreign-key checks, exact ledger/mapping checks and historical table comparisons. Hold migration changes only nine card eligibility flags plus44 quarantine rows; the vintage import changes only125 locale bindings and125 mappings. Independent rebuild comparison excludes only the four documented historical builder timestamp columns. Reimport is44 unchanged holds and125 unchanged locale rows.

The read-only local server at `http://127.0.0.1:18789` serves the final candidate for the separately authorized frontend owner's adapter checks. The 19-request operator proof includes exact targets, full-pool pagination, invalid filter rejection, comparison boundaries and direct `/units` and `/offers` HTTP400 rejection for the held Base58 ID. Maximum measured request time was2.772329s in one local run; that is not a cloud latency guarantee or live asset-fetch test. Frontend/private staging integration is owned by the other session. This session has not deployed, pushed, modified cloud access/expiry or changed frontend files.

## Rebuild, rollback and next batch

From the repository root, build into a new path:

```sh
python3 scripts/build_catalog_snapshot.py --manifest catalog-build-manifest-international-pokemon-vintage-v1.json --db ../vintage-new.sqlite3
```

The input manifest SHA256 is `edac857fe29dd854ee86ee2eb95f61873aaaa14b5cd4707baf9ad8355a04bc7e`. The delivered local candidate `../vintage.sqlite3` has SHA256 `0f030b433fb5a285d3c9bd7acc15cd73a3ff09bbf10bf9767e49346d85cccfe6`; the independent rebuild has SHA256 `d0d55e310412cea85526c6f9a22f648a27e408e61229e4363d3feac6fa5e9b1e`. Timestamp differences mean a new build need not have the same file hash; compare audited table contents and installed guards.

Rollback may point a local reader to the untouched stage13 `../classic.sqlite3` (SHA256 `ebb883552bce5aaf7d2553f9f60d9e927c39a9ef8e849cee0b955063c3622b87`) with the76-input classic manifest. Code rollback requires a clean disposable copy of the composed stage14 patch: reverse-check then reverse-apply `international-coverage-stage14-incremental.patch`. The package proof verifies restoration of exact stage13 bytes. Do not reset this shared checkout, remove quarantine rows in place, or overwrite snapshots. Full rollback restores nine historical eligibility flags known to have size ambiguity; retain this issue evidence and avoid trading through those legacy identities. No production rollback is needed because this session made no deployment.

The next operational priority is exact compatible scan and rights qualification for the five targets, using inputs acquired/reviewed by the authorized owner and returned with source hashes, endpoint snapshots and independent evidence. Until supplied, keep their explicit hold/missing states. This session imports no new artwork or fabricated review. Further metadata execution remains bounded:320 Japanese records qualify from334 preliminary candidates, with14 name/Dex holds. An unapplied100-record plan chooses PMCG1(64), PMCG3(19), PCG2(6), PCG5(4), SM2P(7), retaining complete eligible groups and measured translation gaps; its25 English comparisons still require qualification before execution. It is not a broad-import approval.

Korean remains a proposed real-language evaluation only after measured Japan-to-US/adjacent demand, authorized Buy&Ship supply and sufficiently complete metadata/licensing evidence. Row count alone is insufficient. French remains synthetic test-only. Identity is separate from offers, stock, condition, grading, sold versus asking prices and destination-specific landed cost. Catalogue inclusion and source scans grant no display or purchase eligibility. Buy&Ship remains the intended merchant of record; Pivota holds no customer funds.

Evidence: [hold audit](catalog/variant-dimension-holds-v1/coverage-report.json), [vintage audit](catalog/international-pokemon-vintage-v1/coverage-report.json), [next plan](catalog/international-pokemon-vintage-v1/next-batch-plan.json), [tests](catalog/international-pokemon-vintage-v1/test-results.md), [independent review](catalog/international-pokemon-vintage-v1/independent-review.md), [backend note](integrations/pivota/IMAGE_FIX_AND_VINTAGE_BACKEND_NOTE.md).

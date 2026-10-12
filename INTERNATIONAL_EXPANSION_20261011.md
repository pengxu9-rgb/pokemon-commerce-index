# Bounded Japanese retrieval coverage expansion — 2026-10-11

The local candidate snapshot adds reviewed English retrieval aliases to 62 existing Japanese printing/variant IDs across five physical set scopes, plus Japanese aliases on 25 distinct English comparison IDs. All 87 exact target-ID gaps close; these checks use 72 distinct query strings because variant siblings share queries. Catalogue rows remain 70,006. This expands discovery coverage, not independently verified physical-card coverage.

The work remains on isolated branch `codex/international-coverage-20261011`, based on commit `f499b46f7f0898c5c0478c53fef960d435f1765f`. Stages1–6 remain intact; stage6 tree `f04661fef0c31efa6aad31649d163744079e1c9a` is the incremental patch base. The original repository and creator frontend are untouched. Nothing is pushed or deployed.

## Selected gaps

| Japanese set scope | Existing localized source name | New exact-ID retrieval bindings | Number groups |
|---|---|---:|---:|
| SV8A | テラスタルフェスex | 21 | 11 |
| S8B | VMAXクライマックス | 14 | 9 |
| SM12A | TAG TEAM GX タッグオールスターズ | 10 | 10 |
| SM6B | チャンピオンロード | 10 | 10 |
| SM8B | GXウルトラシャイニー | 7 | 7 |

These five scopes provide contemporary and older Japanese collector discovery cases, with existing localized set names/counts, pinned physical-source tuples and current reviewed Trainer/Energy translations. Their exact-ID English queries failed before this batch. They are disjoint from all previous locale evidence and source mappings. English comparisons prefer 25 different reviewed concepts across physical SM and SV scopes; they are not cross-language counterpart assertions. This is a source-qualified engineering selection for the Japan-to-US flow. Set-level user demand and authorized live Buy&Ship offer availability remain unmeasured.

The batch has 47 Japanese language/set/number groups and 62 separate variants: 36 normal, 13 reverse, 11 holo and two reverse_masterball. The 25 English records include 17 existing normalized standard variants, six normal and two player-reward holo variants. A normalized standard label is not a physical-copy verification. Same names, source files, numbers or artwork cannot merge these IDs or their future prices. The table's group counts are reported separately from variant counts.

For example, `Fog Crystal ja S8B 135/184` now retrieves its existing normal and reverse IDs; `Buddy-Buddy Poffin ja SV8A 147/187` retains its normal and reverse candidates. Mist Energy and Legacy Energy retain separate Master Ball variant IDs at their own coordinates. Native Japanese queries continue to work. Structured resolver identities remain unchanged: 85 checks retain a unique result and two retain multiple candidates. Aliases make records findable without resolving physical ambiguity.

## Evidence and boundaries

`catalog/international-coverage-expansion-v1/locales.jsonl` contains 87 immutable, content-addressed locale records. Each binds the exact existing card snapshot, provider namespace/native path, explicit language/variant/release scope, pinned revision, Git blob, SHA-256, reviewed licence hash/reference, inspection time, current concept/review revision, localized release snapshot, metadata confidence and unresolved conflicts. Historical retrieval time remains explicitly unknown; inspection time is recorded as `2026-10-11T13:43:00Z`. Confidence 1.0 concerns checked bytes, an existing source tuple and reviewed text only.

All selected card files and LICENSE match existing authorized TCGdex revision `a211f11f3ba57d56c65c5ac33be35b77d3280757` and the already reviewed MIT metadata licence. The inventory has 72 card source files plus the licence. Sources are reparsed to check the exact language/set/number/name/variant tuple and category. Git checks disable lazy fetching and override origin with `/dev/null`; no network fallback exists. No new translation is inferred from shared art or similar names. Missing fields, stale reviews, ambiguous concepts, source mismatches or unresolved families abort the compiler; the importer quarantines malformed/conflicted bindings, and a manifest import aborts if anything is quarantined.

`region=ZZ` preserves unknown physical distribution region for both Japanese and English. A `tcgdex-product:<set>` label is a provider scope, not an independently qualified region, initial edition or physical release. Existing set names and release dates are copied as snapshots and remain unchanged. No missing date inherits another language's date. All six display/image/purchase/offer/physical-verification/price-comparability claims stay false.

Pocket and digital-only paths are excluded. The synthetic French fixture remains test-only; no real third-language cards are admitted. No artwork or new image evidence, marketplace prices, API keys, subscriptions or restricted scraping are added. Offers, stock, condition, grader/grade, asking versus sold prices and destination-specific landed cost remain separate from catalogue identity. Buy&Ship remains intended MoR; Pivota does not hold customer funds. Live ingestion, purchase/payment actions, cloud permissions and creator frontend changes remain disabled.

## Before and after

| Measure | Stage6 | Stage7 candidate |
|---|---:|---:|
| Internal source records: English / Japanese | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Distinct internal printing/variant tuples | 70,006 | 70,006 |
| Source-declared/normalized variant records | 49,916 | 49,916 |
| Unresolved label records / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical-printing total | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,543 |
| Locale evidence / provider source mappings | 60 / 60 | 147 / 147 |
| Japanese / English locale bindings | 35 / 25 | 97 / 50 |
| This batch: target-ID gaps closed | 0 / 87 | 87 / 87 |
| Publisher-caption events / held candidates / quarantine entries | 4 / 65 / 65 | 4 / 65 / 65 |
| Japanese records missing set names / dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Packaged images / inspected image subjects and hashes | 0 / 1,141 and 1,141 | 0 / 1,141 and 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Ordered snapshot inputs | 68 | 69 |

The October2 audit is reproduced without a difference: 70,006 source-version/family records, not 70,006 independently verified physical cards. Missing images and missing offers do not imply missing identities. Whole-catalogue image availability remains unmeasured. All four anchor product-release bindings and their 65 candidate holds remain unresolved.

## Reproduction and verification

Use `catalog-build-manifest-international-coverage-expansion-v1.json` explicitly for the new candidate. Its 69th input is the hash-bound locale batch; its first 68 inputs are identical to the prior manifest, including all original 65 ordered source-binding inputs. Expected card/evidence inventory counts stay unchanged. Dockerfile still explicitly uses `catalog-build-manifest-source-binding-v1.json`; the older snapshot-builder default is not used for this work.

```sh
python3 -m scripts.build_international_coverage_expansion \
  --db /path/to/immutable-stage6.sqlite3 --source-repo /path/to/existing-tcgdex-public \
  --output /path/to/new-artifact-directory --inspected-at 2026-10-11T13:43:00Z
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-international-coverage-expansion-v1.json \
  --db /path/to/new-rebuilt.sqlite3
python3 -m scripts.audit_international_coverage_expansion \
  --before /path/to/immutable-stage6.sqlite3 --after /path/to/incremental-candidate.sqlite3 \
  --rebuilt /path/to/new-rebuilt.sqlite3 --output /path/to/new-audit.json
```

For exact history preservation, `scripts.audit_international_coverage_expansion.append(before_path, output_path, repository_root)` applies the new locale input exclusively to a new copy. It checks every historical column in all 51 tables, allowing only 87 appended rows each in locale evidence and source mappings. Installed SQL evidence IDs, card IDs, canonical payloads and six-field mappings must exactly match the batch; JSON search success alone cannot prove the stored context binding. Existing outputs are refused, and input drift is rejected.

The independent full rebuild matches every table outside four explicitly named existing builder timestamp columns: 19 identity-exception `applied_at`, two number-rule `applied_at`, 532 rarity-correction `applied_at` and 657 relationship `asserted_at` values regenerate. No such differences occur in the incremental candidate. Its SHA-256 is `aef2f80100489c31451e2726d548071f8e7c7e811c5da4aad9ac53b9db52afb7`; the prior database remains unchanged at `43efee62091ce157ea7d14182262c5c3a68f2e5e86058dbc5287da29b6cc1b82`.

The 87 target-ID checks pass translated, native, fullwidth/decomposed Unicode, wrong-language exclusion and unchanged resolver-identity checks; ten additional queries pass through the unfiltered internal entry. Re-import inserts zero, reports 87 unchanged and zero quarantined, preserving all tables. The locale, selection and licence artifacts reproduce byte-identically. Full Python results: 743 run, 741 pass, two existing skips, 41.122 seconds. All 34 focused cases pass, including 19 new tests; all 15 existing Node caller tests pass. Tests cover bounds, disjoint selection, ambiguous/withdrawn reviews, source/category/licence drift, missing fields/dates, unknown regions, Unicode, source collisions and wrong stored SQL context. Existing negative cases cover shared artwork, promos, foil/stamps, repeated numbers and the test-only third language. Local HTTP tests require the existing localhost sandbox exception; the first focused sandbox run's socket denial is retained in the logs. Three early fixture errors were corrected before final runs.

GPT-6.1 Sol high independently reviewed the compiler, exact source reproduction and actual three-snapshot audit. Two audit findings were fixed: broader disclosure of the four generated timestamp columns and exact SQL installation checks. Final independent review is recorded with the delivery; no Astra model is used for this review.

## Rollback and next bounded batch

The new candidate is separate from the prior snapshot. Discard it or select the prior explicit 68-input manifest to roll back the new aliases; retain the immutable stage6 database for exact timestamp history. There is no runtime/schema migration or external action to undo. Do not delete historical source/evidence rows. For code/artifact rollback, apply the stage7 incremental patch in reverse only to the unchanged stage7 patch state, after `git apply --reverse --check`; preserve unrelated session edits. The cumulative patch applies to the clean base commit; the incremental patch requires stage6 tree.

The next proposed batch is 25 additional Japanese existing-ID retrieval gaps across SV1A (5), SV5A (7), SV6 (4), SV7 (4), SV9 (5), plus 25 disjoint English comparison records. `next-batch-plan.json` records exact IDs/queries, approved source inventory and existing release snapshots after read-only pin/tuple checks. It is not an import input and has not been applied. These contemporary set scopes qualify for another offline retrieval batch; new physical identities need separate identity evidence. SMH/DS/SC/LL remain held until their exact product/variant evidence exists in the authorized sources.

Korean remains a conditional next-language investigation because the reviewed provider has localized Korean headers. It is not a justified real-card import yet: demonstrate actual demand, authorized Buy&Ship supply and complete card/variant sources with reviewed rights first. Row counts, translated headers and shared artwork are insufficient.

# Hundred-level offline coverage batch — 2026-10-12

The new local candidate adds reviewed retrieval coverage for exactly **100 existing Japanese printing/variant IDs across 19 fixed sets**, plus **25 disjoint English comparison IDs**. This is a 125-record batch. Localized evidence and source mappings increase from 147 to 272; card identities remain 70,006. All 125 exact target-ID gaps close, using 122 distinct translated query strings. Shared-query variants keep their own IDs.

The user requested a larger batch on October 12. The remaining approved-name gaps are too dispersed to reach 100 Japanese records within the earlier five-set pilot scope. This explicit scope includes all 25 Japanese targets in the prior proposal, then contemporary Sword & Shield, Scarlet & Violet and Mega set cases with existing localized source names/counts and pinned card tuples. All eligible reviewed-name gaps within these 19 chosen sets are included; short, overfull or incomplete scopes abort instead of silently backfilling or truncating. English comparisons prefer 25 distinct reviewed concepts from eligible physical SM/SWSH/SV scopes; this batch selects SM and SV records. They are comparisons, not counterpart assertions.

The Japanese batch occupies 97 language/set/number groups: 63 normal, 34 holo, one reverse and two reverse_pokeball source variants. Available approved translations constrain it to 93 Trainer and seven Energy records. Pokémon character-name alias gaps remain a separate evidence task. Set-level demand and authorized live Buy&Ship supply remain unmeasured; these are source-qualified retrieval cases for the Japan-to-US use case.

| Japanese scope | Variant IDs | Number groups |
|---|---:|---:|
| M1S | 4 | 4 |
| M2A | 9 | 9 |
| M3 | 3 | 3 |
| M4 | 6 | 6 |
| M5 | 2 | 2 |
| MC | 17 | 17 |
| MF | 2 | 2 |
| S10A | 5 | 4 |
| S6K | 5 | 5 |
| S9A | 6 | 4 |
| SV10 | 4 | 4 |
| SV1A | 5 | 5 |
| SV1V | 4 | 4 |
| SV4K | 4 | 4 |
| SV5A | 7 | 7 |
| SV5M | 4 | 4 |
| SV6 | 4 | 4 |
| SV7 | 4 | 4 |
| SV9 | 5 | 5 |

## Evidence and boundaries

All 122 selected card source files and LICENSE match existing authorized TCGdex revision `a211f11f3ba57d56c65c5ac33be35b77d3280757` and the already reviewed MIT metadata licence. The inventory has 123 entries including the licence. Every source tuple is reparsed to check language, set, number, name, variant, provenance, rights reference and category. Git pin checks disable lazy fetching and override origin with `/dev/null`; sources and licence are checked again after compilation. No network fallback or new external source is used.

Each immutable locale record binds the exact existing identity snapshot, provider/native path, revision/Git blob/SHA-256, licence hash/reference, current reviewed concept/review revision, localized release snapshot, metadata confidence and unresolved conflicts. Inspection is `2026-10-12T00:15:21Z` (08:15:21 Asia/Shanghai). Historical retrieval time stays explicitly unknown. Confidence 1.0 applies to checked bytes, the existing source tuple and current reviewed text; it does not verify a physical copy or price comparability. No new translation review is invented.

Both languages use `region=ZZ`; physical distribution region remains unknown. A `tcgdex-product:<set>` value is a provider scope, not a qualified initial edition or independent product-release binding. Existing set names/dates are snapshots and remain unchanged. Missing fields, stale or ambiguous reviews, source conflicts and unresolved families are refused; importer quarantine and manifest-abort behavior remain intact. Shared artwork, names, repeated numbers, foil/stamps and promos cannot merge separate variants, languages, editions, prices or offers.

All display, image-display, purchase, automatic-offer, physical-printing and price-comparability flags remain false. Pocket/digital paths remain excluded; French remains synthetic test-only and no real third-language cards are admitted. No new artwork, image evidence, marketplace prices, API keys, subscriptions, restricted scraping, cloud permissions, live ingestion, payment or purchase activity is added. Offers, stock, raw condition, grading company/grade, sold versus asking prices and destination-specific landed cost remain separate. Buy&Ship remains intended MoR; Pivota does not hold customer funds. Creator frontend files remain untouched. No push or deployment occurs.

## Before and after

| Measure | Stage7 | Stage8 candidate |
|---|---:|---:|
| Internal source records: English / Japanese | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups / distinct internal identity tuples | 45,438 / 70,006 | 45,438 / 70,006 |
| Source-declared/normalized variant records | 49,916 | 49,916 |
| Unresolved label records / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical-printing total | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,543 |
| Locale evidence / provider source mappings | 147 / 147 | 272 / 272 |
| Japanese / English locale bindings | 97 / 50 | 197 / 75 |
| This batch: target-ID gaps closed | 0 / 125 | 125 / 125 |
| Publisher-caption events / held candidates / quarantine entries | 4 / 65 / 65 | 4 / 65 / 65 |
| Japanese records missing set names / dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Packaged images / existing image-evidence subjects and hashes | 0 / 1,141 and 1,141 | 0 / 1,141 and 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Ordered build inputs | 69 | 70 |

The committed October2 audit is reproduced without a difference: 70,006 source-version/family records are not 70,006 independently verified physical cards. Missing images or offers do not imply missing identities. Whole-catalogue image availability remains unmeasured. SMH/DS/SC/LL anchor product/physical bindings and all 65 candidate holds remain unresolved.

## Implementation, reproduction and checks

The isolated branch remains `codex/international-coverage-20261011`, HEAD `f499b46f7f0898c5c0478c53fef960d435f1765f`. Stage7 tree `54e4b95ea11bc7ce3d7f0724dc29036e9e00565e` is the new incremental patch base. Existing work and evidence artifacts are retained. The two operator helpers accept validated, immutable scope/audit profiles; dedicated hundred-batch entry points select the fixed 100-Japanese scope. Earlier five-set defaults and their compiled artifacts reproduce byte-identically. There is no runtime/schema or response-contract change in this stage.

Use `catalog-build-manifest-international-coverage-hundred-v1.json` explicitly. It appends one hash-bound locale input, preserving all previous 69 ordered inputs including the original 65 from `catalog-build-manifest-source-binding-v1.json`. Expected card/evidence inventory counts stay unchanged. Dockerfile still explicitly uses that original 65-input manifest; the snapshot builder's older default is not used.

```sh
python3 -m scripts.build_international_coverage_hundred \
  --db /path/to/immutable-stage7.sqlite3 --source-repo /path/to/existing-tcgdex-public \
  --output /path/to/new-artifacts --inspected-at 2026-10-12T00:15:21Z
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-international-coverage-hundred-v1.json \
  --db /path/to/new-rebuilt.sqlite3
python3 -m scripts.audit_international_coverage_hundred \
  --before /path/to/immutable-stage7.sqlite3 --after /path/to/incremental-candidate.sqlite3 \
  --rebuilt /path/to/new-rebuilt.sqlite3 --output /path/to/new-audit.json
```

For exact history, call `scripts.audit_international_coverage_hundred.append(before_path, output_path, repository_root)` to create a new incremental copy. It verifies every historical column in all 51 tables, permitting only 125 new locale rows and 125 new source mappings. Outputs are exclusive and input drift is rejected. Installed SQL evidence IDs/card IDs/canonical payloads and six-field mappings must match the queue exactly; duplicate IDs are rejected before ingestion.

All 125 target-ID checks pass translated, native, fullwidth/decomposed Unicode and wrong-language exclusion checks. Resolver identity results remain unchanged: 120 retain unique results and five retain multiple candidates. Ten additional unfiltered internal queries pass. Re-import reports inserted 0 / unchanged 125 / quarantined 0 and preserves all tables. New and prior-stage locale/selection/licence artifacts reproduce byte-identically. Candidate database SHA-256 is `72a1611592d47949cab972479aee007e118433fb926fb34039d0863bb8791cf3`; prior stage7 remains unchanged at `aef2f80100489c31451e2726d548071f8e7c7e811c5da4aad9ac53b9db52afb7`. Both pass SQLite integrity checks.

Independent full rebuild differences are limited to four disclosed legacy generated timestamp columns: identity-exception `applied_at` 19, number-rule `applied_at` 2, rarity-correction `applied_at` 532 and relationship `asserted_at` 657. No such differences occur in the incremental snapshot. All other records match.

Final Python suite: 756 run, 754 pass, two existing skips, 42.484 seconds. All 47 focused cases pass, including 13 new hundred-batch tests; all 15 Node caller tests pass. New cases cover exact count/set scope, immutable/invalid profiles, underfill, overflow, missing comparisons, duplicate IDs, missing sets, source pins, exclusive outputs, input drift and all-column preservation. Earlier negative tests cover Unicode, provider collisions, region/variant reuse, shared artwork, promos, foil/stamps, repeated numbers, missing fields and test-only French. One initial synthetic overfull fixture used SQL integer booleans; the fixture was corrected to explicit booleans and the failed log is preserved. No final checks fail. These are engineering results, not demand, physical-copy, real-listing or transaction accuracy.

GPT-6.1 Sol high independently reproduced sources/evidence and the actual three-snapshot audit and reviewed the scope controls. Final review is archived with the delivery; Astra is not used.

## Rollback and next batch

Rollback by discarding the separate stage8 candidate or selecting the prior explicit 69-input manifest. Retain the immutable stage7 database for exact timestamp history; do not remove historical evidence rows. Reverse the stage8 incremental patch only on its unchanged matching state after `git apply --reverse --check`, preserving unrelated session changes. The cumulative patch applies to the clean base commit; incremental requires stage7 tree. There is no deployed migration or external action to undo.

The next proposed batch is **100 total records: 75 Japanese IDs across 18 fixed heritage SM/additional SV sets, plus 25 disjoint English comparisons**. `next-batch-plan.json` contains the exact candidate IDs/queries, checked pinned source inventory, release snapshots, rights, confidence, unknown retrieval time/region and unresolved demand/supply. Its content-addressed plan is absent from the manifest and has not been imported. Source qualification is complete for an additional offline retrieval batch; new physical identities still require separate identity evidence.

Korean remains a conditional next-language investigation based on existing reviewed localized headers. Demand, authorized Buy&Ship supply and complete reviewed card/variant sources are still required before a real language batch; raw row counts and translated headers do not justify admission.

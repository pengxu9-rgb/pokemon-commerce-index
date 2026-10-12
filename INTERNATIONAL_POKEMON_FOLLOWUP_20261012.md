# Offline name-coverage follow-up — 2026-10-12

The local candidate applies the previously reviewed **85 Japanese records across eight partial set scopes**, plus **25 disjoint English comparisons**. These are existing source-declared variant IDs, with no new card identities or physical-copy verification. Locale evidence and provider source mappings rise **1,297 → 1,407**: Japanese **1,282**, English **125**. All **110 exact target-ID retrieval gaps** close through **105 distinct translated queries**. Structured resolution identifies **109 catalogue coordinates** and retains **one ambiguity hold**.

The Japanese plan is preserved byte-for-byte as basis-plan.json, bound to SHA-256 `03b902152be82b527ab9e7fc87b86ae6e339095ed77cee26da5b2e936159305c`. Its 85 records occupy 80 set/number groups and 52 existing reviewed full names. Every eligible unbound Japanese sibling must be included; changed, missing, newly bound or incomplete groups abort. No translation concept is added: concept revisions/review events remain **285 / 623**. English selection uses 25 distinct concepts from the same Japanese name group, after source qualification of 701 candidates. Comparison records do not assert counterparts or identical SKUs.

| Japanese scope | Variant records |
|---|---:|
| M3 | 11 |
| M6 | 12 |
| S11A | 13 |
| S9 | 10 |
| SM11B | 12 |
| SM1S | 1 |
| SV1V | 11 |
| SV6 | 15 |

English scopes: SV03.5 3, SV06 2, SM10 15, SM9 2, SM4 2, SM11 1. Combined provider variant labels are normal 65, holo 20, standard 20 and reverse_pokeball 5. These labels do not independently establish physical finishes or editions.

The held comparison is **en:SV06:082/167:holo, Alakazam**. The broad holo request also matches its separate **holo_cosmos** row, which lacks a current locale binding. Search finds the selected record, while structured resolution returns `not_attempted / reviewed_name_record_binding_required` with no chosen IDs. A Cosmos variant is not silently treated as regular holo. It remains a separate catalogue row; additional evidence must preserve ambiguity rather than force a unique SKU. This is a resolver hold, separate from the unchanged 65 catalogue candidate/quarantine entries.

## Evidence and reproduced baseline

All **496 source inventory entries including LICENSE** match the existing authorized TCGdex pin `a211f11f3ba57d56c65c5ac33be35b77d3280757` and the reviewed MIT metadata licence. Each selected tuple is reparsed for exact language, set, collector number, variant, full name, category, singleton-Dex, provenance and rights reference, against the current approved name/review event. Review-event digests are checked. Licence/source/plan/database checks repeat after compilation; Git lazy fetch is disabled and origin is overridden with `/dev/null`. No external source or network fallback is used.

Inspection is recorded as `2026-10-12T03:03:38Z` (11:03:38 Asia/Shanghai). Historical retrieval time remains explicitly unknown. Each record retains provider/native ID, revision/Git blob/SHA-256, licence hash/reference, identity and localized-release snapshots, current review reference, full-name/Dex scope, confidence and conflicts. Confidence 1.0 describes checked source bytes and retained metadata translation, with no physical-copy or market accuracy claim. Region remains `ZZ`; physical distribution region is unknown. Provider product labels do not establish initial editions or independently qualified releases.

| Measure | Stage9 | Stage10 candidate |
|---|---:|---:|
| Internal source-version/family records: English / Japanese | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups / distinct internal identity tuples | 45,438 / 70,006 | 45,438 / 70,006 |
| Source-declared/normalized variants | 49,916 | 49,916 |
| Unresolved label records / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical-printing total | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,543 |
| Locale evidence / provider mappings | 1,297 / 1,297 | 1,407 / 1,407 |
| Japanese / English bindings | 1,197 / 100 | 1,282 / 125 |
| Concept revisions / review events | 285 / 623 | 285 / 623 |
| Publisher captions / catalogue holds / quarantine | 4 / 65 / 65 | 4 / 65 / 65 |
| Japanese rows missing set names / release dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Packaged images / existing image-evidence subjects and hashes | 0 / 1,141 and 1,141 | 0 / 1,141 and 1,141 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Ordered build inputs | 72 | 73 |

The October 2 committed audit is reproduced with no record-count difference. Its 70,006 internal rows are not 70,006 independently verified physical cards. This step improves bilingual name discovery; missing release fields, image availability and offers remain separate gaps. Whole-catalogue image availability is unmeasured. SMH/DS/SC/LL product/physical qualification remains unresolved.

All display, image-display, physical-printing, price-comparability, automatic-offer and purchase claims stay false. Pocket/digital records remain excluded; French remains a synthetic test-only language fixture. No artwork, prices, offers, keys, subscriptions, restricted scraping, cloud permissions, live ingestion, purchases or payments are added. Identity, stock, raw condition, grading company/grade, asking/sold prices and destination landed costs remain separate. Buy&Ship remains intended MoR; Pivota does not hold customer funds. The creator frontend and runtime/schema are unchanged in this step; nothing is pushed or deployed.

## Verification and local reproduction

Use **catalog-build-manifest-international-pokemon-followup-v1.json** explicitly. It preserves every previous 72 ordered hash-bound input, including the original 65 from **catalog-build-manifest-source-binding-v1.json**, and appends one locale input. Expected inventory counts remain unchanged. Dockerfile explicitly retains the original 65-input manifest; the builder's older default is not used.

The compiler refuses anything outside the frozen Japanese plan, stale/ambiguous reviews, source drift and existing bindings. The audit checks exact planned name/Dex pairs, requires English alias/Dex to match the selected Japanese concepts, and validates installed SQL evidence/card IDs/canonical JSON and six-field source tuples. It permits only 110 locale and 110 mapping additions; all historical columns in 51 tables remain intact. New record binding may enable an already approved translation; legacy audit profiles still require unchanged resolver outcomes by default.

All 110 translated/native/fullwidth/decomposed Unicode and wrong-language checks pass; ten unfiltered queries pass. The 109 positive results remain inside exact language/set/number/full-name/category and current-binding scope. Re-import returns inserted 0 / unchanged 110 / quarantined 0, preserving every table. The independent 73-input rebuild matches all content except four existing generated timestamp columns: identity-exception applied_at 19, number-rule applied_at 2, rarity-correction applied_at 532 and relationship asserted_at 657. The incremental copy preserves those too. All three snapshots pass SQLite integrity checks. Four compiler artifacts reproduce byte-identically, and fixed compiler-input hashing keeps audit/prose outputs out of the input signatures.

Final Python suite: **791 run, 789 passed, two existing skips**; all **72 focused cases**, including **15 new cases**, pass. All **15 Node caller tests** pass. Tests cover exact plan/hash/identity/set scope, current reviews, missing or omitted foil/stamp siblings, disjoint English names, source/plan drift, exclusive outputs, all-column preservation, idempotence, literal name/Dex audit scope and future English comparison restrictions. Existing negative tests retain Unicode, source collisions, shared artwork, promos, repeated numbers, missing fields and physical/trading gates. GPT-6.1 Sol high independently reviews this delivery; its final record is archived alongside the reports. These are engineering/source-qualification checks, with no real-user or transaction accuracy claim.

The isolated branch remains `codex/international-coverage-20261011`, HEAD `f499b46f7f0898c5c0478c53fef960d435f1765f`. Its staged content matched the previous delivery before work began; no other session changes were present. Stage9 tree `509765edb93aa8885f4132acb29c9164d436b0a3` is the incremental patch base. Original repository main remains untouched. No commit is made.

```sh
python3 -m scripts.build_pokemon_name_followup \
  --db /path/to/immutable-stage9.sqlite3 --source-repo /path/to/existing-tcgdex-public \
  --output /path/to/new-artifacts --inspected-at 2026-10-12T03:03:38Z
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-international-pokemon-followup-v1.json \
  --db /path/to/new-rebuilt.sqlite3
python3 -m scripts.audit_pokemon_name_followup \
  --before /path/to/immutable-stage9.sqlite3 --after /path/to/incremental-candidate.sqlite3 \
  --rebuilt /path/to/new-rebuilt.sqlite3 --output /path/to/new-audit.json
```

For exact historical timestamps, call `scripts.audit_pokemon_name_followup.append(before_path, output_path, repository_root)`. Evidence drift is checked before exclusive publication of the temporary copy. Candidate SHA-256 is `216f0b0411fb06dc801cceebd9fb15e90e5f0c82863968454b53b05b27b2be24`; stage9 remains `2778cafe8b7e2e1e57fc775f0ce84c3963bc7eca0067fc5d92a8a2505552a7e0`; rebuild is `88354d73590144ad2c9c7842431eaad9b6b123ff2f0ac28454e945562faf6d2d`.

Rollback: use the untouched stage9 snapshot or explicitly rebuild its 72-input thousand manifest. Reverse only the stage10 incremental patch after `git apply --reverse --check` passes against matching content; preserve unrelated work. Fresh temporary copies verify cumulative/incremental patch application and actual reverse restoration. Nothing requires a cloud rollback.

## Next justified batch

A read-only source qualification pass found 734 remaining eligible reviewed-name candidates across 81 Japanese scopes. **720 records pass** the existing pin/tuple/singleton-Dex/current-name checks and complete eligible groups; **14 lack singleton-Dex evidence and remain held**. These operator holds are separate from catalogue quarantine, and include the earlier 13 held candidates. The source inventory contains 619 entries including LICENSE; no import occurs during this qualification.

The next unapplied proposal selects **100 Japanese variant records at 94 number groups across ten modern scopes**: S9A 13, S8 12, S11 11, S12 11, SM6A 12, SM1M 12, M2 12, M5 9, SV9 7, SV6A 1. Each has a measured target-ID gap and existing full-name review. Twenty-five disjoint English comparisons remain a future selection target. Recheck current pins/reviews and issue a reviewed next manifest before applying. The remaining qualified pool can support further bounded batches, while reaching 5,000 needs additional full-name/source qualification beyond the current Kanto scope. Demand and live authorized supply remain unmeasured; qualification counts are not stock or buyer demand. Real third-language expansion remains conditional on evidence of demand, authorized supply and licensed completeness.

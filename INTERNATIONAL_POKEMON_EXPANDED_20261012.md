# Larger offline retrieval batch — 12 October 2026

The user authorized parallel agents and a larger batch. A source planner, cached-evidence auditor and independent GPT-6.1 Sol high reviewer supported this local stage. It adds **300 Japanese and 75 English localized retrieval bindings**, three times stage14's batch, while preserving all existing card IDs and references. The source-record count and physical/image/commerce approvals do not increase.

This remains the isolated `codex/international-coverage-20261011` checkout, based on `f499b46f7f0898c5c0478c53fef960d435f1765f`. Stage14's staged tree `c0912a3264a00dcb37a52be3f4f7f366a6313351`, delivery and database remain frozen. Its running read-only server retains the code and catalogue revision loaded at startup; the current checkout has the stage15 revision fix for future launches. Stage15 uses a separate candidate. No creator frontend, deployment, push, cloud permissions/expiry, live ingestion, artwork, marketplace prices, purchases or payments were changed by this session.

## Coverage and meaning

| Measure | Stage14 | Stage15 |
| --- | ---: | ---: |
| Internal source-version/family records; distinct internal identity tuples | 70,006 | 70,006 |
| English / Japanese source records | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Source-declared/normalized variant records | 49,916 | 49,916 |
| Unresolved family/label rows | 20,090 | 20,090 |
| Independently verified physical printings | Unknown | Unknown |
| Structural matching eligibility | 33,534 | 33,534 |
| Locale bindings / provider source mappings | 1,907 | 2,282 |
| Japanese / English locale bindings | 1,682 / 225 | 1,982 / 300 |
| Size-loss identity holds / quarantine ledger entries | 44 / 109 | 44 / 109 |
| Source-image fact events / subjects | 1,449 / 1,141 | 1,449 / 1,141 |
| Current exact scan-evidence subjects, including number-only evidence | 1,171 | 1,171 |
| New images / image bindings / counterpart assertions | 0 / 0 / 0 | 0 / 0 / 0 |
| Catalogue / image display permissions | 0 / 0 | 0 / 0 |
| Automatic offer / purchase approvals | 0 / 0 | 0 / 0 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |

The October 2 baseline is reproduced without a source-record count difference. Its 70,006 rows are not 70,006 independently verified physical cards. This stage improves retrieval of existing source records; it does not create new printing identities. Shared artwork, names or similar numbers never merge SKUs or price series. Pocket/digital-only cards remain excluded. Unknown Japanese set names still affect 7,745 rows and unknown dates 8,114 rows; those metadata gaps are unchanged.

The explicit 79-input manifest preserves all 78 previous ordered steps and the original 65 hash-bound source-binding inputs. Dockerfile and `catalog-build-manifest-source-binding-v1.json` are unchanged. The builder's older default manifest is not used for this candidate.

## Selection, provenance and bounded scaling

The frozen plan SHA256 is `d2ddacfdfdfbb15399484cdeda567842cf4facd278fe2f6b924861a26485255e`. The prior 320 qualified Japanese records included three priority image IDs. Excluding the five priority IDs' four distinct coordinate groups leaves 317 complete-group candidates. The plan selects exactly 300 records in 252 complete eligible groups across 58 releases, using 108 already reviewed exact full-name concepts. It includes one complete group from each eligible release, then uses chronological round-robin selection and a residual-count check to avoid splitting variant groups. PMCG1 contributes 74 and PMCG3 18; the remaining 208 span NEO, WEB, PCG, CP, SM, S and SV scopes. Full per-set counts and exact IDs are in the selection evidence.

The English pool contains 1,191 preliminary candidates. Pinned card tuples, singleton Dex, current approved names, literal variants and localized provider release metadata qualify 1,169; 22 nonliteral variant structures remain held and are not selected. The final 75 comparisons use distinct retained Japanese-scope concepts and disjoint existing English IDs, across 17 release scopes. They are comparison records rather than printing-counterpart relationships. A shortfall aborts; the compiler does not pad with duplicate concepts.

Only the existing authorized TCGdex cache at revision `a211f11f3ba57d56c65c5ac33be35b77d3280757` is used. The planner verifies 1,105 pinned files, including 105 release headers. The compiled batch verifies 1,080 inputs, including those headers, with 103 qualified localized release snapshots. The difference is unselected/held Japanese source files retained in planning evidence. Two headers occur only among held English variants and confer no release qualification. Both inventories retain original Git blobs, SHA256 hashes and byte counts, with the existing licence preserved. Git lazy fetching is disabled.

Each binding records provider namespace, language, source release, region `ZZ` where physical distribution is unknown, source ID, revision/blob/hash, rights reference/status, inspection time, explicit unknown historical retrieval time, confidence scope and conflicts. Confidence refers to checked metadata bytes/current exact-name review, not physical printing. No new translation concepts, semantic review events, release dates or counterpart assertions are created. Metadata licensing confers no artwork/display rights.

The new release extractor reads literal source data only. Some original English headers use legacy variable names such as `sm10`; the extractor normalizes only the checked declaration/export binding tokens in an extraction copy. Evidence hashes always bind original bytes. Multiple/mismatched declarations or exports, missing/computed fields, inconsistent ID/name/date/count and boolean counts abstain. It preserves localized versus shared provider-date scope and does not establish initial-versus-copy or destination-region release dates.

Larger batches require explicit `expanded_batch=true`, strict dimension validation and a frozen reviewed plan. Hard ceilings are 300 JA / 75 EN / 64 scopes. Historical defaults stay 100 JA / 25 EN / 19 scopes; the generic selector refuses expanded batches and directs them to the frozen exact-name compiler. Compiler and audit scopes must match fully. English selection is restricted to the exact frozen qualified pool, with card/name/Dex/release witnesses rechecked. Priority exclusions cover whole language/set/number groups, including any foil/stamp sibling. Source, licence, plan, input database, release headers and priority-image witness are rechecked at the end of compilation. Historical vintage/classic artifacts still reproduce byte for byte.

## Evidence and trading boundaries

All 44 source-size-loss holds remain current, with exact canonical ledger records, both retention triggers, the partial index and matching/display flags checked on before/candidate/rebuilt snapshots. The legacy `en:BASE1:058/102:normal` remains a source-declared jumbo hold with no canonical replacement or standard-size/edition fallback. Direct market readers still reject it. All four Japanese priority IDs still lack compatible imported exact scan evidence. The cached-evidence agent qualified no new target and made no new visual review or source retrieval.

The final media partition remains 1,171 current + 68,791 missing + 44 identity holds = 70,006; stale/held scan counts are zero. Current evidence basis is 1,141 primary image-fact subjects and 30 exact number-only subjects. All previous image/number contexts and all five priority card responses are unchanged. Missing images are not absent identities, and absent offers are not absent catalogue records. Artwork/translation/number similarity is not printing or price equivalence.

The frontend owner's existing six-English-Pikachu local receipt matches archived exact source URLs and image hashes, but these are different from the five unresolved targets. Fetch times were 14.322–50.846 seconds; they do not establish consistently sub-20-second image delivery. Its read-only status inspection found model-capacity failure and no completed stage14 cloud/UI acceptance receipt. This stage does not resume, edit or deploy the frontend. Its stage14 snapshot and existing server process view remain available and unchanged.

The expanded candidate retains the same first five broad Pikachu scan-evidence results and all false physical/display/transaction flags. The final local in-process replay with a precomputed catalogue revision took 13.170721 seconds during concurrent testing. That excludes startup, asset fetching, cloud and UI latency. Source availability remains archived evidence rather than live display delivery.

## Verification and rollback

The final full Python run executed 853 tests: 851 passed and two existing skips, in 156.818 seconds. The final journey/media/hold/expanded subset passed 46 tests in 29.857 seconds, including local HTTP checks; the focused name/profile suite passed 75 tests in 62.644 seconds. The independent reviewer separately passed all 12 new expanded-batch methods and the additional revision regression, and verified source inventories, all release/English witnesses, exact installations, whole groups, historical reproducibility and hold guards. Node tests passed 16/16 in 270.209917 ms. Initial synthetic names collided with existing query vocabulary and were corrected to unambiguous synthetic names without altering production search behavior; an operator report query was corrected to join the locale table to the card language. An initial revision fixture used the wrong SQL value count and was corrected; an initial packaging check used an inherited older checksum and was corrected against the immutable stage14 receipt. Retained diagnostic logs are not counted as passing checks.

Catalogue revisions now include the locale ledger, provider source mappings, full-name concept revisions and review events, as well as the locale/language module bytes. Review found that these were omitted from the previous revision digest. Fresh CLI/source runs distinguish stage14 (`a253a5ccd318299614a2f923ac2c3168d747daca717def8ecf8d91f32b714b81`) from stage15 (`9e28d15fc139a38a146ab3814a97f4f930b7e2ff35737ec26a1a59b3e99f4b4d`), and reject saved resumes carrying the older expected revision. Equivalent candidate/rebuild contents share the latter revision. API schemas and ranking policy are unchanged. The existing integration server caches its revision at startup and still serves its recorded stage14 process view (`ca0c40ac97aee676e47ec750bb786746470509322f2182306352aa3d468f5d11`); it was not restarted or promoted.

The audit measures 375 target-ID translation gaps over 327 distinct queries: 336 unique and 39 multiple-candidate resolver outcomes. Native, Unicode and wrong-language checks pass. Ambiguity remains a request for variant clarification, never a guessed merge. Reimport yields zero inserts, 375 unchanged and zero quarantines. All 51 historical tables are preserved, with only 375 locale and 375 source-mapping rows appended. The independent rebuild matches audited contents except four explicitly documented historical builder-generated timestamp columns. Integrity, foreign keys, exact ledger/mapping rows, hold flags and retention definitions pass.

Build a new local file explicitly:

```sh
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-pokemon-expanded-v1.json --db ../expanded-new.sqlite3
```

Manifest SHA256: `5641882668cc41e98a2886b7b3f6d9c85ab26306e0d0075b3a96ded87f369a72`. Candidate `../expanded.sqlite3`: `5289fb3167fe193257e4d58e715f9600a8f585443fdb9c61563aecd8c80f86cf`. Independent rebuild: `4c444e72932f6047bb77686bd766a6b68450af7a5f0a4fa071d7c240d01f14c2`. New builds may differ in historical generated timestamps; compare audited contents/guards rather than assuming identical file hashes.

Rollback uses untouched stage14 `../vintage.sqlite3`, SHA256 `0f030b433fb5a285d3c9bd7acc15cd73a3ff09bbf10bf9767e49346d85cccfe6`, with the 78-input vintage manifest. Reverse-check and reverse-apply the delivered stage15 incremental patch only in a clean disposable copy of the composed patch. The package proof verifies exact restoration of stage14 bytes. Do not reset this shared checkout, overwrite snapshots or remove evidence in place. Stage14's 44 holds remain effective after this rollback. No production rollback is required because this session deployed nothing.

The remaining requalification has 34 preliminary Japanese records: 20 qualify, including three priority image IDs, and 14 singleton-Dex records stay held. Excluding those priority groups leaves 17 safe complete-group records, all in PMCG1/PMCG3. The next justified work is compatible exact scan/rights evidence for the five targets and a newly reviewed full-name tranche beyond the present Kanto scope before another large import. The residual 17 can support a smaller explicitly reviewed follow-up, not another 300-record promise. Set demand and authorized Buy&Ship supply remain unmeasured. Korean remains a conditional next real-language evaluation based on demand, authorized supply and metadata completeness; French stays synthetic test-only.

Identity remains separate from stock, offers, raw condition, grading company/grade, asking versus sold prices and destination-specific landed cost. Catalogue inclusion grants neither display nor purchase permission. Buy&Ship remains intended merchant of record; Pivota does not hold customer funds.

Evidence: [coverage audit](catalog/international-pokemon-expanded-v1/coverage-report.json), [frozen plan](catalog/international-pokemon-expanded-plan-v1/plan.json), [cached image qualification](catalog/international-pokemon-expanded-v1/cached-image-qualification.md), [remaining qualification](catalog/international-pokemon-expanded-v1/remaining-name-qualification.json), [tests](catalog/international-pokemon-expanded-v1/test-results.md), [review](catalog/international-pokemon-expanded-v1/independent-review.md), [backend note](integrations/pivota/INTERNATIONAL_POKEMON_EXPANDED_BACKEND_NOTE.md).

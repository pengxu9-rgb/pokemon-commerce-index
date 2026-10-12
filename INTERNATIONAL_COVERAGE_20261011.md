# Staged international coverage — offline pilot, 11 October 2026

Implemented on `codex/international-coverage-20261011`, based on clean `main` at `f499b46f7f0898c5c0478c53fef960d435f1765f`. No creator frontend changes, deployment, push, cloud permissions, live ingestion, purchases or payments. Independent review uses GPT-6.1 Sol high.

## Reproduced baseline and interpretation

Dockerfile explicitly selects `catalog-build-manifest-source-binding-v1.json`; the snapshot CLI default is an older manifest. This work uses the Dockerfile manifest explicitly. All 65 ordered input entries and their SHA-256 bindings are identical in the new 66-step pilot manifest. Dockerfile and every historical manifest/input remain unchanged.

| Measure | Before | After |
|---|---:|---:|
| Internal source-version/family records | 70,006 | 70,006 |
| English records | 42,911 | 42,911 |
| Japanese records | 27,095 | 27,095 |
| Distinct internal language/set/number/variant tuples | 70,006 | 70,006 |
| Language/set/number groups | 45,438 | 45,438 |
| Source-declared variant records, excluding unverified labels | 49,916 | 49,916 |
| Unresolved family labels / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Structural matching eligibility | 33,543 | 33,543 |
| Catalogue display permissions | 0 | 0 |
| Image files packaged in catalogue | 0 | 0 |
| Source-image evidence subjects / distinct hashes | 1,141 / 1,141 | 1,141 / 1,141 |
| Image display / automatic offer / purchase permissions | 0 / 0 / 0 | 0 / 0 / 0 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Scoped localization/source bindings | 0 | 60 |

There is no difference from the requested October 2 baseline. The earlier 70,005-record audit predates the appended source-only 154/SV-P family; it does not justify counting independently verified physical cards. The 49,916 declared variants also remain provider declarations, not independent physical validation or deduplicated market SKUs. Source rows with overlapping physical interpretations are preserved. Whole-catalog image availability is not inventoried; image evidence hashes count inspected subjects, not comprehensive image coverage or display rights. Pocket is excluded, and the generalized builder rejects its series.

Full per-query counts, release gaps and verification are in `catalog/international-coverage-pilot-v1/coverage-report.json`. Incrementally appending the pilot to a copied baseline preserves every pre-existing table and column exactly. Independent rebuilds differ in 657 relationship `asserted_at` values because the existing importer generates timestamps when source rows omit them; only that bookkeeping column is excluded from independent rebuild comparison. Relationship IDs, endpoints, assertions and evidence remain identical. Historical stored timestamps remain unchanged during incremental append.

## Actual Japanese gaps

Japanese coverage has **24,145** language/set/number groups versus **21,293** English groups, and 342 represented Japanese set scopes versus 201 English scopes. Fewer Japanese source-version rows do not demonstrate fewer distinct card coordinates: English variant expansion inflates its row total.

The pinned Japanese extraction has 5,046 gaps: 4,994 missing Japanese source names, 50 colliding source variant declarations, and two set-header/directory issues. The second reference source reports 162 same-coordinate name conflicts, 525 ambiguous new coordinate groups and 1,468 unsupported identities. These are historical source extraction gaps; many coordinates already have a separate unresolved catalogue record. They are not additive missing-card counts.

The current catalogue has 7,745 Japanese records across 197 set scopes missing release names, and 8,114 records across 200 scopes missing dates. Promotional scopes may span many dates; no single date is invented. The frozen October 1 Japanese API refresh returned zero card briefs for all 40 then-missing runtime set scopes. S6a's licensed pinned source has Traditional Chinese names without Japanese names; those must not be relabelled Japanese. Legacy denominator conflicts, printed-number differences, promo/sentinel numbers and family holds remain in their existing evidence layers.

Before the patch, the internal free-text search matched the raw card/set names and did not consume reviewed translated names. Sixty scoped translated-name queries—35 English-name queries for Japanese records and 25 Japanese-name queries for English records—missed their targets. After the pilot, all sixty retrieve the intended existing IDs, and all sixty native-name checks retain them. The pre-existing v2 resolver already handled these reviewed concepts: **59 unique and one multiple-candidate result before and after**, with no new unique identity resolutions. Its full variant/category/coordinate checks remain unchanged. These are backend regression results, not measured frontend success or market accuracy. No frontend was inspected or edited to manufacture a result.

## Bounded pilot choice and implementation

The pilot enriches 35 existing Japanese records: SV4A 4, SV2A 9, SV8 7, S12A 15. These are all eligible exact reviewed-name/category matches in four collector-relevant releases using the existing approved concept ledger. They are relevant to browsing Japanese supply for a Japan-to-US Buy&Ship journey; demand and supplier availability have not been measured. Twenty-five English comparison records use the same reviewed concepts across SV02, SV03.5, SV06, SV08 and SWSH10. This is a comparison sample, not counterpart or price equivalence.

The request permits up to 100 Japanese printings. This smaller batch addresses evidenced retrieval gaps rather than filling the limit with speculative identities. **Zero new real card identities are inserted.** Larger known identity/variant gaps remain held because the available evidence cannot safely prove the missing physical printing. No card or reference is duplicated.

Each binding preserves the exact existing card snapshot, provider, provider-native path, source revision and full-source SHA-256, language, region, product-release ID, source variant, current localized set snapshot, rights reference/status, metadata confidence and unresolved conflicts. The 60 original source files were hash-checked locally against the existing provenance, and the copied MIT license matches the pinned checkout. Historical retrieval timestamps were not recorded; they remain explicit nulls with `historical_snapshot_time_not_recorded`, separate from the actual inspection time. English region `ZZ` means unknown; it is not fabricated US distribution. Product-release scope never identifies a reprint date or a seller copy.

New language tags are normalized without changing existing `en`/`ja` IDs. Japanese legacy set fields remain supported; other languages use generic localized name/date fields. A localized date object missing the selected language produces unknown, rather than inheriting another region's date. The international builder accepts explicit language and `data`/`data-asia` roots, checks selected bytes against the pinned Git tree, rejects escapes/digital series, and leaves additional languages disabled for structural offer matching. Missing names and colliding finish/stamp declarations abstain. Existing committed import flags remain unchanged; newly extracted rows require explicit variant declarations rather than inferring eligibility from a filename.

`catalog_source_mapping` namespaces native IDs by provider, language, region, release and variant. Evidence is append-only; changed hashes/revisions append new evidence rather than overwrite old events. Stale snapshot, withdrawn concept or changed category evidence cannot contribute a locale search alias. Malformed, conflicting, unknown-rights, permission-widening, test-only and unresolved identities enter deterministic quarantine. A regional/release reuse of the same legacy printing is held instead of merging. The existing four-part card-ID model is preserved; simultaneous distinct same-language regional releases that collide in that model require a separately reviewed identity migration before admission. This pilot does not silently solve that ambiguity.

Existing graph `localization_counterpart`/`same_artwork` relationships remain separate records, with no new edges in this batch. Shared artwork, translated names, repeated collector numbers, foil/stamp differences and promos do not merge cards, offers, stock or price histories. Priceable units still separate raw condition and grading company/grade; asking observations, paid sales and destination-specific landed quotes remain separate tables. Catalogue inclusion grants no commerce or display permission. Buy&Ship remains the intended merchant of record; Pivota holds no customer funds.

The French synthetic fixture under `tests/fixtures/international/` is explicitly test-only and excluded from the pilot manifest. It exercises Unicode, parser/build/import support and absence of cross-language results. It is not real coverage or licensed supply.

## Next justified batch

The next bounded Japanese batch should fill release-name/date evidence for up to 65 existing records in 3–5 scopes with verified card-to-product bindings, plus unresolved promo/finish holds selected by actual Japan-to-US query evidence. Start with gaps already identified in SMH, DS, SC and LL, where existing audits explicitly require stronger card-to-product links. Reuse authorized cached text only if receipts and exact bindings qualify; preserve missing or multi-product dates and all unresolved variants. There is no authorization here for broad imports.

Traditional Chinese (`zh-tw`) is a **conditional next readiness study**, because pinned Asian sources contain localized names and regional release dates, including the S6a source that cannot fill Japanese gaps. It is not yet a justified real import: no demand sample or authorized Taiwan/region-specific supply feed has been provided. Admission requires Japan-to-US customer/query demand for that language, Buy&Ship-confirmed permitted supplier/URL coverage and destination handling, reviewed metadata rights, and complete source language/region/set/number/variant/release mappings for a small batch. If those conditions do not hold, continue Japanese evidence work. Raw row count does not decide the next language; no third real language has been admitted.

## Verification, reproduction and rollback

From the isolated worktree:

```sh
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-source-binding-v1.json --db /tmp/pokemon-before.sqlite3
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-pilot-v1.json --db /tmp/pokemon-after.sqlite3
python3 -m scripts.audit_international_coverage --before /tmp/pokemon-before.sqlite3 --after /tmp/pokemon-after.sqlite3 --output /tmp/pokemon-coverage-report.json
python3 -m unittest discover -s tests
node --test integrations/pivota/*.test.cjs
```

Outputs must not already exist. These commands are offline and do not serve the application or activate ingestion. The baseline test attempt ran 626 tests with six sandbox localhost failures and two skips. A permitted local rerun of the first patch passed 633 tests with two skips; **the final suite runs 641 Python tests (639 passes, two existing skips), plus 15 passing Node tests**. Independent review reports no remaining actionable findings. The final coverage audit verifies 66 hashes, the ordered 65-step prefix, exact unchanged ID/reference/facet rows, current native/translated retrieval, read-only snapshots and idempotent re-import (`inserted=0, unchanged=60, quarantined=0`). New tests cover source namespace collisions, regional release holds, stale/withdrawn aliases, malformed nested fields, Unicode, absent-language negatives, Ho-Oh, shared art, repeated numbers, promos, foil/stamp differences, missing localized fields and quarantined ambiguity.

Rollback requires no cloud action: continue building from the original source-binding manifest and original application revision. Discard the scratch pilot database rather than deleting historical evidence from a shared runtime. If the local patch was applied elsewhere, reverse it only in that isolated clean checkout (`git apply -R international-coverage.patch`); do not reset another session's worktree. Dockerfile still selects the original manifest, so the pilot is opt-in by explicit offline build only.

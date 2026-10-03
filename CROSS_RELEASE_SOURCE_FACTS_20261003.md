# Cross-release source-image evidence — 3 October 2026

## Frozen hundred completed

All **100 selected targets across twenty Japanese/English releases** now have explicit outcomes. The selection is deterministic and source-scoped, not random sampling or market demand. Every pinned source file and current endpoint was checked. The first CDN/API pass acquired 85 image files; fourteen were recovered from existing Japanese publisher coordinate references. One corrupt CDN transfer was retained as a failed decode, then recovered through a fresh transfer from the same URL. Final acquisition yields **99 decodable stock images and one unavailable image**.

Root inspected actual header/footer crops and full-card thumbnails for the first 98 images, saving readings before Gemini calls; the recovered Celebi scan was inspected separately before its fresh call. **Gemini 3.8 Flash made 101 actual Vertex calls for 99 images**, including two connection failures and their successful retries. Original failures and selected attempt bindings remain recorded. Gemini received image-only requests, with no catalog values, prior verdicts or search tools. Root knows catalog/project context and discloses it. These are two-model source correspondence observations, not independent ground truth, marketplace precision or real-user answer accuracy.

[Acquisition history](catalog/cross-release-source-facts-v1/assets-v4.json), [review chronology](catalog/cross-release-source-facts-v1/chronology-and-tests-v1.json), [attempt selection](catalog/cross-release-source-facts-v1/gemini-attempt-selection-v1.json).

## Results and concrete repairs

- **98 titles correspond** to their pinned source names; **99 header HP readings agree** between the inspections and with source HP. No new HP conflict was found in this selected cohort.
- **98 collector-number observations agree** with catalog text; one acquired image remains held because a trailing Prism Star title symbol is preserved without expanding it into an approved catalog name.
- **ミュウ, `ja:M6A:00B/103:holo`**, remains an acquisition hold. Its pinned source filename is `B.ts`, while the catalog numerator is `00B`. Both the guarded convention route and an explicitly disclosed native-filename candidate failed to acquire a usable image. No printed number is inferred and no identity is remapped.
- Typography fragment boundaries and curly/straight apostrophes now normalize in comparison keys. Raw model readings remain intact; trainer names, mechanic text and symbol anchors remain distinct.
- Known adjacent rarity labels are separated only from an otherwise complete numeric collector fraction when computing a comparison key. This resolves five false holds from readings such as `003/187 RR`; the raw strings remain visible. Missing denominators, arbitrary suffixes and differing numeric values remain unconfirmed. The original six-hold compilation is retained; the corrected final compilation is a separate version.

[Final number outcomes for all hundred](catalog/cross-release-source-facts-v1/number-compilation-v2.json), [final source-fact compilation](catalog/cross-release-source-facts-v1/compilation-v2.json). These facts do not identify physical foil variants from stock images, verify seller copies or add price equivalence.

## Cumulative state and preservation

The [55-input build manifest](catalog-build-manifest-cross-release-source-facts-v1.json) retains all previous 53 ordered input objects/hashes and appends 99 number events plus 99 source-fact events. The cumulative layer now contains:

| Evidence | Current total |
|---|---:|
| Exact source-image fact subjects | 148 |
| Title correspondence advisories | 147 |
| HP source agreements / absent headers / conflicts | 138 / 9 / 1 |
| Number-evidence subjects | 178 |
| Usable scoped number observations / holds | 172 / 6 |
| Catalog denominators not established as visible text | 25 |
| Stale fact or number subjects | 0 |

The prior Ho-Oh HP conflict remains explicit. [Preservation](catalog/cross-release-source-facts-v1/preservation-v1.json) checks **42 base tables**, all **79 prior number rows**, and all **49 prior fact rows**. Only specifically identified import bookkeeping times are excluded from base-table semantic comparison; each difference is retained. Catalog records, coordinates, aliases and graph decisions are preserved. The catalog remains **70,006 source records / 45,438 language-set-number coordinates / 33,543 structurally eligible records**. The graph remains **63 reviewed same-artwork pairs, eleven reviewed differences and 594 proposals**. No physical, display or automatic-offer approval is added. Image observations are neither new catalog SKUs nor new relationship edges.

[Coverage](catalog/cross-release-source-facts-v1/coverage-v1.json).

## Verification and delivery

**563 Python tests and twelve Node client/operation tests pass** on the final runtime. Earlier 561- and 562-test runs remain recorded as intermediate checks. Local replays pass **116 new-batch checks and 21 prior-fact checks**. Ten newly authored comparison questions test source conflicts, title markers, repeated artwork across releases, trainer ownership, missing images and physical/price boundaries; these are engineering checks, not blind user measurement.

Private Cloud Run revision **`pokemon-commerce-index-00038-jsw`** serves 100% of staging traffic. [New cloud checks](catalog/cross-release-source-facts-v1/private-cloud-replay-v1.json) pass **118/118**; [prior fact checks](catalog/cross-release-source-facts-v1/prior-facts-cloud-v1.json) pass **23/23** on the same immutable image. These **141 checks include four repeated unauthenticated 403 denials**. Final runs record no transport errors. Six actual Node caller journeys retain the existing timeout/retry policy. [Delivery bindings](catalog/cross-release-source-facts-v1/delivery-validation-v1.json) verify source/review/runtime/snapshot/input hashes and unchanged private deployment. Only the two final compiled evidence files enter the runtime image; raw scans, reviews, queues and diagnostics remain excluded.

## Next sequence

1. Process the [next frozen thousand targets](catalog/cross-release-source-facts-v1/next-thousand-targets-v1.jsonl): fifty distinct unreviewed coordinates per release, Japanese/English 500 each, with deterministic bucket selection and explicit fallbacks. All source-file bytes and endpoint snapshots are checked; **zero new images, model reviews or evidence imports are claimed for this queue**. Acquisition/recovery/compilation tools accept an explicit expected cohort size. Work can continue while Buy&Ship's feed is unavailable.
2. Review the [fourteen frozen artwork-pair hypotheses](catalog/cross-release-source-facts-v1/next-artwork-pair-targets-v1.jsonl), using already bound images across languages/releases and near-neighbor contrasts. Conduct separate actual two-image reviews before adding any graph edge; title/HP agreement alone is insufficient. No pair review or new graph decision is claimed yet.
3. Keep the filename/number discrepancy, Prism Star interpretation and existing source/number holds in targeted evidence queues. Extend physical finish, seller-copy condition and cross-region price comparability only when the corresponding evidence exists.
4. Attach authorized marketplace offers when Buy&Ship supplies the listing feed and data-use scope. Price freshness, accepted price, landed cost and transaction handoff remain separate from catalog evidence.

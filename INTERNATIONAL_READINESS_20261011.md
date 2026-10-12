# International coverage — fourth offline implementation stage

A read-only release-readiness planner now turns the fixed 65 held Japanese coordinate families into exact evidence requests. It flags the four publisher-caption anchors separately from the remaining 61 provider declarations. This stage admits **zero identities, release dates, aliases or permissions**. The source catalogue remains 70,006 internal source-version/family records, with all 65 identity holds intact.

The isolated branch remains `codex/international-coverage-20261011`, based on `f499b46f7f0898c5c0478c53fef960d435f1765f`. Original checkout and creator frontend remain untouched. No push, deployment, cloud permission change, new source retrieval, artwork or marketplace-price import, live ingestion, purchase or payment activation.

## What the existing evidence supports

The authorized cache contains 40 receipt-bound publisher HTML documents. The four exact card pages and their captions remain checked evidence. The SMH caption links to `https://www.pokemon-card.com/info/2018/20180420_001166.html#1`; that target document is absent from the cache. A related GX-start-deck family page exists at `/ex/smh/index.html`, but it is not the caption's exact linked target. Its sale-image alternative text supplies the marker **`7.13[金] 発売!!`**, with no year. Campaign URLs containing `2018` do not supply a year for that marker. The planner records month 7/day 13 and keeps year, release date and physical region null. It omits the price/copy text following the marker.

DS, SC and LL have unlinked captions and no corresponding product documents in this cache. Their source names and set headers cannot manufacture a product URL, date or physical-printing binding. All four anchors still require exact product-release and physical evidence.

The fixed queue produces:

| Evidence work | Work groups | Exact subjects retained |
|---|---:|---:|
| Missing exact publisher card pages | 61 | 61 |
| SMH news document | 1 | 17, with separate grass/fire caption and fragment selectors |
| Unlinked DS / SC / LL product-document discovery | 3 | 16 / 16 / 16 |
| Publisher-caption anchor priority flags | 4 | SMH35030, DS27836, SC28616, LL26001 |
| Physical finish, stamp/edition and distribution-region evidence | Per subject | All 65 |

There are 65 request groups: 61 card pages plus four product-document groups. Their known document URLs total 62; three product groups explicitly have no URL. These are work groups, not release identities or SKUs. Every group retains each exact candidate ID, card ID, language, set, collector number, source revision/hash and declaration status. SMH `#1` and `#2` selectors remain separate inside the shared document request. Similar artwork, names, numbers and captions cannot reduce identity subjects or transfer approval.

## Implemented operator workflow

`scripts.plan_international_release_evidence` is an offline operator command. It reads the explicit 68-step stage-3 manifest and canonical installed candidate/caption payloads, validates current evidence and exact provider/native references, verifies all source-input hashes, and indexes only the authorized local cache. It has no network fallback, importer or database-write path. Existing runtime interfaces and database schema are unchanged.

The planner rejects stale or uninstalled evidence, duplicate/non-Japanese subjects, references shared ambiguously by variant siblings, namespace/redirect problems, conflicting receipts, changed cache bytes and paths escaping the cache. Known cached documents remain `cached_needs_separate_review`; their presence cannot promote a binding. Unknown product links remain null. All physical, price-comparison, display, image-display, offer and purchase claims remain false.

Independent review found an input-integrity gap in the first draft: source/cache files could change between hashing and parsing. The final code parses and hashes the same receipt bytes, verifies the exact SMH bytes it observes, freezes manifest/input signatures, and rechecks all 151 inspected manifest, input, receipt and HTML files plus the receipt inventory before returning. Concurrent changes abort the plan. Historical retrieval times remain separate from the new inspection time (`2026-10-11T11:41:41Z`). The source database SHA-256 stays `43efee62091ce157ea7d14182262c5c3a68f2e5e86058dbc5287da29b6cc1b82`.

Publisher cached text has no display grant. The previously reviewed pinned source-metadata licence remains scoped to metadata; it grants no publisher artwork or public display approval. The artifact contains receipts/hashes and bounded factual text, not HTML, images, merchant purchase links or prices. No counterpart relationship or automatic offer join is created. Stock, raw condition, grading company/grade, sold/asking prices and destination landed cost remain separate. Buy&Ship remains the intended merchant of record; Pivota does not hold customer funds.

## Before and after

The stage-3 database is read byte for byte without mutation. Consequently all existing catalogue, retrieval, rights, graph, held-candidate, quarantine and trading records are unchanged.

| Measure | Stage 3 | Stage 4 |
|---|---:|---:|
| Internal source-version/family records | 70,006 | 70,006 |
| English / Japanese records | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Distinct internal identity tuples | 70,006 | 70,006 |
| Source-declared variants excluding unverified labels | 49,916 | 49,916 |
| Unresolved labels / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical printing count | Unknown | Unknown |
| Structural matching eligibility | 33,543 | 33,543 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Packaged image files | 0 | 0 |
| Inspected source-image subjects / distinct hashes | 1,141 / 1,141 | 1,141 / 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Localized bindings / exact publisher-caption events | 60 / 4 | 60 / 4 |
| Japanese records missing release names / dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Current holds / quarantine entries | 65 / 65 | 65 / 65 |
| Manifest inputs | 68 | 68 |

The October2 inventory is reproduced without a count difference. Internal identities and source variants are not independently verified physical cards. Whole-catalog image availability remains unmeasured; image/offer absence is not identity absence. Pocket/digital-only cards remain excluded. The French fixture remains test-only outside the real manifest. Real third-language admission still requires demand, authorized Buy&Ship supply and complete licensed source coverage; Traditional Chinese remains a conditional readiness study.

## Verification and reproduction

The final Python suite runs **685 tests: 683 pass and two existing skips**. All 16 new readiness tests pass independently as well. They cover exact/unchanged IDs and tables, provider declarations versus checked captions, shared-caption and news-fragment grouping, repeated numbers across sets, foil/stamp reference ambiguity, cross-language exclusions, stale/uninstalled evidence, false permissions, cache corruption/redirect/collision/path escape, partial-date uncertainty, input mutation and output overwrite refusal. The existing international/product/release regressions pass in the full run. Stage 3's 15 passing Node results carry forward; this stage changes no Node/runtime code.

The real fixed-queue plan and independent rebuild are byte-identical. All 68 input hashes, the original ordered65 inputs and stage2's67-step prefix are preserved. All 151 inspected file signatures and input database bytes remain exact. Compilation and staged/unstaged Git whitespace checks pass. GPT-6.1 Sol high independent review reports no remaining actionable findings after the integrity fix.

With an existing stage 3 snapshot and authorized cache, use fresh output paths:

```sh
python3 -m scripts.plan_international_release_evidence --db /tmp/pokemon-stage3.sqlite3 --cache <existing-authorized-cache> --output /tmp/pokemon-release-readiness.json --inspected-at <actual-inspection-time>
python3 -m unittest tests.test_release_readiness -v
python3 -m unittest discover -s tests
```

Reproduce the frozen artifact with `--inspected-at 2026-10-11T11:41:41Z` and unchanged authorized bytes. If building the snapshot first, explicitly use `catalog-build-manifest-international-product-text-v1.json`. Dockerfile still explicitly selects the original `catalog-build-manifest-source-binding-v1.json`; neither the Dockerfile nor the older CLI default is changed.

Rollback stage 4 by retaining the stage 3 application patch and 68-step snapshot, discarding this operator plan, and reversing the stage 4 incremental patch only in its isolated checkout. There is no database migration, new manifest input or cloud rollback. Preserve historical evidence and other sessions' work.

## Next justified batch

Complete the four anchor product bindings first: qualify the exact SMH news target and obtain source-supported product documents for DS/SC/LL through an authorized cached or pinned, licence-reviewed route. Preserve initial-product versus copy-date and language/physical-region distinctions. Then review the 61 exact card-page requests with their retained native IDs; do not expand the queue based on shared captions. Physical finish/edition and region need separate evidence for all 65 subjects. The current cache justifies no positive release date, physical printing, broad import or deployment.

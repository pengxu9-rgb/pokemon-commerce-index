# International coverage — third offline implementation stage

Four existing Japanese coordinate families now support internal search by their exact cached publisher product captions. The catalogue still contains 70,006 internal source-version/family records; this stage adds **zero identities and zero release or physical-printing approvals**. All 65 stage-2 identity holds remain current. The isolated branch is `codex/international-coverage-20261011`, based on `f499b46f7f0898c5c0478c53fef960d435f1765f`; no creator frontend, push, deployment, cloud permission or live ingestion/purchase/payment changes.

## Evidence and retrieval gain

The stage-2 held queue contains four exact cached official card-page anchors. This stage verifies the raw cached HTML against the historical receipts, titles and complete coordinates, then checks each caption against the pinned PTCG source declaration. It preserves historical retrieval times from October 2 and records the October 11 inspection separately (`2026-10-11T10:57:06Z`). The bounded compiler has no network fallback.

| Existing coordinate family | Publisher native ID | Exact product caption | Link classification | Caption search before → after |
|---|---:|---|---|---:|
| ja:SMH:001/131:unverified | 35030 | ポケモンカードゲーム サン&ムーン GXスタートデッキ「草ラランテス」 | Official news article | 0 → 1 |
| ja:DS:001/020:unverified | 27836 | ポケモンカードゲームBW 拡張パック「ドラゴンセレクション」 | Unlinked text | 0 → 1 |
| ja:SC:001/020:unverified | 28616 | ポケモンカードゲームBW コンセプトパック「シャイニーコレクション」 | Unlinked text | 0 → 1 |
| ja:LL:001/040:unverified | 26001 | ポケモンカードゲーム 強化パック「ロストリンク」 | Unlinked text | 0 → 1 |

The before/after searches use each full caption and `language=ja`. Each new result is the exact existing anchor above; English filtering returns zero. Neighboring coordinates do not inherit the caption. Native-name retrieval and all 60 stage-1 translated searches and v2 question resolutions are preserved. These four checks measure scoped retrieval gains on selected evidence, not general Japanese search accuracy or customer demand.

Stage 2's historical `official_card_page_has_no_product_link` hold used a narrower `/ex/` and `/products/` product-page allowlist. Stage 3 identifies a real SMH `/info/2018/20180420_001166.html#1` **news article** link outside that allowlist. The historical hold and its payload remain unchanged; the new caption evidence does not convert a news link into a verified release binding. DS, SC and LL have plain caption text in these cached pages. TCGdex headers alone provide no missing card identities or cross-provider bindings.

The named SMH deck is evidence for this coordinate family only. It is not a name for every SMH printing. The compiler accepts only the exact caption's own publisher anchor, rejecting empty, unrelated, grafted, nested or unbalanced anchors and ambiguous list items. Source purchase-button text and its malformed legacy merchant URL stay in the historical held lead and are excluded from the caption artifact. No merchant URL is repaired, followed or joined to an offer.

## Backend boundaries

`catalog_product_text` stores four append-only evidence events, bound to the installed held candidate and its exact identity, sibling set, references, source hash and release snapshot. The publisher namespace, native ID, URL, revision (`sha256:<hash>`), retrieval time, inspection time and rights status are explicit. Missing physical region and product/variant confidence stay null. Source-text correspondence is 1.0 for checked bytes and text; it does not express confidence in a release date or physical printing.

Internal card/search results can expose optional `publisher_product_text` context. Internal search uses current captions only for their exact card IDs. Source/reference/release drift, added variant siblings or test-only status makes the old evidence stale and removes its caption from retrieval while retaining history. Re-import is idempotent. Malformed or forged input enters identity quarantine; the manifest builder aborts if its caption batch is quarantined. Older snapshots remain readable without the new table.

All physical, display, image-display, price-comparison, automatic-offer, purchase and release-binding claims remain false. The existing MIT source-metadata review does not grant publisher text or artwork display rights; publisher evidence is labelled `existing_cached_factual_text_internal_only`, with no metadata-license grant. No raw HTML or artwork is packaged in the build. Cross-language cards and shared artwork remain relationships, and repeated numbers/promos/foil/stamp differences cannot transfer this evidence or merge SKUs. Offers, stock, condition, grading, asking versus sold prices and destination-specific landed cost remain separate. Buy&Ship remains the intended merchant of record; Pivota does not hold customer funds.

## Before and after this stage

| Measure | Stage 2 | Stage 3 |
|---|---:|---:|
| Internal source-version/family records | 70,006 | 70,006 |
| English / Japanese records | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups | 45,438 | 45,438 |
| Distinct internal identity tuples | 70,006 | 70,006 |
| Source-declared variant records excluding unverified labels | 49,916 | 49,916 |
| Unresolved labels / coordinate families | 20,090 / 20,090 | 20,090 / 20,090 |
| Independently verified physical printing count | Unknown | Unknown |
| Structural matching eligibility | 33,543 | 33,543 |
| Display / image display / automatic offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Catalogue image files packaged | 0 | 0 |
| Inspected source-image subjects / distinct hashes | 1,141 / 1,141 | 1,141 / 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Scoped localization bindings | 60 | 60 |
| Japanese records missing release name / date | 7,745 / 8,114 | 7,745 / 8,114 |
| Current held qualification events / stale / admitted identities | 65 / 0 / 0 | 65 / 0 / 0 |
| Quarantine entries | 65 | 65 |
| Publisher-caption events / exact coordinate subjects | 0 / 0 | 4 / 4 |
| Verified product-release bindings added | 0 | 0 |

These counts reproduce the October 2 inventory with no source-count difference; the 70,006 rows are not independently verified physical cards. Whole-catalog image availability remains unmeasured. Missing images and missing offers do not imply missing identities. Pocket/digital-only records remain excluded, and the synthetic French fixture stays test-only outside the real manifest. No new provider mappings, counterpart edges or whole-set metadata are added.

The opt-in `catalog-build-manifest-international-product-text-v1.json` contains 68 ordered, hash-bound steps: the original 65 source-binding inputs, unchanged stage-1 locales, unchanged stage-2 held queue, and the four caption events. Dockerfile still explicitly uses `catalog-build-manifest-source-binding-v1.json`. The snapshot CLI's older default is not used for these builds.

## Verify and rollback

Use fresh paths:

```sh
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-qualification-v1.json --db /tmp/pokemon-stage2.sqlite3
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-product-text-v1.json --db /tmp/pokemon-stage3.sqlite3
python3 -m scripts.audit_international_product_text --before /tmp/pokemon-stage2.sqlite3 --after /tmp/pokemon-stage3.sqlite3 --output /tmp/pokemon-stage3-audit.json
python3 -m unittest discover -s tests
node --test integrations/pivota/*.test.cjs
```

The coverage audit checks all 68 input hashes and exact preceding prefixes; installation of the exact four payloads in the actual after snapshot; four caption queries; preserved 60 locale queries and full v2 responses; unchanged catalogue, rights, trading, held-candidate and quarantine records; idempotent re-import (`inserted=0, unchanged=4, quarantined=0`); and unchanged input database bytes. Incremental append preserves every pre-existing table/column exactly, including historical timestamps.

Independent full rebuilds continue to differ only in four existing importers' generated bookkeeping columns: relationship `asserted_at`, identity-exception `applied_at`, rarity-correction `applied_at`, and number-rule `applied_at`. Only these named columns are excluded across independent rebuilds; none is excluded in the incremental comparison. Detailed final test and independent GPT-6.1 Sol high review results accompany the patch in `catalog/international-product-text-v1/`.

The final Python suite runs 669 tests: **667 pass and two existing skips**. All 15 Node tests pass. The new product-text suite includes 15 checks covering idempotence, Unicode/localized search, source drift/collisions, cross-language and adjacent-coordinate exclusions, added foil/stamp siblings, missing fields, malformed permissions, exact snapshot installation, parser ambiguity and read-only CLI/HTTP behavior. Existing international tests cover shared artwork, promos and repeated collector numbers. Compilation and Git whitespace checks pass. Independent review found and corrected the ambiguous-anchor/list parser cases before final verification.

To recompile the four events, use a stage-2 database and the authorized existing `release-metadata-next-v1-cache` with `python3 -m scripts.build_publisher_product_text --db <stage2-db> --cache <existing-cache> --output <fresh-jsonl> --inspected-at 2026-10-11T10:57:06Z`. The local cache remains outside the delivered artifact. Recompilation after the parser fixes produces identical event bytes.

Rollback stage 3 by retaining the 67-step stage-2 manifest/database and stage-2 application patch, discarding the stage-3 scratch database. Reverse the incremental patch only in an isolated checkout where it applies cleanly. To roll back all stages, use the original commit and explicit 65-step source-binding manifest. Preserve historical evidence and another session's work. No cloud rollback is needed.

## Next justified expansion batch

The next batch is release/printing evidence completion for these same four anchors, then the remaining 61 held coordinates. Qualify exact card-to-product links and language/region/initial-release scope through authorized cached or pinned, reviewed metadata. The SMH news target has not been retrieved by this stage; its URL and year are not release-date evidence. Unlinked DS/SC/LL captions are not permission to manufacture links. Physical finish and edition claims still require separate printing evidence.

Real third-language admission remains conditional on measured query demand, Buy&Ship-confirmed authorized supply and complete licensed source coverage. Traditional Chinese remains a readiness study, not an approved import. The current evidence justifies no broad catalogue, price, artwork or language import and no deployment.

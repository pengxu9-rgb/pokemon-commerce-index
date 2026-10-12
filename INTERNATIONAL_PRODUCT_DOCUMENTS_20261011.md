# International coverage — stage 5 product-document qualification

Three pinned TCGdex set headers qualify as provider-document facts. All four exact Japanese anchors remain held: the authorized evidence does not establish a publisher-product or cross-provider physical-printing binding. This stage records a completed, bounded qualification outcome for each anchor, including its unresolved conflicts. It adds no catalogue identities, release dates, aliases, permissions or trading activity.

## Evidence and qualified scope

The compiler verifies these local metadata bytes against the Git tree at `a211f11f3ba57d56c65c5ac33be35b77d3280757`. The licence matches the existing reviewed `catalog/TCGDEX-LICENSE` bytes. Small raw headers and the MIT licence are preserved under `catalog/international-product-documents-v1/source-snapshots/`; no publisher HTML, artwork or marketplace data is packaged.

| Provider document | Declared localized names | Official count declaration | Scalar date declaration | Pinned Git blob |
|---|---|---:|---|---|
| `data-asia/BW/DS.ts` | ja: ドラゴンセレクション; ko: 드래곤 컬렉션 | 20 | 2012-01-27 | `9ae18668cea0f427db5079ec923933eee6e65453` |
| `data-asia/BW/SC.ts` | ja: シャイニーコレクション; ko: 샤이니 컬렉션 | 20 | 2013-02-01 | `d73bdeac0a97a28d338e47aacb993f5e30a3dd0c` |
| `data-asia/L/LL.ts` | ja: 強化パック ロストリンク | 40 | 2010-04-16 | `35811b4f87fec2454a6fe72279c10647dc3d799a` |

These dates have no explicit language/region or initial-product-versus-copy-release scope. A Japanese-only name in LL does not prove distribution region. The pinned tree contains no card entries for DS, SC or LL, so it provides no exact card bridge to the PTCG anchors. Name/count similarities remain candidate leads, with no verified equivalence or SKU relationship. Korean header text does not admit Korean printings or change the third-language proposal.

The three `provider-documents.jsonl` records preserve provider/native ID, full revision, Git blob ID, SHA-256, licence hash/reference, literal facts, inspection time and confidence separately from unknown semantic, anchor and physical accuracy. Historical retrieval times were not recorded and remain explicitly null; inspection is `2026-10-11T12:03:38Z`. Metadata licence review does not grant image or public-display approval.

| Exact held anchor | Qualification outcome |
|---|---|
| `ja:SMH:001/131:unverified` / publisher35030 | Exact `/info/2018/20180420_001166.html#1` target remains absent from the authorized cache. No eligible pinned provider header is selected. The related family page supplies only `7.13[金] 発売!!`, without a year, and cannot replace the exact grass-deck caption target. |
| `ja:DS:001/020:unverified` / publisher27836 | Provider header bytes and declarations qualified; exact publisher product document and cross-provider card bridge unqualified. |
| `ja:SC:001/020:unverified` / publisher28616 | Provider header bytes and declarations qualified; exact publisher product document and cross-provider card bridge unqualified. |
| `ja:LL:001/040:unverified` / publisher26001 | Provider header bytes and declarations qualified; exact publisher product document and cross-provider card bridge unqualified. |

`anchor-outcomes.jsonl` keeps the four exact IDs, candidate IDs, existing caption evidence IDs, original provider evidence and hold reasons, plus the optional provider-document lead. Every outcome is `held_anchor_binding_unqualified`. Card release date and physical distribution region remain null. Finish, stamp/edition and distribution region still need separate physical evidence; the three headers cannot qualify the adjacent 61 card coordinates by caption inheritance.

## Before and after

The original October2 audit is reproduced without a count difference. The 70,006 source-version/family records are not independently verified physical-card totals. The explicit original source-binding manifest retains all65 ordered hash-bound inputs. Stage3's68-step manifest remains the candidate snapshot, and Dockerfile still selects the original manifest. This operator artifact is outside the runtime import manifest.

| Measure | Stage 4 | Stage 5 |
|---|---:|---:|
| Qualified provider-header documents | 0 | 3 |
| Recorded exact-anchor document outcomes | 0 | 4 held |
| Qualified exact publisher-product / cross-provider bindings | 0 / 0 | 0 / 0 |
| Internal source records: English / Japanese | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups / distinct internal identity tuples | 45,438 / 70,006 | 45,438 / 70,006 |
| Source-declared variants / unresolved coordinate families | 49,916 / 20,090 | 49,916 / 20,090 |
| Independently verified physical printing total | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,543 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Packaged image files; inspected image subjects / hashes | 0; 1,141 / 1,141 | 0; 1,141 / 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Localized bindings / exact publisher-caption events | 60 / 4 | 60 / 4 |
| Japanese records missing release names / dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Held candidates / quarantine entries / manifest inputs | 65 / 65 / 68 | 65 / 65 / 68 |

The existing database is byte-identical at SHA-256 `43efee62091ce157ea7d14182262c5c3a68f2e5e86058dbc5287da29b6cc1b82`. Whole-catalogue image availability remains unmeasured; missing images and offers are distinct from missing identities. Pocket/digital cards stay excluded. Stock, condition, grading company/grade, sold versus asking prices and destination landed cost remain separate from identity. Buy&Ship remains the intended MoR; Pivota holds no customer funds. Creator frontend, runtime/schema, cloud permissions, ingestion, purchases and payments are unchanged; nothing is pushed or deployed.

## Operator reproduction and rollback

The compiler recomputes the current installed readiness against the explicit68-step manifest, validates all input hashes, checks local pin/license bytes and the absence of pinned provider card entries, extracts literal top-level declarations, and emits three source documents plus four outcomes. It disables lazy Git fetching, overrides origin with `/dev/null` for each pin command and rejects additional remotes. There is no network fallback or database write path. It rechecks source/licence bytes and recomputes readiness before returning, rejecting input drift. Duplicate fields, dynamic/malformed dates, unsupported syntax, ambiguous coordinates, altered blobs and output overwrite attempts fail closed.

```sh
python3 -m scripts.qualify_international_product_documents --db /tmp/pokemon-stage3.sqlite3 --cache <authorized-existing-cache> --source-repo <existing-pinned-tcgdex-checkout> --output-dir /tmp/pokemon-product-documents --inspected-at <actual-inspection-time>
python3 -m unittest tests.test_product_document_qualification -v
python3 -m unittest discover -s tests
```

Use a fresh output directory. Reproduce the saved evidence with `--inspected-at 2026-10-11T12:03:38Z` and identical authorized bytes. The seven compiled files rebuild byte-identically. Final Python tests run707 cases:705 pass and two existing skips; all22 new tests pass independently. Compilation and Git whitespace checks pass. Stage3's15 Node test passes carry forward because stages4–5 change no Node/runtime code. GPT-6.1 Sol high independent review found two draft parser/cache-status issues; both are fixed, covered by regressions and independently reviewed with no remaining actionable findings. The accompanying test and review records preserve the details.

Rollback stage5 by retaining stage4's checkout and stage3's68-step database, discarding only the new operator artifact, and reversing the stage5 incremental patch in its isolated checkout. No database migration, source-history rewrite or cloud rollback is needed. Preserve all historical stages and other sessions' files. The cumulative patch includes stages1–5; apply the incremental patch only to the exact stage4 patch state.

## Next justified evidence batch

Remain within the four anchors. Qualify SMH's exact linked news document and the missing DS/SC/LL publisher-product documents through an already authorized cached or pinned, licence-reviewed route, or obtain explicit exact card-to-product bridges with language/region and initial-release/copy-date scope. DS/SC/LL product URLs are still unknown and must not be guessed from set names. Physical finish, stamp/edition and distribution region require separate proof even after document binding. Review the61 retained exact card-page requests only after the anchor evidence supports doing so. The available bytes justify no positive card release date, broad import or deployment.

# Missing Japanese rarity evidence — 2026-09-30

## Result

Checked 500 previously missing rarity values against exact official Japanese card pages. Applied **497 verified fills across 13 sets**. Three name-qualifier cases remain deferred. This adds metadata evidence to existing identities; it adds no new identities, marketplace observations or verified graph edges.

For **SV4a 347/190, ミュウex**, the [official card page](https://www.pokemon-card.com/card-search/details.php/card/45133) exposes `ic_rare_sar.gif`: the corrected rarity is **SAR**. The catalog identity remains `ja:SV4A:347/190:holo`; the source's `holo` variant label is unchanged by this rarity audit.

| Set | Verified fills |
| --- | ---: |
| S12 | 27 |
| S9 | 27 |
| S9A | 26 |
| SV1A | 28 |
| SV1S | 29 |
| SV2D | 28 |
| SV2P | 28 |
| SV3 | 33 |
| SV3A | 13 |
| SV4A | 170 |
| SV4K | 29 |
| SV4M | 29 |
| SV5A | 30 |

The Japanese **TCGdex-sourced, match-eligible** missing-rarity subset fell from **903 to 406**. This is a source-specific count, not the total number of missing rarities across every catalog source. The 406 include the three deferred rows and other cards without a unique supported reference selected by this audit.

## Evidence and import rules

[`scripts/audit_missing_card_rarities.py`](scripts/audit_missing_card_rarities.py) selects cards with missing rarity, one pinned reference at the same set and number, matching normalized names and a recognized reference rarity icon. It freezes the candidate list before collection. Each official page must confirm set, number, name and icon. A reference alone cannot authorize a fill.

[`catalog/missing-rarity-v1/`](catalog/missing-rarity-v1/) records the input hashes, 500 candidates, official page checks, 497 correction rows and summary. Fetches use two workers, bounded retries and a resumable checkpoint. Retained evidence contains metadata and page hashes; no images or prices are collected by this audit.

Imports bind corrections to the original name, original rarity (including null), source provenance, official URL and page hash. An exact source reimport preserves the overlay; changed source coordinates fail the binding check. The schema migration retains earlier correction evidence while allowing a missing original rarity.

## Deferred name qualifiers

| Identity | Source name | Official heading | Proposed rarity |
| --- | --- | --- | --- |
| `ja:SV1A:095/073:holo` | ボスの指令（ゲーチス） | ボスの指令 | SR |
| `ja:SV1A:100/073:holo` | ボスの指令（ゲーチス） | ボスの指令 | SAR |
| `ja:SV1S:099/078:holo` | 博士の研究（オーリム博士） | 博士の研究 | SR |

Their official pages are [43300](https://www.pokemon-card.com/card-search/details.php/card/43300), [43305](https://www.pokemon-card.com/card-search/details.php/card/43305), and [43059](https://www.pokemon-card.com/card-search/details.php/card/43059). The audit labels them `rejected` because the exact name predicate fails. This does not establish an identity error. Qualifier evidence is needed before a separate correction can be admitted.

## Current build and resolver effect

[`catalog-build-manifest-rarity-v2.json`](catalog-build-manifest-rarity-v2.json) contains the earlier 35 M6 corrections and these 497 fills: **532 rarity overlays**, 55,167 internal identities and 33,543 match-eligible identities. Earlier manifests and frozen diagnostic cohorts are retained.

```bash
python3 -m scripts.build_catalog_snapshot --db catalog.sqlite3
```

The v9 SV4a 347/190 question now exposes the SAR candidate instead of failing on `rarity_not_verified`. It still lacks explicit card-language evidence, so its result is `insufficient_printing_coordinates`. Supplying Japanese language resolves the exact catalog identity. It does not supply condition, a priceable unit or a current quote.

Docker now builds this corrected manifest. This revision has not been deployed to Cloud Run.

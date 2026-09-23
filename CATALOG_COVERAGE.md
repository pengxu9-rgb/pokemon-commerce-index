# Japanese card catalog coverage — 23 September 2026

The catalog can be built without Buy&Ship. It currently contains **26,580 internal card identities across 342 set codes**, plus **24,039 source reference records**. These are card metadata, not live offers or prices.

| Layer | Records | Use in offer matching |
| --- | ---: | --- |
| TCGdex pinned metadata | 16,347 printings in 126 sets | Structurally eligible for exact set, number and finish matching; accuracy against live listings is not yet measured |
| Supplemental Japanese reference candidates | 10,233 unique set-and-number candidates in 229 sets | Disabled until the printing and finish are verified |
| Second-source reference records | 24,039 | Internal comparison only; 10,522 set-and-number groups overlap the TCGdex seed |

The previous 3,621-row selected seed is wholly contained in the broader TCGdex extract. The supplemental layer includes **87 S6a cards** from the second source; they remain unverified for price matching. No catalog record is currently approved for public display, and no images, image URLs, attacks, effects or rules text are shipped in these extracts.

A ready-to-query SQLite snapshot is included as [`catalog-index.sqlite3`](catalog-index.sqlite3). It has no live marketplace listings or prices.

## Source snapshots

- [TCGdex cards-database](https://github.com/tcgdex/cards-database), commit `a211f11f3ba57d56c65c5ac33be35b77d3280757`. The repository describes its database as MIT licensed. We extracted identity text from its `data-asia` TypeScript files and recorded each source path and SHA-256.
- [type-null/PTCG-database](https://github.com/type-null/PTCG-database), commit `bc5a2698eb9af858feb0280d579fd5fd0f0273e2`. Its Japanese JSON appears to derive from the Pokémon official site. Its repository license does not settle rights to Pokémon content, so this source remains internal and cannot automatically contribute to offer matching or public display. We retained set, number, name, rarity, basic card attributes and source ID only.

## Audit results

- TCGdex: 174 `data-asia` set directories scanned, 18,442 card files, 13,397 parsed card files, 16,347 printing identities. Of 5,046 gap rows, 4,994 have no Japanese name in that source. Many are non-Japanese Asian editions; 808 missing files belong to sets whose headers do contain Japanese set names. Fifty files have repeated, indistinguishable variant declarations and remain unresolved.
- Supplemental source: 24,039 records, 10,233 new unique set-and-number candidates, 525 new groups with multiple source records, 1,468 records lacking a usable set/number identity, and 162 overlapping groups whose Japanese names disagree with TCGdex. Conflicts remain visible in the audit and are not silently merged.
- `catalog_status` in the pilot database reports 26,580 identities, 16,347 structurally match-eligible, 10,233 match-disabled, 24,039 reference records and zero display-approved.

## Files and reproduction

The broad TCGdex extract is [`catalog/ja-all-available.jsonl`](catalog/ja-all-available.jsonl), with [set metadata](catalog/ja-all-sets.jsonl), [coverage report](catalog/coverage-all-available.json) and [per-file gaps](catalog/ja-all-gaps.jsonl). The second source has a [minimal reference extract](catalog/ptcg-jp-reference.jsonl), [unverified candidates](catalog/ptcg-jp-candidates.jsonl), [audit](catalog/ptcg-jp-audit.json) and [gaps](catalog/ptcg-jp-gaps.jsonl). Both source licenses are copied under `catalog/` for attribution; underlying card art and marks remain with their rights holders.

With the two pinned public repositories checked out locally, `scripts.build_tcgdex_full` and `scripts.build_ptcg_reference` reproduce the extracts. The scripts fail on an unexpected commit SHA and create new output files instead of silently overwriting an earlier audit.

Next catalog work should reconcile high-value S6a and the 162 name conflicts against independent evidence, establish finish identities for selected supplemental cards, and seek an explicit public metadata/image license before exposing the catalog in a product. Listing volume from a permitted marketplace feed will decide which remaining sets deserve deeper curation.

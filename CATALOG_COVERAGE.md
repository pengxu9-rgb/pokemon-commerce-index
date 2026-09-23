# Japanese and English card catalog coverage — 23 September 2026

The catalog can be built without Buy&Ship. It currently contains **44,838 internal card identities across 415 language-and-set combinations**: 27,092 Japanese identities in 342 sets and 17,746 English identities in 73 sets, plus 24,039 Japanese source reference records. These are card metadata, not live offers or prices.

| Layer | Records | Use in offer matching |
| --- | ---: | --- |
| TCGdex pinned metadata | 16,347 printings in 126 sets | Structurally eligible for exact set, number and finish matching; accuracy against live listings is not yet measured |
| Supplemental Japanese reference candidates | 10,233 unique set-and-number candidates in 229 sets | Disabled until the printing and finish are verified |
| Same-name, multi-record candidates | 462 set-and-number identities in 31 sets | Disabled; source records agree on name but do not establish the printing or finish |
| TCGdex ambiguous source candidates | 50 set-and-number identities in E2/E3 | Disabled because duplicated source variant declarations cannot distinguish printings |
| TCGdex English physical cards | 17,611 version identities in 73 sets | 16,491 have a numeric collector ID and official set denominator; matching accuracy against live listings remains unmeasured |
| TCGdex English ambiguous candidates | 135 set-and-number identities | Disabled because duplicate source variants cannot be distinguished |
| Second-source reference records | 24,039 | Internal comparison only; 10,522 set-and-number groups overlap the TCGdex seed |

The previous 3,621-row selected seed is wholly contained in the broader TCGdex extract. The supplemental layer includes **87 S6a cards** from the second source; they remain unverified for price matching. No catalog record is currently approved for public display, and no images, image URLs, attacks, effects or rules text are shipped in these extracts.

The local SQLite snapshot can be rebuilt from the pinned JSONL files. It has no live marketplace listings or prices and is excluded from Git and the source ZIP.

## Source snapshots

- [TCGdex cards-database](https://github.com/tcgdex/cards-database), commit `a211f11f3ba57d56c65c5ac33be35b77d3280757`. The repository describes its database as MIT licensed. We extracted identity text from its `data-asia` TypeScript files and recorded each source path and SHA-256.
- The same pinned TCGdex commit supplies the English physical-card source under `data/`. This batch covers Mega Evolution, Scarlet & Violet, Sword & Shield, and Sun & Moon. Pokémon TCG Pocket is digital and excluded. Older English physical series remain outside this batch.
- [type-null/PTCG-database](https://github.com/type-null/PTCG-database), commit `bc5a2698eb9af858feb0280d579fd5fd0f0273e2`. Its Japanese JSON appears to derive from the Pokémon official site. Its repository license does not settle rights to Pokémon content, so this source remains internal and cannot automatically contribute to offer matching or public display. We retained set, number, name, rarity, basic card attributes and source ID only.

## Audit results

- TCGdex: 174 `data-asia` set directories scanned, 18,442 card files, 13,397 parsed card files, 16,347 printing identities. Of 5,046 gap rows, 4,994 have no Japanese name in that source. Many are non-Japanese Asian editions; 808 missing files belong to sets whose headers do contain Japanese set names. Fifty files have repeated, indistinguishable variant declarations; their set, number and Japanese name are retained as **unverified** identities, without guessing which variant is which.
- Supplemental source: 24,039 records, 10,233 new single-record set-and-number candidates, and 525 new groups with multiple source records. Of the multi-record groups, 462 have one shared Japanese name and come from set codes with no name collision; they are internal *set-and-number* candidates, not resolved printing variants. The other 51 name-conflicting groups and 12 same-name groups in those conflicting sets (`MG`, `SA`) remain reference-only. Another 1,468 records lack a usable set/number identity, while 162 overlapping groups have names that disagree with TCGdex. Conflicts remain visible in the audit and are not silently merged.
- English physical source: 11,565 card files in 73 sets, 11,430 parsed files yielding 17,611 version identities. A further 135 files have duplicate indistinguishable variant declarations; each contributes one unverified internal discovery candidate. Of the parsed version identities, 16,491 have a numeric collector ID and nonzero official set denominator. The remaining 1,120 stay match-disabled. This does not establish actual marketplace match accuracy.
- `catalog_status` reports 44,838 identities, 32,838 structurally match-eligible, 12,000 match-disabled, 24,039 reference records and zero display-approved. Japanese and English set metadata are keyed by both language and code, so identical codes cannot cross-contaminate names.

## Files and reproduction

The broad TCGdex extract is [`catalog/ja-all-available.jsonl`](catalog/ja-all-available.jsonl), with [set metadata](catalog/ja-all-sets.jsonl), [coverage report](catalog/coverage-all-available.json) and [per-file gaps](catalog/ja-all-gaps.jsonl). The 50 additional [ambiguous candidates](catalog/tcgdex-ambiguous-candidates.jsonl) have their own [audit](catalog/tcgdex-ambiguous-audit.json). The second source has a [minimal reference extract](catalog/ptcg-jp-reference.jsonl), [single-record candidates](catalog/ptcg-jp-candidates.jsonl), [multi-record candidates](catalog/ptcg-jp-multi-record-candidates.jsonl), [multi-record audit](catalog/ptcg-jp-multi-record-audit.json), [original audit](catalog/ptcg-jp-audit.json) and [gaps](catalog/ptcg-jp-gaps.jsonl). Both source licenses are copied under `catalog/` for attribution; underlying card art and marks remain with their rights holders.

The English batch has [card identities](catalog/en-physical-cards.jsonl), [language-scoped sets](catalog/en-physical-sets.jsonl), [source gaps](catalog/en-physical-gaps.jsonl), [coverage audit](catalog/en-physical-audit.json), [ambiguous candidates](catalog/en-physical-ambiguous.jsonl) and [ambiguity audit](catalog/en-physical-ambiguous-audit.json). `scripts.build_tcgdex_international` reproduces it from the four named series in the pinned checkout. English data adds text identities only; no images, image URLs, attacks, effects or prices are shipped.

With the two pinned public repositories checked out locally, `scripts.build_tcgdex_full` and `scripts.build_ptcg_reference` reproduce the source extracts. `scripts.build_ptcg_multi_record` then derives the additional candidates from the reference and gap files. The source extract scripts fail on an unexpected commit SHA, and all three create new output files instead of silently overwriting an earlier audit.

Next catalog work should reconcile high-value S6a and the 162 name conflicts against independent evidence, establish finish identities for selected supplemental cards, and seek an explicit public metadata/image license before exposing the catalog in a product. Listing volume from a permitted marketplace feed will decide which remaining sets deserve deeper curation.

# Japanese and English card catalog coverage — 23 September 2026

The catalog can be built without Buy&Ship. The 23 September pinned baseline contains **55,165 internal card identities across 543 card-bearing language-and-set combinations**: 27,092 Japanese identities in 342 sets and 28,073 English identities in 201 sets, plus 24,039 Japanese and 9,208 English source reference records. The 26 September increment below adds two internal candidates. These are card metadata, not live offers or prices.

| Layer | Records | Use in offer matching |
| --- | ---: | --- |
| TCGdex pinned metadata | 16,347 printings in 126 sets | Structurally eligible for exact set, number and finish matching; accuracy against live listings is not yet measured |
| Supplemental Japanese reference candidates | 10,233 unique set-and-number candidates in 229 sets | Disabled until the printing and finish are verified |
| Same-name, multi-record candidates | 462 set-and-number identities in 31 sets | Disabled; source records agree on name but do not establish the printing or finish |
| TCGdex ambiguous source candidates | 50 set-and-number identities in E2/E3 | Disabled because duplicated source variant declarations cannot distinguish printings |
| Pinned TCGdex English physical cards | 18,730 version identities in 79 sets | 17,610 have a numeric collector ID and official set denominator; matching accuracy against live listings remains unmeasured |
| TCGdex English ambiguous candidates | 135 set-and-number identities | Disabled because duplicate source variants cannot be distinguished |
| TCGdex API English set-list candidates | 9,208 set-and-number families in 122 further card-bearing sets | Disabled: list responses do not resolve finish or printing identity |
| Second-source reference records | 24,039 | Internal comparison only; 10,522 set-and-number groups overlap the TCGdex seed |

The previous 3,621-row selected seed is wholly contained in the broader TCGdex extract. The supplemental layer includes **87 S6a cards** from the second source; they remain unverified for price matching. No catalog record is currently approved for public display, and no images, image URLs, attacks, effects or rules text are shipped in these extracts.

The local SQLite snapshot can be rebuilt from the pinned JSONL files. It has no live marketplace listings or prices and is excluded from Git and the source ZIP.

### 26 September 2026 demand-backed increment

A read-only audit of 26 old Mercari HTTP cassette files found 467 distinct
historical items; 467 carried a `photos[]` array and 418 carried at least two
photo references. These counts do not prove that either image shows a card back,
that the URLs still work, or that Buy&Ship permits sending them to AI. The
audit copied no listing titles, IDs, photo URLs, sellers or prices into this
repository. Of 127 non-bundle titles with one interpretable set/number, 121
already had a catalog identity. Five historical items pointed to two missing
S6a secret-art numbers, `094/069` and `095/069`; these have now been added as
**match-disabled, display-disabled** internal candidates using two independent
set/number/name references each. The local index now has **55,167 identities**
(27,094 Japanese, 28,073 English) and still **33,957 match-eligible**. No new
priceable unit or offer was asserted. One `SA 006/023` title remains
reference-only because the existing source has three different cards at that
set/number.

The deterministic resolver accepts 105 of the 467 historical titles and
abstains on 362. Among items with at least two photo references, 99 are
title-accepted and 319 abstain; 83 of the latter are explicit bundles. These
are sampling strata for a future authorized photo evaluation, not measured
vision accuracy. The resolver now requires the normalized catalog card name
as well as set/number and finish evidence. One old title omitted the `X` in
`メガリザードンXex` and is now held for photo review instead of being automatically
matched.

An internal review-only candidate retriever now finds at least one catalog
candidate for 94 of the 319 two-photo historical items on which the strict
title resolver abstains. This expands the future photo audit queue without
changing `match_eligible`, the ask index, or public card display. A singleton
retrieval result is not a verified identity.

The before/after audit files are
[`catalog/legacy-mercari-fixture-coverage-audit.json`](catalog/legacy-mercari-fixture-coverage-audit.json)
and [`catalog/legacy-mercari-fixture-coverage-after-s6a.json`](catalog/legacy-mercari-fixture-coverage-after-s6a.json).
The two internal candidates are in
[`catalog/s6a-secret-art-gap-candidates.jsonl`](catalog/s6a-secret-art-gap-candidates.jsonl).
The public TCGdex Japanese set API listed 40 set codes absent from the Japanese
runtime index, but every detail response returned zero card summaries on this
date; they therefore supplied no safe card-level expansion.

## Character and artist discovery facets

The pinned TCGdex source also supplies **59,710 provenance-checked, text-only facet rows** for the 35,077 Japanese and English identities extracted directly from its card files: 28,361 cards have a usable Pokédex character ID and 31,071 have an illustrator. Facets are stored separately in [`catalog/card-facets.jsonl.gz`](catalog/card-facets.jsonl.gz), with a [build audit](catalog/card-facets-audit.json). Four legacy source files use a decimal `dexId` such as `384.1`; those IDs are omitted and listed in the audit rather than coerced to a different character. API-only and supplemental candidates have no TCGdex facet assertion from this batch.

Each facet retains the pinned source path, content SHA-256 and rights reference. A shared character ID supports exploratory retrieval across languages; it does **not** assert identical artwork, printing, condition or price. Artist matches have the same limitation. All facet queries remain internal, and no display permission is inferred from the source license. `scripts.build_discovery_facets` reproduces the compressed snapshot byte-for-byte from the pinned checkout and the two card identity extracts.

## Source snapshots

- [TCGdex cards-database](https://github.com/tcgdex/cards-database), commit `a211f11f3ba57d56c65c5ac33be35b77d3280757`. The repository describes its database as MIT licensed. We extracted identity text from its `data-asia` TypeScript files and recorded each source path and SHA-256.
- The same pinned TCGdex commit supplies the English physical-card source under `data/`. This batch covers Base, Mega Evolution, Scarlet & Violet, Sword & Shield, and Sun & Moon.
- The [TCGdex set API](https://tcgdex.dev/rest/set) supplies a frozen September 2026 snapshot for 126 additional English physical sets. The snapshot retains set/card identity fields, fetch time and response SHA-256. Four sets had empty card lists; the other 122 contribute discovery candidates only. Pokémon TCG Pocket's 15 digital sets were excluded using the API's series list. API list responses do not establish finish variants, so these rows never auto-resolve an offer.
- [type-null/PTCG-database](https://github.com/type-null/PTCG-database), commit `bc5a2698eb9af858feb0280d579fd5fd0f0273e2`. Its Japanese JSON appears to derive from the Pokémon official site. Its repository license does not settle rights to Pokémon content, so this source remains internal and cannot automatically contribute to offer matching or public display. We retained set, number, name, rarity, basic card attributes and source ID only.

## Audit results

- TCGdex: 174 `data-asia` set directories scanned, 18,442 card files, 13,397 parsed card files, 16,347 printing identities. Of 5,046 gap rows, 4,994 have no Japanese name in that source. Many are non-Japanese Asian editions; 808 missing files belong to sets whose headers do contain Japanese set names. Fifty files have repeated, indistinguishable variant declarations; their set, number and Japanese name are retained as **unverified** identities, without guessing which variant is which.
- Supplemental source: 24,039 records, 10,233 new single-record set-and-number candidates, and 525 new groups with multiple source records. Of the multi-record groups, 462 have one shared Japanese name and come from set codes with no name collision; they are internal *set-and-number* candidates, not resolved printing variants. The other 51 name-conflicting groups and 12 same-name groups in those conflicting sets (`MG`, `SA`) remain reference-only. Another 1,468 records lack a usable set/number identity, while 162 overlapping groups have names that disagree with TCGdex. Conflicts remain visible in the audit and are not silently merged.
- Pinned English physical source: 12,059 card files in 79 sets, 11,924 parsed files yielding 18,730 version identities. A further 135 files have duplicate indistinguishable variant declarations; each contributes one unverified internal discovery candidate. Of the parsed version identities, 17,610 have a numeric collector ID and nonzero official set denominator. The remaining 1,120 stay match-disabled. This does not establish actual marketplace match accuracy.
- API supplement: 126 set responses, 9,208 card summaries and no identity-field gaps. Four set responses have empty card lists (`jumbo`, `rc`, `sp`, `wp`). All 9,208 card families are unverified and match-disabled; they are not 9,208 confirmed printing variants.
- At the 23 September baseline, `catalog_status` reports 55,165 identities, 33,957 structurally match-eligible, 21,208 match-disabled, 24,039 Japanese reference records and zero display-approved. After the two S6a imports it reports 55,167 identities and 21,210 match-disabled. The API's 9,208 English reference rows are frozen in JSONL but not loaded into the runtime `card_reference` table. Japanese and English set metadata are keyed by both language and code, so identical codes cannot cross-contaminate names.

## Files and reproduction

The broad TCGdex extract is [`catalog/ja-all-available.jsonl`](catalog/ja-all-available.jsonl), with [set metadata](catalog/ja-all-sets.jsonl), [coverage report](catalog/coverage-all-available.json) and [per-file gaps](catalog/ja-all-gaps.jsonl). The 50 additional [ambiguous candidates](catalog/tcgdex-ambiguous-candidates.jsonl) have their own [audit](catalog/tcgdex-ambiguous-audit.json). The second source has a [minimal reference extract](catalog/ptcg-jp-reference.jsonl), [single-record candidates](catalog/ptcg-jp-candidates.jsonl), [multi-record candidates](catalog/ptcg-jp-multi-record-candidates.jsonl), [multi-record audit](catalog/ptcg-jp-multi-record-audit.json), [original audit](catalog/ptcg-jp-audit.json) and [gaps](catalog/ptcg-jp-gaps.jsonl). Both source licenses are copied under `catalog/` for attribution; underlying card art and marks remain with their rights holders.

The pinned English batch has [card identities](catalog/en-physical-cards.jsonl), [language-scoped sets](catalog/en-physical-sets.jsonl), [source gaps](catalog/en-physical-gaps.jsonl), [coverage audit](catalog/en-physical-audit.json), [ambiguous candidates](catalog/en-physical-ambiguous.jsonl) and [ambiguity audit](catalog/en-physical-ambiguous-audit.json). `scripts.build_tcgdex_international` reproduces it from five named series in the pinned checkout.

The API supplement has [frozen reference rows](catalog/en-api-reference.jsonl), [set metadata](catalog/en-api-sets.jsonl), [fetch audit](catalog/en-api-audit.json), [unverified candidates](catalog/en-api-candidates.jsonl) and [candidate audit](catalog/en-api-candidates-audit.json). `scripts.snapshot_tcgdex_api_sets` fetches and caches one set response per missing physical set; `scripts.build_tcgdex_api_candidates` reproduces the candidate identities from the frozen reference and pinned source list. These extracts contain no images, image URLs, attacks, effects, rules text or prices.

With the two pinned public repositories checked out locally, `scripts.build_tcgdex_full` and `scripts.build_ptcg_reference` reproduce the source extracts. `scripts.build_ptcg_multi_record` then derives the additional candidates from the reference and gap files. The source extract scripts fail on an unexpected commit SHA, and all three create new output files instead of silently overwriting an earlier audit.

Next catalog work should reconcile high-value S6a and the 162 name conflicts against independent evidence, establish finish identities for selected supplemental cards, and seek an explicit public metadata/image license before exposing the catalog in a product. Listing volume from a permitted marketplace feed will decide which remaining sets deserve deeper curation.

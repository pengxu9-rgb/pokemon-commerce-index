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

### 26 September source-conflict check

A fresh comparison against the broad TCGdex Japanese seed found 76 same-set,
same-number groups with different source names. Unicode and whitespace
normalization accounts for 53. The remaining 23 were checked against the
exact set and collector number on Pokémon's official card pages, retaining
the page URL and response SHA-256 in the [official-page audit](catalog/jp-source-conflict-official-audit.json).
Nineteen official base names agree with TCGdex; the other source had appended
qualifiers such as a professor's name or `prismstar`. Four official pages
contradict TCGdex's name: M6 `098/076` and `099/076` were interchanged, while
SM6 `094/094` and SV-P `136/SV-P` omitted part of the printed name.
Within the 19 base-name agreements, **15 official pages carry the Prism Star
rarity icon**, while the pinned seed labels their sole variant `holo` and its
rarity `Rare Holo`. The audit records the official icon separately from the
card title; a base-name agreement does not resolve this printing mismatch.

The 19 [identity exceptions](catalog/jp-card-identity-exceptions.jsonl) correct
four internal names and label 15 official Prism Star rarities without rewriting
the pinned TCGdex extract. All 19 are held from automatic offer matching and
public display until the variant taxonomy and finish are reconciled. The
exception table makes that hold survive a seed re-import. Match-eligible cards
decrease from 33,957 to **33,938**; the total remains **55,167**. A Gemini 3.8 Flash Google Search
grounding pass identified M6 `098/076` as a likely source error, but did not
return its exact official URL. Direct official-page verification, rather than
the model answer, determined the correction. That single grounded request
generated 56 searches, so bulk conflict verification uses the bounded exact
official-page path.

### Collector-denominator conflict gate — 27 September

The pinned TCGdex Japanese extract assigns `SM10B` cards `/056` and `SV11B`
cards `/174`. All 62 pinned official-source records for `SM10B` use `/054`;
all 254 for `SV11B` use `/086`. Two live official pages per set, including
the first and highest-numbered source records, confirmed the printed
denominator. The [rule evidence](catalog/ja-number-denominator-conflict-rules.jsonl)
and [audit](catalog/ja-number-denominator-conflict-audit.json) retain source
revisions, a manifest hash and official-page hashes.

The two source-scoped rules disable exact offer matching for **69 + 326 =
395** existing catalog identities. They do not rewrite card IDs or approve
the same-number official-source records as equivalent physical variants.
The local index now has **33,543 match-eligible cards** of 55,167. A seed
re-import cannot re-enable these 395 cards while the same pinned source
revision is used. `number-explanation` exposes the catalog and official
denominators. Apply the rules after `init` when rebuilding a database:

```bash
python3 -m pokemon_index --db catalog-index.sqlite3 import-card-number-conflicts \
  catalog/ja-number-denominator-conflict-rules.jsonl
```

The 15 cards now also carry `official_printing_type=prism_star`, sourced from
the verified official rarity icon. Internal catalog search, listing review
candidates and the exploration graph expose this field separately from the
old TCGdex `variant=holo`. Their existing card IDs remain stable because card
facets and classifications already reference them; the `holo` suffix is a
legacy source key, not a verified physical finish. `catalog-search
--printing-type prism_star` finds the 15 cards, but all 15 remain
`match_eligible=false` and cannot start offer tracking. The SQLite migration
also repairs a prior positional-insert error in upgraded exception tables;
new inserts name their columns explicitly.

The before/after audit files are
[`catalog/legacy-mercari-fixture-coverage-audit.json`](catalog/legacy-mercari-fixture-coverage-audit.json)
and [`catalog/legacy-mercari-fixture-coverage-after-s6a.json`](catalog/legacy-mercari-fixture-coverage-after-s6a.json).
The two internal candidates are in
[`catalog/s6a-secret-art-gap-candidates.jsonl`](catalog/s6a-secret-art-gap-candidates.jsonl).
The public TCGdex Japanese set API listed 40 set codes absent from the Japanese
runtime index, but every detail response returned zero card summaries on this
date; they therefore supplied no safe card-level expansion.

### Evidence expansion: all Japanese multi-record groups

The 50 E2/E3 TCGdex variant-ambiguous candidates have no matching set/number
record in the pinned Japanese second source, so that source cannot independently
settle them. In contrast, SV11B has 80 match-disabled `unverified_multi_record`
card candidates with two pinned source records at the same set/number. All 80
pairs share name, rarity and illustrator, but point to distinct official card
pages and image URLs. The [80-row internal review queue](catalog/ja-sv11b-variant-review-queue.jsonl)
and [build audit](catalog/ja-sv11b-variant-review-audit.json) bind both source
records by SHA-256 while omitting image URLs and bytes. Distinct records alone
do not prove separate physical printings. The follow-on [all-set review queue](catalog/ja-variant-review-all-queue.jsonl)
expands this lane to **462 groups in 31 sets**, including the same 80 SV11B
groups. Every source record is hash-bound and all groups remain candidate-only.
Its [structural audit](catalog/ja-variant-review-all-audit.json) found 348
groups whose source records differ only in record ID, official page URL and
image URL; another 113 also differ in source attribution, and one additionally
differs in card type. These differences do not establish physical finish.
The follow-up [image-hash audit](catalog/ja-variant-image-hash-audit.json)
fetched all 967 official source images for these 462 groups and found distinct
image bytes within every group. Hashes establish file differences only; they
do not classify artwork, foil, stamp, edition, or physical printing. The
source-bound [group evidence](catalog/ja-variant-image-hash-evidence.jsonl)
remains internal.
Batch image and official-page review must resolve the exact printing before
any catalog split or offer matching. No new card identities or match permissions
were added by either queue.

## 1 October 2026 — English historical source coverage

The English expansion build is [`catalog-build-manifest-coverage-v1.json`](catalog-build-manifest-coverage-v1.json): **70,005 internal records**, comprising 27,094 Japanese and 42,911 English records across the same 543 card-bearing language/set combinations. These are source-declared version identities and unresolved family placeholders, **not 70,005 verified distinct physical cards**. There are 24,144 Japanese and 21,293 English set/number groups; language, printing, finish and cross-region equivalence remain separate questions.

This batch parses the remaining 15 English physical series in the same pinned TCGdex revision: XY, Black & White, Diamond & Pearl, Platinum, HeartGold & SoulSilver, EX, E-Card, Neo, Gym, Legendary Collection, Call of Legends, POP, McDonald's Collection, Trainer kits and Miscellaneous. The [batch audit](catalog/english-history-v1/audit.json) distinguishes:

- **14,838 added source-version records** in 121 already indexed sets.
- **9,135 previously indexed set/number groups enriched**, plus **26 new groups**. Most of the increase adds metadata to previously list-only families; it does not expand unique-card breadth by 14,838.
- 26,592 new role/artist facet rows, including Pokédex IDs on 12,225 records and illustrator names on 14,326. Total facet coverage is now 40,586 records with character IDs and 45,397 with illustrator names.
- 14,793 added category/subtype declarations; 45 records remain unclassified. There are 153 extraction gaps, including 33 ambiguous variant files. These are retained in the source gap audit.
- Every added record is **match-disabled and display-disabled**. Existing eligibility remains 33,543; supported metadata targets remain 100; verified counterpart assertions and approved automatic offer joins remain zero. No prices, offers or marketplace photos were imported.

API family IDs are retained for provenance and existing references. They are not silently equated with newly parsed source variants. A physical printing, price comparison or owned-copy equivalence needs its own evidence. Character/artist retrieval can use the new facets immediately; a shared character or artist is not a cross-language printing edge.

The batch verifies **9,454 source Git blobs** (card files, headers and license) against the pinned tree before extraction. The recovered complete source archive has SHA-256 `858b99b8e2a0f1dc5f74ffcb102cb47ba59a46e8a71a8f9ad52ad58be76e1c39`. The previous download was truncated; it was not used for this import. The original sparse checkout fetch failed, and recovery used the complete archive with Git-object verification.

Expansion exposed a parser bug: an attack's nested `name` could be read before the card's top-level `name`. The parser now requires the top-level card property and abstains when it is missing. All 35,077 earlier directly parsed TCGdex records were rechecked against their card-name properties: zero disagreements. Baseline inputs remain unchanged. The [baseline parser audit](catalog/english-history-v1/baseline-name-parser-audit.json) and original failed extraction in the local work directory preserve the diagnosis.

The [14-question rehearsal](catalog/english-history-v1/discovery-rehearsal.json) checks character, artist, historical coordinates, current Japanese coordinates and blocked price/counterpart requests. Questions were constructed during development; this is a regression diagnostic, not independent accuracy. English Pikachu retrieval increases from 199 to 313 source-version records; Eevee increases from 81 to 130. These are catalog retrieval counts, not distinct physical-copy counts. All returned records retain false price-comparability and automatic-join flags. The full test suite passed 416 tests. Private Cloud Run revision `pokemon-commerce-index-00024-8qz` also passed [35 authenticated logical checks](cloud-deployment-20261001-coverage-v1.json), with unauthenticated requests rejected.

### Japanese gaps and the next expansion batch

A fresh [Japanese API gap audit](catalog/ja-api-gap-refresh-20261001.json) checked all 40 API-listed sets absent from the runtime catalog. All returned empty card lists, after retrying five plus-sign set IDs with proper URL encoding. This API check adds **zero Japanese cards**; an empty response does not establish that the set has no cards.

The [prepared 1,000-record review queue](catalog/japanese-evidence-next-v1/queue.jsonl) selected 1,000 unique set/number groups from a 3,305-group pool across nine modern Japanese releases. Selection used release priority and metadata needs, not measured demand or GMV. The official-page audit below completes this queue; its original preparation report remains unchanged.

## 1 October 2026 — 1,000 official Japanese metadata records

The first metadata [`catalog-build-manifest-metadata-v1.json`](catalog-build-manifest-metadata-v1.json) adds one SHA-256 checked input to the previous 38. It imports [1,000 append-only metadata evidence records](catalog/japanese-evidence-next-v1/metadata-evidence-v1.jsonl), each bound to its original catalog identity, pinned source reference, exact official page, response hash and retrieval timestamp. These enrich existing identities; the catalog remains **70,005 internal records**, with **33,543 structurally eligible records**. The existing 100-target supported cohort remains separately defined and disjoint from this metadata batch. No physical-printing allowlist or market permission expands.

| Measure | Result |
|---|---:|
| Exact official name/set/number agreement | 1,000 |
| Official rarity icon recognized | 749 |
| Official page has no rarity icon | 251 |
| Unknown rarity icons | 0 |
| Pages covering multiple numbered parts | 4 |
| Substantive artist conflicts withheld from discovery facets | 7 |
| Effective character / illustrator facet coverage | 40,662 / 45,493 |
| Live observations / verified card-pair relationships / approved offer joins | 0 / 0 / 0 |

Release distribution: M6A 131, M6 110, M-P 126, SV11W 94, SV11B 94, SV10 132, SV9A 92, SV9 132 and SV8A 89. The [final source audit](catalog/japanese-evidence-next-v1/official-audit-v2.summary.json) and [evidence summary](catalog/japanese-evidence-next-v1/metadata-evidence-v1.summary.json) retain the decisions. The initial audit found 996 agreements and four parser holds; [that first result](catalog/japanese-evidence-next-v1/official-audit-v1.summary.json) is preserved. Those four pages explicitly list multiple numbered parts: LEGEND upper/lower and three stadium left/right pairs. The final parser binds the exact requested number and retains the other part coordinates. A journey cannot select these as an established physical copy without part/copy evidence; page-level combined credits do not become per-part character or artist assertions.

Artist comparison found 26 differences: 18 additional coauthor declarations, one page-level LEGEND combined-credit case and seven substantive conflicts. Coauthors can support same-artist retrieval sharing any explicit credited name, with source provenance. The seven [conflict cases](catalog/japanese-evidence-next-v1/artist-conflict-queue.jsonl) suppress both conflicting seed and official values in the discovery projection. Raw declarations remain visible with a conflict status. No artist alias, physical identity or counterpart approval is inferred. A Vertex Gemini 3.8 Flash request with Google Search was attempted for these seven cases; it timed out without a response. [The protocol](catalog/japanese-evidence-next-v1/artist-conflict-gemini-protocol.json) and [unavailable result](catalog/japanese-evidence-next-v1/artist-conflict-gemini-unavailable.json) record that limitation. There are no model approvals from this attempt.

Known official rarity now appears in internal catalog/collector responses with the original seed value retained as `source_rarity`; absence of an icon stays explicitly undeclared. Immutable seed rows and the historically frozen v1/v2 question resolvers remain unchanged. Active metadata is invalidated when its catalog identity or bound reference drifts. Journey revisions also bind metadata events, runtime code and actual derived-view definitions, so a stale journey cannot silently reuse an earlier projection.

The [development rehearsal](catalog/japanese-evidence-next-v1/discovery-rehearsal-v2.json) passes 20 constructed questions with full pagination, four numbered-part journey blockers and seven graph checks, including coauthor retrieval and conflict exclusion. **430 Python tests and 11 Node tests pass.** Private Cloud Run revision `pokemon-commerce-index-00025-zs7` passed [49 authenticated logical checks](cloud-deployment-20261001-japanese-metadata-v1.json), including exact metadata/graph comparisons and the four numbered-part journey blockers. These are engineering checks, not blind marketplace precision or independent AI accuracy. Official HTML stays in a local cache and is excluded from Git/cloud; deployed text facts do not grant public image/display rights. Buy&Ship is still required for an authorized live listing feed and transaction handoff.

Reproduction (outputs must be new files; the official cache may be reused after receipt/hash checks):

```bash
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-coverage-v1.json --db /tmp/pokemon-coverage-expansion-v1.sqlite3
python3 -m scripts.audit_japanese_metadata_batch \
  --queue catalog/japanese-evidence-next-v1/queue.jsonl \
  --cache ../../work/japanese-evidence-next-v1-cache \
  --output /tmp/japanese-official-audit.jsonl
python3 -m scripts.build_japanese_metadata_evidence \
  --queue catalog/japanese-evidence-next-v1/queue.jsonl \
  --audit catalog/japanese-evidence-next-v1/official-audit-v2.jsonl \
  --baseline /tmp/pokemon-coverage-expansion-v1.sqlite3 \
  --output /tmp/japanese-metadata-evidence.jsonl
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-metadata-v1.json --db /tmp/japanese-metadata-catalog.sqlite3
```

Next evidence work should resolve the seven artist conflicts from independent exact-card sources and image credits, extend the remaining Japanese coordinate cohort, and keep physical finish/edition and cross-language price equivalence as separate evidence tasks. The 251 pages without a rarity declaration must not be filled by filename or rarity-distribution guesses.

## 2 October 2026 — another 1,497 official Japanese coordinates

The current [`catalog-build-manifest-metadata-v2.json`](catalog-build-manifest-metadata-v2.json) has **40 ordered SHA-256 checked inputs**. It adds [1,497 official metadata records](catalog/japanese-evidence-expansion-v2/metadata-evidence-v1.jsonl), disjoint from the previous 1,000 and the original 100 supported targets. All 1,497 official pages agree on name, release code and collector number. The catalog still contains **70,005 source-version/family records**, **33,543 structurally eligible records** and zero public display approvals; this batch strengthens existing metadata rather than adding physical-printing identities.

| Measure | This batch | Cumulative official metadata |
|---|---:|---:|
| Exact source-coordinate records | 1,497 | 2,497 |
| Recognized official rarity | 1,151 | 1,900 |
| No official rarity icon | 346 | 597 |
| Unrecognized rarity icon | 0 | 0 |
| Numbered-part page records | 0 | 4 |
| Artist conflicts excluded from discovery facets | 3 | 10 |

The [queue](catalog/japanese-evidence-expansion-v2/queue.jsonl), [initial selection audit](catalog/japanese-evidence-expansion-v2/queue.summary.json), [exact reproduction check](catalog/japanese-evidence-expansion-v2/queue-reproduction-check.json), [official audit](catalog/japanese-evidence-expansion-v2/official-audit-v1.summary.json) and [import evidence summary](catalog/japanese-evidence-expansion-v2/metadata-evidence-v1.summary.json) are frozen. Release distribution: SV8A 3, SV-P 278, SV8 138, SV7A 94, SV7 135, SV6A 94, SV6 133, SV5A 96, SV5M 100, SV5K 100, SV4K 95, SV4M 95 and SV4A 136. The deterministic selector excludes 238 groups with multiple source versions, 89 already checked groups, 100 original supported targets, 40 missing/multiple reference groups and two reference-name conflicts. The 280 pending source/identity groups are retained with original variants, names and references in [the next evidence queue](catalog/japanese-evidence-expansion-v2/next-evidence-holds.jsonl). Those omissions need separate evidence; they are not silently resolved. Selection is engineering coverage, not observed demand or GMV.

Most of this cohort already had seed facets. Effective character/artist discovery coverage rises from 40,662 / 45,493 to **40,666 / 45,500** after conflict suppression. The benefit is exact official provenance and rarity evidence across another 1,497 coordinates, not 1,497 new graph relationships. Original source rows, original 1,000 metadata events, supported-target membership and physical-copy gates remain unchanged.

Three new artist conflicts are held: SV-P 111/SV-P and SV8 012/106 have seed `0313` versus official display `313`; SV-P 198/SV-P has Susumu Maeya versus Kariya. A search-enabled Gemini retry for the original seven conflicts returned six advisory responses and one timeout; [its assessment](catalog/japanese-evidence-expansion-v2/previous-artist-retry-assessment.json) records that none returned grounding chunks/supports. The [new-conflict assessment](catalog/japanese-evidence-expansion-v2/new-artist-triage-assessment.json) records one ungrounded advisory response and two timeouts. Suggested URLs and confident explanations are research leads, not independent scan or search evidence. All ten conflicting artist facets remain excluded. Separate [official search leads](catalog/japanese-evidence-expansion-v2/independent-artist-search-leads.json) corroborate two page declarations but do not import a seed correction, artist alias or cross-region assertion.

The [constructed development rehearsal](catalog/japanese-evidence-expansion-v2/discovery-rehearsal-v1.json) covers one exact coordinate in each of the 13 releases, a character/artist scope, blocked counterpart/price requests, four preserved numbered-part journey blockers and seven graph checks. **433 Python and 11 Node tests pass**. Private Cloud Run revision `pokemon-commerce-index-00026-9lt` passed [48 authenticated logical requests](cloud-deployment-20261002-japanese-metadata-v2.json), with unauthenticated access rejected. These checks verify engineering behavior, not blind real-listing precision or independent recommendation accuracy. No marketplace listing, price, paid transaction or fulfillment outcome was added.

Rebuild and prepare the same untouched-coordinate queue using new output files:

```bash
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-metadata-v1.json --db /tmp/japanese-metadata-baseline.sqlite3
python3 -m scripts.prepare_japanese_metadata_queue \
  --baseline /tmp/japanese-metadata-baseline.sqlite3 \
  --manifest catalog-build-manifest-metadata-v1.json \
  --sets SV8A SV-P SV8 SV7A SV7 SV6A SV6 SV5A SV5M SV5K SV4K SV4M SV4A \
  --output /tmp/japanese-next-queue.jsonl
python3 -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-metadata-v2.json --db /tmp/japanese-metadata-v2.sqlite3
```

Next prioritize source-name conflicts and multiple-version groups with exact official pages and printed-credit/variant evidence. Unknown rarity declarations stay unknown; a printing split or offer permission requires its own positive evidence. Authorized live listing discovery, matching/freshness measurement and Buy&Ship transaction handoff remain the external gates.

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

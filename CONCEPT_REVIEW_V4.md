# Ranked bilingual concept review, v4

This batch addresses the high-ambiguity Trainer-name backlog left after v3.
The [frozen packet](catalog/concept-review-v4-queue.jsonl) contains 125
Japanese/English name proposals across 25 previously unreviewed Japanese
names. The [selection audit](catalog/concept-review-v4-audit.json),
[exclusions](catalog/concept-review-v4-exclusions.jsonl), and
[human template](catalog/concept-review-v4-template.csv) are retained.
Previous concept names and the pilot and blind anchors were excluded.

The ranking script requires matching pinned illustrator and compatible
Trainer subtype. It then ranks candidate names with numerals extracted from
both card effects, the two set release dates when present, and matching
series era. It verifies card-source SHA-256 hashes before reading effects and
records set-source hashes and ranking inputs in each proposal snapshot. The
rank is a way to prioritize review, **not** evidence that names are
translations. All 125 snapshots, 138 distinct card files, and 48 distinct
set files were verified against pinned TCGdex commit
`a211f11f3ba57d56c65c5ac33be35b77d3280757`.

Of 756 new Japanese Trainer names with more than four same-illustrator
English candidate names, 37 passed the fixed score and fifth-place cutoff
rules; the first 25 by deterministic seed entered this packet. The audit
records 588 below the top-score threshold and 131 without a sufficient
fifth-to-sixth gap. A diagnostic replay on 48 already reviewed Trainer
aliases placed all 48 known English names in the first five. This replay is
selected and in-sample; it is **not** a blind recall or production precision
estimate. The current date parser uses scalar `releaseDate` fields from
pinned set files; set files with localized object dates may lack this ranking
signal. Missing dates do not bar a proposal.

[Astra](ASTRA_CONCEPT_REVIEW_V4.md) and [Sol](SOL_CONCEPT_REVIEW_V4.md)
independently inspected both pinned source cards for every proposal. The
[comparison](catalog/concept-review-v4-comparison.csv) yielded:

| Outcome | Rows |
| --- | ---: |
| Both approve | 19 |
| Both reject | 104 |
| Both uncertain | 1 |
| Approve versus uncertain | 1 |

The two deferred rows were **not imported**:

- `0ec2b6105a38cd25fb34`, のろいのおふだ → Spell Tag: the extracted Japanese
  effect omits the Psychic-type symbol present in English. Both models held
  for card-image or card-specific corroboration.
- `74708c2ced11cc576a2b`, アカギ → Cyrus ◇: Astra cited an official errata
  resolving an Active-versus-in-play rule difference; Sol remained uncertain
  about that wording and the Prism Star marker. The pair needs adjudication.

The [consensus bundle](catalog/concept-review-v4-ai-consensus.bundle.json)
retains 123 agreed AI decisions and source snapshots. Nineteen new name
aliases and [19 `proposed` graph edges](catalog/concept-review-v4-proposed-edges.jsonl)
were imported into the local directory. The approved source-card
[anchors](catalog/concept-review-v4-anchors.jsonl) generated
[37 further candidate pairs](catalog/concept-review-v4-relationship-queue.jsonl),
with [audit](catalog/concept-review-v4-relationship-audit.json) and an
untouched [printing review template](catalog/concept-review-v4-relationship-review-template.csv).
One candidate pair involves a card barred from automatic offer matching.

Across v2–v4, the local uncommitted `catalog-index.sqlite3` now contains
276 AI review events, 73 approved internal name aliases, 73 proposed
source-card edges, and **zero verified printing edges**. All three human
concept templates remain pending. Neither the proposed edges nor the 37
queue rows establish identical artwork, finish, price comparability, or
merchant availability.

The v4 packet and consensus bundle rebuilt byte-identically from their
recorded inputs. Rebuild these imports after loading the pinned catalog:

```bash
python3 -m pokemon_index --db catalog-index.sqlite3 import-concept-review-bundle \
  catalog/concept-review-v4-ai-consensus.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 import-relationships \
  catalog/concept-review-v4-proposed-edges.jsonl
```

The next expansion should improve candidate recall among names that fail
the current score or cutoff gates, particularly when source set dates or
effect numbers are absent. Missing official or licensed card evidence should
remain a visible gap rather than a forced alias.

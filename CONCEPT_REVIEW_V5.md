# Ranked bilingual concept review, v5

This batch extends the internal Japanese–English Trainer-name review. The
[frozen packet](catalog/concept-review-v5-queue.jsonl) has 125 candidate pairs
for 25 new Japanese names. The [selection audit](catalog/concept-review-v5-audit.json),
[exclusions](catalog/concept-review-v5-exclusions.jsonl), and untouched
[human concept template](catalog/concept-review-v5-template.csv) are retained.
Prior reviewed names and pilot/blind anchors were excluded.

The ranker checks the pinned illustrator and compatible Trainer subtype, then
uses effect numerals, set release dates, and era to prioritize candidates.
This batch reads both scalar and localized-object set dates. Ranking is a
review queue, not translation evidence. The audit records 747 eligible-source
Japanese names with artist, 731 high-ambiguity names, 90 names passing the
fixed score and cutoff gates, and the first 25 selected by the frozen seed.
All 125 snapshots, 156 distinct card files, and 72 distinct set files were
checked against pinned TCGdex commit
`a211f11f3ba57d56c65c5ac33be35b77d3280757`.

[Astra](ASTRA_CONCEPT_REVIEW_V5.md) and [Sol](SOL_CONCEPT_REVIEW_V5.md)
independently read the pinned card sources. Their row-by-row
[comparison](catalog/concept-review-v5-comparison.csv) is:

| Outcome | Rows |
| --- | ---: |
| Both approve for name-concept retrieval | 24 |
| Both reject | 100 |
| Both uncertain | 1 |

The deferred pair is `2b4d40b32101491f2d33`, 大地の封印石 → Earthen Seal Stone.
The pinned Japanese source contains only generic Tool text, so the distinctive
effect cannot be compared. It was not imported. Boss's Orders/Ghetsis is an
approved **name concept only**; its generic English title does not verify a
depicted-character or physical-printing match. Other source limitations are
recorded in the two independent review reports and per-row CSV rationales.

The [consensus bundle](catalog/concept-review-v5-ai-consensus.bundle.json)
retains 124 agreed decisions, their source snapshots, and both rationales.
It imports 24 internal bilingual aliases and
[24 `proposed` candidate edges](catalog/concept-review-v5-proposed-edges.jsonl).
The approved [source-card anchors](catalog/concept-review-v5-anchors.jsonl)
produce [67 further relationship candidates](catalog/concept-review-v5-relationship-queue.jsonl)
with [audit](catalog/concept-review-v5-relationship-audit.json) and an
untouched [printing review template](catalog/concept-review-v5-relationship-review-template.csv).
All 67 printing reviews remain pending. The graph has **zero verified
physical-printing edges** and no basis to use these edges for price comparison.

Across v2–v5, the local uncommitted `catalog-index.sqlite3` contains 400 AI
concept review events, 97 approved internal name aliases, and 97 proposed
source-card edges after this batch is imported. These are AI judgements, not
human certifications or production precision measurements. The 25-name batch
was selected by a ranking heuristic; it is not a blind accuracy sample.

The catalog parser also now recognizes scalar Japanese set dates in the same
pinned source. This fills 58 previously blank set dates; the rebuilt card
identity file is byte-identical to the prior one. The total gap count
remains 5,046, including 4,994 files without a Japanese card name. Both the
packet and consensus bundle were reproduced
byte-identically from recorded inputs.

Rebuild this state after loading the pinned catalog and earlier concept batches:

```bash
python3 -m pokemon_index --db catalog-index.sqlite3 import-sets \
  catalog/ja-all-sets.jsonl
python3 -m pokemon_index --db catalog-index.sqlite3 import-concept-review-bundle \
  catalog/concept-review-v5-ai-consensus.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 import-relationships \
  catalog/concept-review-v5-proposed-edges.jsonl
```

The imports are idempotent. Approval or correction by a real human requires
the separate review workflow and evidence; the pending templates must not be
treated as completed reviews.

# Bilingual concept review, v3

This batch expands the dual-AI name-concept review beyond the 22 Japanese
names in v2. The frozen [proposal queue](catalog/concept-review-v3-queue.jsonl)
contains 115 pairs across 39 new Japanese Trainer names, with a separate
[human template](catalog/concept-review-v3-template.csv). The names in v2 and
the existing pilot and blind coverage anchors were excluded using the
[recorded exclusion list](catalog/concept-review-v3-exclusions.jsonl). The
[selection audit](catalog/concept-review-v3-audit.json) records the exact
`concept-review-v3` seed and candidate limits.

The shortlisting method requires pinned Japanese and English TCGdex source
records at commit `a211f11f3ba57d56c65c5ac33be35b77d3280757`, compatible
Trainer subtypes when known, and a shared illustrator. It limits each Japanese
name to four distinct English candidates. All 115 source snapshots and 93
distinct source-file hashes were verified. Among 811 Japanese Trainer names
with a pinned illustrator outside the exclusion set, 39 entered this queue;
16 lacked a source-backed candidate and 756 had more than four candidate
names. This intentionally bounded batch does not measure catalog recall or
production precision. Energy hints yielded no additional pinned candidates.

[Astra](ASTRA_CONCEPT_REVIEW_V3.md) and [Sol](SOL_CONCEPT_REVIEW_V3.md) reviewed
the 115 pairs independently against both pinned card records. Their
[row-by-row comparison](catalog/concept-review-v3-comparison.csv) is:

| Outcome | Rows |
| --- | ---: |
| Both approve | 33 |
| Both reject | 81 |
| Disagreement, deferred | 1 |

The disagreement is `625083540e9b1435d8ca`, ポケモンセンター → Pokémon Center.
The pinned Japanese legacy record lacks effect text and subtype. Astra marked
it uncertain; Sol approved the literal name concept. It remains **unimported**
pending stronger card-specific evidence. The [human template](catalog/concept-review-v3-template.csv)
remains entirely pending; neither model is represented as a human reviewer.

The [consensus bundle](catalog/concept-review-v3-ai-consensus.bundle.json)
retains 114 agreed decisions, both AI rationales, every source snapshot, and
the explicit AI review basis. It imported 33 new internal name aliases. The
[33 source-card graph edges](catalog/concept-review-v3-proposed-edges.jsonl)
are `collecting_alternative` / `proposed` only. They do not assert exact
printing, identical artwork or finish, offer eligibility, or price
comparability. The 33 approved source [anchors](catalog/concept-review-v3-anchors.jsonl)
produce [68 further relationship candidates](catalog/concept-review-v3-relationship-queue.jsonl),
with [audit](catalog/concept-review-v3-relationship-audit.json) and an
untouched [printing review template](catalog/concept-review-v3-relationship-review-template.csv).
All 33 anchors found candidates; two candidate pairs include a card barred
from automatic offer matching. None of the 68 is a verified edge.

The local `catalog-index.sqlite3` snapshot now has 153 AI review events,
54 approved name aliases, 54 proposed source-card edges, and zero verified
printing edges across v2 and v3. The snapshot is not committed. The frozen
bundle and edges can be replayed after rebuilding the catalog:

```bash
python3 -m pokemon_index --db catalog-index.sqlite3 import-concept-review-bundle \
  catalog/concept-review-v2-ai-consensus.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 import-relationships \
  catalog/concept-review-v2-proposed-edges.jsonl
python3 -m pokemon_index --db catalog-index.sqlite3 import-concept-review-bundle \
  catalog/concept-review-v3-ai-consensus.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 import-relationships \
  catalog/concept-review-v3-proposed-edges.jsonl
```

Replaying v3 on the local snapshot inserted zero new rows. The next expansion
needs a better candidate generator for the 756 high-ambiguity names; adding
more same-illustrator guesses without another signal would mostly increase
review cost. The deferred Pokémon Center pair needs independent official or
licensed card-specific evidence before any alias import. Real human review
and a separately adjudicated blind gold set remain needed to measure quality.

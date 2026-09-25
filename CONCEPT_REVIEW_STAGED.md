# Staged bilingual concept review

## What the 24/125 number measures

The v5 packet deliberately offered five English candidates for each of 25
Japanese Trainer names. Under the working one-name-per-concept assumption,
only about one row per group can pass. The 24/125 = 19.2% row approval figure
is therefore close to this packet's 25/125 = 20% ceiling. It is **not** a
catalog matching accuracy measure. In v5, at least one candidate received
agreement to approve for 24/25 selected names, while the first-ranked
candidate was approved for 18/25. In v4 these figures were 19/25 and 12/25.
All are retrospective results from AI-reviewed, selected packets; none is a
blind precision or recall estimate.

The ranking score combines artist, subtype, effect numerals, release dates
and era. It does not understand bilingual card names or full rule meaning.
High scores can belong to unrelated cards with the same illustrator and
similar dates. Raising its score threshold would discard real candidates
without evidence that it improves review yield.

## Review one candidate at a time

Keep the five-candidate ranked pool frozen for audit, but expose only rank 1
for each name. Advance to rank 2 only after every independent reviewer rejects
rank 1. Agreement to approve stops the name. Any uncertainty or reviewer
disagreement pauses it for adjudication. Exhausting the pool creates a visible
gap. The stage selector checks every review file's proposal IDs, source
snapshot hashes and nonempty rationales. It schedules review only: it cannot
import a name alias, create a graph edge, or verify a physical printing.

Retrospective replay of the exact v4 and v5 decisions:

| Packet | Reviewed rows originally | Sequential rows needed | AI-agreed approvals retained | Rows avoided |
| --- | ---: | ---: | ---: | ---: |
| v4 | 125 | 56 | 19/19 | 69 (55.2%) |
| v5 | 125 | 42 | 24/24 | 83 (66.4%) |

This changes review efficiency, not the underlying model's bilingual
judgment. It avoids presenting four likely negative options for every name
at once. The original reviewers saw all five candidates, so a fresh
sequential review could yield different decisions; the savings are a replay
estimate, not a measured prospective result. See the immutable
[v4 replay audit](catalog/concept-review-v4-staged-replay-audit.json)
and [v5 replay audit](catalog/concept-review-v5-staged-replay-audit.json).

## v6 prospective staged run

The [v6 full ranked pool](catalog/concept-review-v6-full-queue.jsonl) contains
125 source-bound pairs across 25 new Japanese names. It is retained to allow
later stages; it is **not** a 125-row task for reviewers. The
[v6 stage 1 queue](catalog/concept-review-v6-stage1-queue.jsonl) and
[review template](catalog/concept-review-v6-stage1-template.csv) contain
only 25 rank-1 pairs. The [selection audit](catalog/concept-review-v6-selection-audit.json),
[exclusions](catalog/concept-review-v6-exclusions.jsonl), and
[stage audit](catalog/concept-review-v6-stage1-audit.json) record the exact
selection. Five stages are now complete: 55 reviewed rows yielded 20 internal
name concepts and five exhausted names. See [v6 results](CONCEPT_REVIEW_V6.md).

Use the selector with **cumulative** review CSVs to prepare the next stage. Each review CSV
must have `proposal_id`, `source_snapshot_sha256`, `suggested_decision`
(`approve`, `reject`, or `uncertain`) and a nonempty `rationale`. The next-stage
output paths must be new:

```bash
python3 -m scripts.concept_review_staged \
  --queue catalog/concept-review-v6-full-queue.jsonl \
  --astra V6_ASTRA_CUMULATIVE.csv --sol V6_SOL_CUMULATIVE.csv \
  --gemini V6_GEMINI_CUMULATIVE.csv --gemini-audit V6_GEMINI_AUDIT.json \
  --output V6_NEXT_QUEUE.jsonl --sheet V6_NEXT_TEMPLATE.csv \
  --audit V6_NEXT_AUDIT.json
```

The `combine_ai_concept_review_stages` helper produces cumulative working
inputs from immutable per-stage reviewer files. The
`compile_ai_concept_consensus` command compiles each reviewed stage with
`--batch-id v6 --allow-deferred --gemini ... --gemini-audit ...`; only matching
three-way decisions become internal aliases and `proposed` collecting
alternatives.
Physical printing, shared artwork, finish, condition and price comparability
still require separate evidence and review.

The next quality gate should sample **new names not used to tune the ranker**
and report: first-rank approval, selected-name coverage after fallback, number
of reviewed rows per resolved name, deferred names, and source-backed gaps.
These metrics should be reported separately from graph-edge verification and
from price or merchant availability.

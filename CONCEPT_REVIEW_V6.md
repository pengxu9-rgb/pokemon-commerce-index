# Triple-AI staged bilingual concept review, v6

The [frozen full pool](catalog/concept-review-v6-full-queue.jsonl) contains five
ranked English candidates for each of 25 new Japanese Trainer names. Reviewers
received only one candidate per unresolved name at each stage. All three
reviewed the pinned TCGdex card sources independently: GPT-6 Astra, GPT-6 Sol,
and Gemini 3.8 Flash through Vertex AI (`pivota-prod`, `global`). Gemini also
received source-matched TCGdex card images when available. No reviewer saw
another reviewer's decisions before writing its own output.

| Stage | Reviewed | Three-way approve | Three-way reject | Images supplied / possible |
| --- | ---: | ---: | ---: | ---: |
| 1 | 25 | 15 | 10 | 35 / 50 |
| 2 | 10 | 2 | 8 | 13 / 20 |
| 3 | 8 | 2 | 6 | 9 / 16 |
| 4 | 6 | 0 | 6 | 8 / 12 |
| 5 | 6 | 1 | 5 | 8 / 12 |
| **Total** | **55** | **20** | **35** | **73 / 110** |

All 55 decisions agree across all three models. This resolved 20/25 selected
names; 15 were resolved at rank 1. Staging avoided reviewing 70 of the 125
ranked rows. These are selected-packet yields, **not** blind precision or recall
measurements. Ten approved rows had both images; the other ten have an image
gap recorded in the [Gemini audits](catalog/concept-review-v6-stage1-gemini-audit.json).
An image is supporting evidence for a **name concept**, never proof of the same
physical printing, artwork, finish, condition, or price comparability.

The [55-row comparison](catalog/concept-review-v6-triple-comparison.csv) and
[final staged audit](catalog/concept-review-v6-final-staged-audit.json) retain
all decisions, image statuses, and the five unresolved names:
ポケパッド, みずの塔, サカキのカリスマ, 霧の水晶, and キャンプセット.
All five ranked candidates for each were unanimously rejected. They remain
visible gaps for another retrieval method or source, not negative claims that
an English equivalent does not exist.

Each stage retains its three independent CSVs, pinned queue, Gemini image and
request-hash audit, [consensus bundle](catalog/concept-review-v6-stage1-triple-consensus.bundle.json),
and [`proposed` edge file](catalog/concept-review-v6-stage1-proposed-edges.jsonl).
The compiler imports agreed negative review events as well as 20 agreed
internal bilingual aliases and 20 `proposed` collecting alternatives. Its
review event records all three rationales, image hashes where supplied, and
explicit evidence limits. Source images are not committed; image URLs and
hashes are retained for audit. The local index now has 455 concept review
events, 117 aliases and 117 `proposed` edges across v2–v6. It has **zero
verified physical-printing edges**. Replaying every v6 import inserted zero
records.

The approved [20 source-card anchors](catalog/concept-review-v6-anchors.jsonl)
produce [58 further card relationship candidates](catalog/concept-review-v6-relationship-queue.jsonl).
Their [audit](catalog/concept-review-v6-relationship-audit.json) records one
truncated candidate list, and the [printing review template](catalog/concept-review-v6-relationship-review-template.csv)
is untouched. No card-printing relationship from this queue has been approved.

## Reproduce and extend

The staged selector consumes cumulative reviewer CSVs. The helper below merges
immutable stage files into working inputs, then the selector releases only the
next ranked row for each unresolved name. It creates no aliases or edges.

```bash
python3 -m scripts.combine_ai_concept_review_stages \
  --catalog catalog --stages 1 2 3 4 5 --output ../../work/vertex-concept-v6
python3 -m scripts.concept_review_staged \
  --queue catalog/concept-review-v6-full-queue.jsonl \
  --astra ../../work/vertex-concept-v6/concept-review-v6-through-stage5-astra.csv \
  --sol ../../work/vertex-concept-v6/concept-review-v6-through-stage5-sol.csv \
  --gemini ../../work/vertex-concept-v6/concept-review-v6-through-stage5-gemini.csv \
  --gemini-audit ../../work/vertex-concept-v6/concept-review-v6-through-stage5-gemini-audit.json \
  --output /tmp/v6-next-queue.jsonl --sheet /tmp/v6-next-template.csv \
  --audit /tmp/v6-next-audit.json
```

The current run returns an empty next queue. Gemini's independent reviewer is
`scripts/vertex_concept_review.py`; it verifies the pinned source revision and
source hashes, checks the live API card name before using an image, calls
Vertex with `gemini-3.8-flash`, and stores no access token or image bytes. It
requires `GOOGLE_CLOUD_PROJECT` and `gcloud` authentication. Requests can be
resumed from a local checkpoint; final CSV and audit outputs are write-once.

The next coverage step is source expansion for the five exhausted names and a
blind, human-adjudicated sample to measure actual retrieval quality. The 58
card-specific candidates need separate artwork/printing review before any
cross-region price comparison or merchant recommendation uses them as an exact
product relationship.

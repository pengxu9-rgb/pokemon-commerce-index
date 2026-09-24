# Dual-AI concept import and candidate graph

On 2026-09-24 the user authorized Sol to review Astra's work and, if their
results agreed, to import aliases and create graph edges. Sol recorded its
decisions independently before comparing them with Astra. The two reviews
agree on all 39 proposals: 21 name concepts approved for **internal candidate
retrieval**, 18 rejected. Neither model is a human reviewer.

The original [human review template](catalog/concept-review-v2-template.csv)
still has 39 pending decisions. The retained [consensus bundle](catalog/concept-review-v2-ai-consensus.bundle.json)
contains all 39 proposal source snapshots, two attributed AI rationales per
proposal, and `review_basis=dual_ai_agreement_user_authorized`. Its 21 approved
concept revisions carry `reviewer=ai-consensus:gpt-6-astra+gpt-6-sol`.

The [21 graph assertions](catalog/concept-review-v2-proposed-edges.jsonl) connect
the pinned Japanese and English source cards as `collecting_alternative` with
`review_status=proposed`. They are discovery candidates, visible only when
`--include-proposed` is requested. They are not verified counterpart, artwork,
finish, offer-matching, or price-comparability claims. The existing verified
printing-edge gate remains in force. The 21 source-card [anchors](catalog/concept-consensus-anchors.jsonl)
produced [49 candidate pairs](catalog/concept-consensus-relationship-queue.jsonl)
with [audit](catalog/concept-consensus-relationship-audit.json) and an untouched
[printing review template](catalog/concept-consensus-relationship-review-template.csv).
All 21 anchors had candidates; 37 pairs used the reviewed concept plus matching
illustrator, and 12 used the reviewed concept alone. One pair includes an
offer-matching-disabled card. These are selected anchors, not a recall test.

At the v2 import, the local `catalog-index.sqlite3` snapshot contained 39
concept review events, 21 concept revisions, and 21 proposed graph assertions.
The later v3 expansion and current totals are recorded in
[CONCEPT_REVIEW_V3.md](CONCEPT_REVIEW_V3.md). It is not
committed to GitHub. Rebuild the same state in a catalog database that already
contains the pinned cards, facets, and classifications:

```bash
python3 -m pokemon_index --db catalog-index.sqlite3 import-concept-review-bundle \
  catalog/concept-review-v2-ai-consensus.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 import-relationships \
  catalog/concept-review-v2-proposed-edges.jsonl
python3 -m pokemon_index --db catalog-index.sqlite3 catalog-neighborhood \
  'ja:SM6B:057/066:normal' --include-proposed
```

Both imports are idempotent. A replay on the local database inserted zero new
rows. The compiler rejects missing proposals, changed pinned source snapshots,
AI abstentions, or any Astra/Sol decision disagreement:

```bash
python3 -m scripts.compile_ai_concept_consensus \
  --queue catalog/concept-review-v2-queue.jsonl \
  --astra catalog/concept-review-v2-ai-triage.csv \
  --sol catalog/concept-review-v2-sol-review.csv \
  --bundle NEW-consensus.bundle.json \
  --edges NEW-proposed-edges.jsonl
```

The compiled output files are immutable audit artifacts; this command refuses
to overwrite them. The v2 human template remains the place for genuine human
signoff. A later human correction needs a superseding concept revision and
corresponding graph review events instead of editing these retained AI events.
The current human sheet compiler emits revision 1, so a supersession workflow
must be added before importing a correction over these AI revisions.

Source limitations documented in [Astra's audit](CONCEPT_REVIEW_V2_AI_AUDIT.md)
and [Sol's review](SOL_CONCEPT_REVIEW_V2.md) remain open: Mustard's pinned
English TG27 effect is a placeholder, some Japanese Energy type symbols are
missing from text extraction, and Team Magma Grunt lacks a supported English
candidate in this packet. No public card display rights or marketplace price
feed is inferred from this import.

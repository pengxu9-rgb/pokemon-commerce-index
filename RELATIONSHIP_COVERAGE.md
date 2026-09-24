# Independent relationship retrieval coverage sample

The [blind anchor sample](catalog/relationship-coverage-anchors.jsonl) contains 30 Japanese card identities, three from each of ten risk strata. It excludes every anchor in the original [relationship pilot](catalog/relationship-pilot-anchors.jsonl). Selection uses a fixed SHA-256 ordering over the existing catalog, so this challenge set can be reproduced without choosing cards because the current candidate generator happened to find them. It is deliberately stratified, **not** a population-representative sample.

The [audit](catalog/relationship-coverage-audit.json) records source populations and a *candidate probe*. The current single-character plus illustrator generator produces at least one candidate for **12 of 30 anchors** and none for 18. All three sampled multi-character, trainer, energy, missing-facet and supplemental-Pokémon anchors return no candidate. These numbers describe the generator's structural reach on this small selected sample; they are **not recall**, because nobody has yet independently established the correct cross-region answers. The trainer, energy and supplemental examples come from an unverified printing-identity source and must be checked for identity gaps before any positive link.

## Blind review handoff

Make a controlled working copy of [the empty gold template](catalog/relationship-coverage-gold-template.jsonl) outside the repository. Reviewers should use card-specific source material and should **not** open the original relationship pilot queue or the candidate probe while establishing target answers. For each anchor:

- Confirm the exact Japanese printing, including set, number, finish and any stamp or edition. If this cannot be established, set `review_status` to `identity_gap` and explain it in `rationale`.
- Independently identify English printings that are `localization_counterpart` or `same_artwork`. These labels may both apply to one target. Enter each as `{ "card_id": "...", "relation_type": "...", "evidence_ref": "card-specific source" }` in `expected`. An empty `expected` list means no known answer was established; it adds no positive pair to the recall denominator.
- Put two distinct reviewers in `reviewers`, each with `id`, offset-aware `reviewed_at` and their own `answers` list of `{ "card_id", "relation_type" }`. Both answer lists must match `expected` before `review_status` is set to `adjudicated`. Provide `anchor_evidence_ref` and a card-specific `rationale`.
- Use `uncertain` when evidence does not support a decision. Do not guess an English counterpart from matching character, artist, rarity or collector number.

The validator checks completeness and agreement in the file; it does not authenticate the people or the underlying images. Neither the template nor the report grants public display rights. Do not commit completed review evidence containing private links.

## Reproduce and measure

Generate new files at unused paths:

```bash
python3 -m scripts.relationship_coverage sample \
  --db catalog-index.sqlite3 \
  --exclude-anchors catalog/relationship-pilot-anchors.jsonl \
  --anchors ../../work/relationship-coverage/anchors.jsonl \
  --gold-template ../../work/relationship-coverage/gold.jsonl \
  --audit ../../work/relationship-coverage/audit.json
```

Only after independent review, evaluate against that locked anchor file:

```bash
python3 -m scripts.relationship_coverage evaluate \
  --db catalog-index.sqlite3 \
  --anchors catalog/relationship-coverage-anchors.jsonl \
  --gold ../../work/relationship-coverage/gold.jsonl \
  --max-per-anchor 12 \
  --output ../../work/relationship-coverage/recall.json
```

The report gives positive-pair recall separately for counterpart and artwork links, by risk stratum, with every missed target and generator gap. A zero-positive denominator yields `null` recall. The current empty template produces zero reviewed anchors and `null` recall. This evaluator measures **candidate retrieval**, not the precision of the relationship classifier or offer matching; those require separately reviewed candidate pairs and listing labels.

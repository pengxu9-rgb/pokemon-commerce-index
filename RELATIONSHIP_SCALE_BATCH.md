# Relationship graph: first thousand-pair batch

This batch expands the **candidate** graph before another small manual checkpoint.
It does not add verified `same_artwork`, `localization_counterpart`, printing,
offer, or price-equivalence edges.

## Frozen batch

| Lane | Cases | Breadth | Source check |
| --- | ---: | --- | --- |
| Japanese ↔ English relationship candidates | 1,000 distinct pairs | 880 Japanese anchors, 83 Japanese sets, 70 English sets | All 1,734 distinct pinned TCGdex source files rehashed against the catalog |
| Japanese same-set/number multi-record candidates | 462 groups | 31 Japanese sets; includes the earlier 80 SV11B groups | Every record rehashed against the pinned Japanese source; exact official card-page URLs retained |

The [cross-region queue](catalog/relationship-scale-v1-queue.jsonl),
[review template](catalog/relationship-scale-v1-review-template.csv),
[selection audit](catalog/relationship-scale-v1-audit.json), and
[source audit](catalog/relationship-scale-v1-source-audit.json) form one batch.
The [Japanese variant queue](catalog/ja-variant-review-all-queue.jsonl) and
[variant audit](catalog/ja-variant-review-all-audit.json) form the second lane.
All review decisions start as pending; candidates are not imported as verified
graph assertions and cannot authorize offer matching or public card display.

## What the batch reveals

- 809 cross-region pairs share an exact Pokédex-character signature and
  illustrator; 148 share the character signature without illustrator agreement.
  Another 43 came from an approved bilingual concept, 31 also sharing an
  illustrator. These are retrieval signals, not proof of common artwork.
- 114 of the 1,000 pairs include a card whose exact offer matcher is disabled.
  A relationship review must not change that flag.
- The batch has no trainer, energy or second-source supplemental Pokémon pairs.
  Current approved bilingual concepts do not cover those categories; the
  generator abstains rather than matching by collector number or loose title.
- Of the 462 Japanese multi-record groups, 348 differ in source `jp_id`,
  official page URL and image URL only. Another 113 also differ in source
  attribution; one additionally differs in `card_type`. There are 433
  two-record, 19 three-record, nine four-record and one eight-record group.
  These fields reveal source-record differences, not physical finish differences.

## Next bulk review

1. Run Gemini artwork triage on the 1,000 frozen cross-region pairs in
   checkpointed batches. Record both image identities and abstentions. Do not
   equate a same-artwork verdict with same printing or comparable price.
2. Compare the 462 multi-record Japanese groups using exact official pages and
   images. Classify `duplicate_source_record`, `distinct_artwork`,
   `possible_finish_or_stamp`, or `insufficient_evidence`; keep the current
   set-and-number catalog identity match-disabled until exact printing evidence
   exists.
3. Measure decisions by stratum, source era, set and signal, including
   disagreement and missing-image rates. Add new bilingual concept coverage
   for trainers and energy only from independently checked exact cards.
4. Import only independently supported, typed assertions into the reviewed
   relation graph. Cross-region offer comparison must still resolve the exact
   regional printing, condition and fresh landed cost separately.

The batch can be regenerated with `scripts.build_relationship_scale_batch`
and `scripts.build_jp_variant_evidence_queue` against the pinned source
checkouts. The source auditor is `scripts.audit_relationship_scale_sources`.

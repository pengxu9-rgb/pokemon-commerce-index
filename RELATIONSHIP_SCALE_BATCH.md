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

## Completed visual and number review

Gemini 3.8 Flash reviewed all 1,000 frozen cross-region candidates in
checkpointed parts: **587 same artwork, 50 different, 351 insufficient images,
three uncertain and nine model errors**. Only 649 pairs had both images. The
[full visual audit](catalog/relationship-scale-v1-gemini-audit.json),
[stratified analysis](catalog/relationship-scale-v1-visual-analysis.json), and
[363-row follow-up queue](catalog/relationship-scale-v1-visual-followup.jsonl)
retain evidence and abstentions. The 587 same-artwork findings were compiled
as [proposed internal graph edges](catalog/relationship-scale-v1-proposed-edges.jsonl);
they were imported into the local index, with zero verified edges from this
batch. The [comparison audit](catalog/relationship-scale-v1-comparability-audit.json)
allows neither price-series merging nor numeric cross-region spread.

The [numbering audit](catalog/relationship-scale-v1-numbering-audit.json)
found only eight identical complete numbers among those 587 same-artwork
candidates; 536 differ in both numerator and denominator. This selected cohort
does not estimate population rates or visual accuracy. See
[AGENTIC_GRAPH_ARCHITECTURE.md](AGENTIC_GRAPH_ARCHITECTURE.md) for how a
release-scoped number should interact with the graph and agent.

All 967 official source images across the 462 Japanese multi-record groups
were hashed; [all 462 groups](catalog/ja-variant-image-hash-evidence.jsonl)
have distinct image byte hashes within their group, per the
[image audit](catalog/ja-variant-image-hash-audit.json). Byte differences do
not yet classify physical finish, stamp or exact artwork differences. No
printing identities or offer matching permissions changed.

## Next evidence work

1. Revisit the 363 cross-region incomplete/uncertain/model-error pairs with
   exact source images or independent visual evidence. Investigate retrieval
   gaps for trainer, energy and supplemental-source Pokémon separately.
2. Compare the 462 multi-record Japanese groups visually. Classify duplicate
   source record, distinct artwork, possible finish/stamp, or insufficient
   evidence; retain match-disabled set-and-number identities until exact
   physical printing evidence exists.
3. Independently calibrate a stratified sample of the 587 AI positives and 50
   negatives before any `verified` relationship promotion. Record precision,
   disagreement and source-era effects rather than treating model output as
   ground truth.
4. After an authorized offer feed arrives, match exact regional printing and
   photographed condition before computing destination-specific landed asks.

The batch can be regenerated with `scripts.build_relationship_scale_batch`
and `scripts.build_jp_variant_evidence_queue` against the pinned source
checkouts. The source auditor is `scripts.audit_relationship_scale_sources`.

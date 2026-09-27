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

The [blind calibration](RELATIONSHIP_CALIBRATION.md) sampled 150 `same`
results, all 50 `different` results and all 12 uncertain/model-error results.
On identical image bytes, the image-only repeat agreed on 149/149 `same` and
47/50 `different`; ten cases still lack stable original image bytes. An
18-case palette challenge identified five `derived_recolor` candidates,
which the [v2 comparison audit](catalog/relationship-scale-v1-comparability-v2-audit.json)
separates from `separate_artwork`. These are stability and taxonomy signals,
not matching precision or verified graph edges.

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

## Source recovery and Japanese visual comparison — 27 September

The [missing-image diagnosis](catalog/relationship-scale-v1-image-gap-diagnosis-audit.json)
separates the 351 original incomplete JP/EN pairs. On the Japanese side,
207 have no official set-and-number record in the pinned source, 23 conflict
on set total, eight conflict on name, 20 have multiple exact official
records, and 42 have one exact record whose image was previously unavailable.
The English side had 98 failed fetches. Neither a nearby card number nor a
default variant image was substituted for these gaps.

After support for the official `legend` image path and source-bound fetch
retries, [68 pairs](catalog/relationship-scale-v1-recovery-v2-audit.json) gained
both images: Gemini classified 62 same artwork, five different artwork and
one uncertain. Across the frozen thousand pairs the current counts are **649
same, 55 different, 283 still lacking images, four uncertain and nine model
errors**. The [v3 comparison](catalog/relationship-scale-v1-comparability-v3-audit.json)
still allows zero price merges or numeric regional spreads. All 62 new
[graph assertions](catalog/relationship-scale-v1-recovery-proposed-edges.jsonl)
were imported locally as `proposed`, bringing this batch to 649 proposed
same-artwork edges and zero verified edges.

For Japanese same-number records, the first full visual pass covered all
462 groups. A second source fetch was required where official image bytes
had changed. Of 37 retry groups, 34 had matching hashes in two independent
fetches; 31 then yielded usable AI comparisons. The
[merged visual audit](catalog/ja-variant-artwork-ai-v2-audit.json) now has
456 groups with **499 image-to-reference comparisons labelled exact artwork**,
and six groups lacking stable images. The
[follow-up queue](catalog/ja-variant-artwork-followup-v2.jsonl) contains
273 groups where the model noticed a possible surface or stamp difference,
plus those six image gaps. This is a statement about the official scans'
visible illustrations, not proof of foil, stamp, edition or separate physical
printing. All 462 groups remain pending for printing identity and offer
matching.

## Next evidence work

1. Seek additional exact, licensed image sources for the 283 still incomplete
   cross-region pairs; preserve set-total and name conflicts for source
   correction rather than inference. Investigate retrieval gaps for trainer,
   energy and supplemental-source Pokémon separately.
2. Obtain printing-specific evidence for the 273 Japanese groups with possible
   surface or stamp differences, and resolve the six unstable image groups.
   Keep the multi-record identities match-disabled until then.
3. Obtain independent adjudicated labels on a precommitted probability sample
   before any `verified` relationship promotion or production precision
   claim. The same-model blind repeat found classification conflicts but is
   not ground truth.
4. After an authorized offer feed arrives, match exact regional printing and
   photographed condition before computing destination-specific landed asks.

The batch can be regenerated with `scripts.build_relationship_scale_batch`
and `scripts.build_jp_variant_evidence_queue` against the pinned source
checkouts. The source auditor is `scripts.audit_relationship_scale_sources`.

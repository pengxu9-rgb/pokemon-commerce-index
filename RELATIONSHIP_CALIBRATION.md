# Cross-region artwork comparison: blind calibration

Prepared 26 September 2026 against the frozen 1,000-pair Japanese/English
candidate batch. This is **same-model stability testing**, not a precision or
recall estimate. No result creates a verified graph edge, exact printing,
shared price series or marketplace price.

## Sample and method

- The [frozen sample](catalog/relationship-scale-v1-calibration-sample.jsonl)
  contains 150 of 587 first-pass `same` findings, stratified across seven
  retrieval reasons; all 50 `different` findings; and all 12 `uncertain` or
  `model_error` cases. Selection within each positive stratum is deterministic
  by candidate ID. The [sample audit](catalog/relationship-scale-v1-calibration-sample-audit.json)
  records counts and a content hash.
- The second pass received **only two images**. Its prompt contained no card
  name, number, previous label or previous rationale. Images were fetched
  into memory and required to match their original SHA-256. It used Gemini
  3.8 Flash again with a different image-only prompt. The
  [results](catalog/relationship-scale-v1-calibration-second.jsonl) retain
  source and response hashes, not image bytes.
- One transient image-fetch error was recovered against the same audited
  hashes; its [retry audit](catalog/relationship-scale-v1-calibration-retry-audit.json)
  retains both result hashes. Thirteen initial image-hash mismatches were
  checked twice: three URLs again returned stable original bytes and were
  safely rerun, nine returned stable but different bytes, and one varied
  across requests. See the [source-drift audit](catalog/relationship-scale-v1-source-image-drift-audit.json)
  and [recovery audit](catalog/relationship-scale-v1-calibration-source-recovery-audit.json).

## Result

| First pass | Second pass on identical image bytes | Unresolved image hash | Meaning |
| --- | ---: | ---: | --- |
| `same`: 150 sampled | 149 `same` | 1 | Repeat consistency in this selected sample |
| `different`: all 50 | 47 `different`, 3 `same` | 0 | Three classification conflicts |
| `uncertain`: all 3 | 1 `same`, 2 `different` | 0 | Candidates for independent adjudication |
| `model_error`: all 9 | 0 comparable | 9 | Old image bytes unavailable |

The [agreement matrix](catalog/relationship-scale-v1-calibration-agreement.json)
and [16-case follow-up queue](catalog/relationship-scale-v1-calibration-followup.jsonl)
retain unresolved cases. Repeating the same model and sampling from retrieved
candidates cannot establish production matching precision.

## Exact artwork versus recolor

The three `different→same` conflicts involved rainbow or materially altered
color treatment over similar composition and linework. We selected every
first-pass conclusive rationale containing `rainbow`, `recolor`, `palette` or
`gradient`: **18 pairs**, an intentionally challenging, non-random set. A
third image-only prompt chose `exact`, `derived_recolor`, `different` or
`uncertain`.

The [source-bound taxonomy results](catalog/relationship-scale-v1-recolor-results.jsonl)
returned `exact` for all ten original `same` pairs. Among eight original
`different` pairs, the model returned **five `derived_recolor` and three
`different`**. This is an AI candidate classification, not independent ground
truth. The five [derived-artwork candidates](catalog/relationship-scale-v1-derived-recolor-candidates.jsonl)
are not imported as verified graph edges.

The [v2 comparison output](catalog/relationship-scale-v1-comparability-v2.jsonl)
keeps all 1,000 original cases and changes the scoped classification from
50 `separate_artwork` to **45 `separate_artwork` plus five
`derived_artwork_candidate`**. The v1 output remains intact. Both permit
zero price-series merges and zero numeric cross-region spreads. Future graph
queries need separate `uses_artwork(exact)` and
`uses_artwork(derived_recolor)` evidence. Price comparisons still require an
exact printing, photographed condition, observation time, source permission
and complete landed quote.

## Next calibration gates

1. Reconcile the ten unresolved source-image hashes against pinned exact-card
   records. A changing URL cannot replace content-addressed evidence.
2. Recover exact images for the 351 original `insufficient_images` pairs,
   without silently substituting a default variant image.
3. Classify the 462 Japanese multi-record groups by artwork lineage and
   physical finish evidence. Different image bytes alone do not establish
   separate printings.
4. A production precision claim needs independently adjudicated labels on a
   precommitted probability sample. Same-model agreement is insufficient.

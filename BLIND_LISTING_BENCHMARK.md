# Blind marketplace listing benchmark

This benchmark measures whether a **title-only** automatic decision points to the exact card printing and grade. Reviewers can inspect the authorized listing description and images to establish the answer. A title that does not contain enough evidence should make the matcher abstain. The benchmark does not validate image AI, authenticity, condition, market prices or paid sales.

The title matcher is evaluated without a source policy argument so this benchmark isolates its matching behavior. A source such as eBay may still require a separate photo-resolution gate before any offer is indexed. Passing this title benchmark does not bypass that source gate.

## Sampling and rights

1. Obtain a source feed and written permission for internal listing review, retention and the intended evaluation. Record a rights reference and retention period outside the repository. Do not reuse the 68 AI-assisted draft labels or the 467 development-time Mercari cassettes as a fresh holdout.
2. Define a real sampling frame before invoking the matcher: source, collection window, search/category scope, pagination depth and missing-page behavior. Save **one observation per native listing ID**. Do not select on matcher acceptance, card identity or price. A random representative cohort supports an estimate for that documented frame; difficult hand-picked cases belong in a separate `challenge` cohort.
3. Store the input JSONL and generated sample under a private `work/` directory. Input rows require `source`, `native_id`, `title`, HTTPS `url`, timezone-aware `observed_at`; optional `description`, HTTPS `image_urls`, aligned `image_sha256` hashes of fetched image bytes and a stratum assigned before matching. Do not include proposed labels or resolver predictions. The tool records the input hash, catalog manifest and database hashes, matcher code hash, Git commit, random seed and sample membership. It does not prove that the source rights reference is genuine; an operator must verify it.

```
python3 -m scripts.blind_listing_eval prepare \
  --frame ../../work/benchmark/frame.jsonl \
  --catalog-db catalog-index.sqlite3 \
  --catalog-manifest catalog-build-manifest.json \
  --out-dir ../../work/benchmark/representative-v1 \
  --sample-size 500 --seed 20260928 --cohort representative \
  --authorization-ref 'internal rights record ID' \
  --frame-ref 'source, collection window, category, and pagination record'
```

`prepare` draws the sample without reading matcher outcomes. The reviewer queue has titles, descriptions and URLs; predictions are in a separate file. Keep `predictions.jsonl` and the manifest from reviewers until gold labels are frozen. The catalog database must be a listing-free snapshot with counts matching the build manifest. `prepare` refuses to overwrite an existing sample directory.

## Independent review

Use the local [review workbench](catalog/review-workbench.md) with the generated `review_queue.jsonl`. Two distinct reviewers label each listing without seeing the predictions; a third person adjudicates disagreements. Reviewer IDs are recorded but the local workbench does not authenticate people, so the study owner must verify reviewer independence. A specific printing or known raw/graded status requires a viewed listing photo and evidence notes. `unknown` means the evidence cannot establish that field; a blank grade is never silently called raw. The exact printing code may be entered as `standard`, `normal`, `holo`, `reverse_masterball`, a vintage edition code, or another catalog code when the image evidence supports it. If the physical printing is clear but absent from our catalog, keep its true code and count the mismatch as a catalog gap.

The workbench exports `item_key`, language, single-card status, card number, printing, explicit grade status, reviewer provenance and evidence notes. **It exports only completed double reviews**, so the benchmark evaluator checks the full frozen sample and reports pending rows rather than shrinking the apparent denominator.

```
python3 -m scripts.review_workbench serve \
  --queue ../../work/benchmark/representative-v1/review_queue.jsonl \
  --db ../../work/benchmark/representative-v1/reviews.sqlite3 --port 8766
python3 -m scripts.review_workbench export \
  --queue ../../work/benchmark/representative-v1/review_queue.jsonl \
  --db ../../work/benchmark/representative-v1/reviews.sqlite3 \
  --output ../../work/benchmark/representative-v1/human_gold.jsonl
python3 -m scripts.blind_listing_eval evaluate \
  --sample-dir ../../work/benchmark/representative-v1 \
  --gold ../../work/benchmark/representative-v1/human_gold.jsonl \
  --output ../../work/benchmark/representative-v1/report.json
```

## Interpretation and decision

The report keeps four measures separate: language+set+number identity, exact printing (identity+variant), grading status/company/value, and the joint printing+grade target. For each it reports accepted evaluable predictions, errors, precision, a Wilson 95% lower bound, accepted coverage and accepted predictions whose gold field is unknown. It also reports overall acceptance, pending reviews, non-single false accepts and per-stratum joint results. Raw condition buckets are outside this benchmark. A `challenge` cohort is reported separately and cannot become a population estimate.

**Proposed first auto-join gate:** complete the representative cohort, independently verify its sampling frame, obtain at least 300 accepted predictions with a fully known joint printing+grade label, and require the joint precision's Wilson 95% lower bound to be at least 0.98 with zero accepted multi-card listings. Report graded and unusual-finish strata separately; any segment with thin evidence remains review-only. This gate covers the documented source and frame only. An unknown variant or grade does not count as a correct match. Repeat after material catalog or matcher changes using a new holdout.

The [AI-first review path](AI_FIRST_REVIEW.md) uses independent model agreement for routine cases and sends uncertain or conflicting cases to humans, plus a random human audit of AI approvals. The first live ask index additionally needs an authorized, sustainable listing feed and written permission to store observations, display offers and compute price statistics. Buy&Ship's partner URL-to-quote API does not provide listing discovery. Gate 1 for sold-price coverage remains separate.

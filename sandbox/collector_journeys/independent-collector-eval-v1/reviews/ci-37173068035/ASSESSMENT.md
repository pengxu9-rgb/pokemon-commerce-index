# Post-fix collector assessment: ec7104e

[CI 37173068035](https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/37173068035) completes all 30 frozen cases: zero execution errors, zero observed safety violations, and 26 mechanical passes. The 49 direct API prefixes finish within the existing ten-second limit; the slowest is 2.05 seconds in this run.

Applying the frozen rubric to every response gives **14 completed collector tasks and 21 tasks with useful progress, out of all 30**. These are agent judgments on an **exposed regression cohort**. They are not human collector testing, a new blinded evaluation, or a population quality estimate. The four mechanical failures do not capture every remaining usability weakness.

## Meaningful improvements

- “Shiny Treasure ex” reaches the correct Japanese release and exact Pikachu selection
- The comparison now reaches two source-bound identities, followed by separate focus and selection
- The stale-comparison case now genuinely creates and invalidates a comparison before rejecting an old choice
- The aesthetic question accepts the artist reply while keeping cozy/peaceful fit unverified
- Mew ex stays scoped to ex/Ex-named records; the requested difference in illustrations remains explicitly unverified
- The hard Pikachu/illustrator intersection no longer returns unrelated species

The original baseline responses reproduced unchanged in the new job. The prior review and scores remain untouched, including its two unscored execution-failure cases. Detailed per-case changes are in `agent-review-v1.json`.

## Four remaining mechanical failures

1. **ICU-03: Japanese-name recognition failure.** The explicit name リザードン yields an empty generic taste question. The snapshot has 56 Japanese Charizard-affiliated records across 48 coordinates, including exact Japanese-name records. This is a product intent-recognition failure, not missing catalog coverage
2. **ICU-26: inventory continuation failure.** “Pikachu cards I don't already own” triggers a generic negative-preference hold. Submitting the exact owned record does not advance it. There are 127 other Pikachu records across 117 coordinates. This is a material continuation failure
3. **ICU-16: safe but unapplied exclusion.** The explicit SV4A/Mew exclusion returns no progress. There are 319 records across 245 coordinates with known non-Mew primary-species facets. The hold avoids incorrect inclusion, but it is still a supported-data discovery gap
4. **ICU-11: exploration-granularity gap.** Five valid Japanese-151 variant records cover two coordinates. The frozen scenario expects five coordinate-level exploration options; the snapshot contains 210 coordinates. This is a presentation/expectation distinction, not incorrect identities or a catalog shortage

## Further usefulness limits

The AND request (ICU-09) correctly finds no current Pikachu/Yuka Morii source-facet intersection, but the response refers to an “exact coordinate” the user never gave and offers no useful relaxation. Its mechanical pass therefore receives no completion credit.

Some era, no-match and identity-hold prompts still ask about generic fields rather than the actual issue. Natural-language budgets and destinations are weakly retained, and budget/grade/delivered-price/checklist objectives remain explicitly partial. A sourced catalog shortlist is not evidence of buyability or European shipping support.

## Recommended next decision

If continuing the private collector loop, prioritize Japanese-name recognition and inventory/clear-exclusion continuation before adding more catalog data. Improve the existing safe clarification prompts next. Treat coordinate diversification as a lower-priority presentation choice while preserving access to variants.

Keep these 30 cases as regression coverage. A further independent collector-quality claim needs a new held-out cohort after the next changes.

## Evidence

- `agent-review-v1.json`: all 30 current scores, unchanged baseline scores, explicit scoring limits and exact response paths
- `readonly-coverage-checks-v1.json`: source-facet/coordinate counts for the four failures
- `readonly-intersection-check-v1.json`: empty Pikachu/Yuka Morii intersection
- Read-only catalog SHA-256: `d1118b9241e014b56455ff93228bb52d208a5856aac49eaa6489d6f7e045b4f9`; bytes remained unchanged

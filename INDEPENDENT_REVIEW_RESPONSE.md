# Response to the independent review (2026-09-28)

The review correctly changes the near-term priority: stop treating catalog breadth or AI agreement counts as product progress, and prove listing-match precision on a narrow, authorized offer slice. The changes below address code defects without implying that a live price product now exists.

## Confirmed and changed in this revision

| Finding | Change | Remaining limit |
| --- | --- | --- |
| P1-1, ambiguous grades entered PSA/BGS series | Grade tokens now need slab or certificate wording. Aspirational, former-slab, multiple-grade and special-label phrases abstain. Adversarial title tests added. | This is a conservative text rule, not measured precision. A blind real-title gold set is still required. |
| P1-2, edition markers collapsed into unlimited | First edition, unlimited and shadowless markers are distinguished; an unmarked vintage edition family abstains. | Printed edition and physical finish still require product evidence. |
| P1-3, Docker catalog differed from documented catalog | One SHA-256 checked, ordered `catalog-build-manifest.json` now drives local rebuild and Docker. Build asserts 55,167 cards, 33,543 eligible, 19 exceptions and two conflict rules. CI is configured to rebuild it. | The Docker image has not been built locally and Cloud Run has not been redeployed or verified in this revision. The private snapshot intentionally excludes proposed graph edges. |
| P1-4, stale photo approval entered `verified_paid` | The paid series now requires approval for the last on-sale observation before settlement. | Payment evidence is still source-supplied; no live feed exists. |
| P2-1, historical index restated without a cutoff | `index` now accepts and returns `as_of`, and filters observations, resolution events, approvals and sales by that knowledge time. | No persisted publication vintages or measured cancellation window yet. |
| P2-7, numeric gap on a proposed artwork edge | Numeric cross-region comparison now requires a verified artwork edge. | There are currently zero verified edges in the local snapshot. |
| P2-8, recommendation used an unbound landed quote | Recommendation and cross-region comparison now use the same source-price, currency, FX, fee and tax binding rule. | Real fee schedules and FX evidence remain unavailable. |
| P1-5, eBay pilot queries used internal set IDs | Removed executable query strings and the 14-day call plan from the 100-card identity cohort. Each target now requires sourced marketplace vocabulary. | eBay production/data-use rights and a query hit-rate test are still pending. |
| P3-1 and P3-2, test dependency and connection close | Declared Pillow as a test extra; CLI database contexts now close connections. | Container build has not been run locally because Docker is unavailable here; CI includes it. |

## Reconciled count

The local snapshot's 852 is an **assertion-event count**, not a count of distinct relationships: 730 proposed same-artwork events cover 705 distinct card pairs, and 122 collecting-alternative events cover 122 pairs. The 25 extra same-artwork events repeat pairs under separate event IDs. The review's 827 distinct pairs is therefore compatible with the snapshot's 852 events. An ordered graph build manifest is still missing; none of these proposed links is deployed as a verified claim.

## Accepted findings still open

- P1-5: English and Japanese marketplace aliases need sourced vocabulary and measured query recall. The eBay cohort is paused pending that work and rights.
- P1-6: eBay data-use scope needs a written answer; no eBay listing or image is processed here.
- P2-2/P2-3/P3-3: vintage Japanese eligibility, incomplete Prism Star corrections and fail-open seed defaults need a source-backed eligibility audit before any real offer matching. Do not infer production match precision from `match_eligible`.
- P2-4/P2-5: model-family identity is operator-attested rather than provider-verified, and re-reviewing every poll is operationally expensive. The current photo gate is a synthetic-data contract, not a production certification service.
- P2-6: proposed graph assertions still need one ordered reproducible import and independent gold labels. Further AI review rounds are deferred.
- Actual feed access, rights, fees, paid-sale semantics, retention, scheduler, persistent storage and observability remain external or unimplemented.

## Next measurable gate

Create a blind, stratified corpus of at least 300 authorized real marketplace titles with exact card, grade and variant labels, including negative and ambiguous examples. Report auto-accept precision with its denominator and confidence interval, plus abstention and recall by bucket. Only then connect a permitted feed for about 100 modern Japanese cards and calculate current asks with sample count and freshness. A clearing-price series remains conditional on the original Gate 1 coverage and bias measurement.

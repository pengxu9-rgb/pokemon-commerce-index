# Collector recommendation loop — 3 October 2026

## Publication handoff — 4 October 2026

The user has requested publication to GitHub and an independent DOT review, followed by DOT-led push/deployment work. The sections below record the 3 October local delivery; their "not pushed" statements describe that earlier milestone. Resolve the current GitHub main commit for the published source. This publication step does not deploy Cloud Run or enable a live marketplace feed. The latest deployment receipt remains `cloud-deployment-20261003-source-binding-v1.json` and must be checked against live cloud state before rollout.

## Delivered locally

The DOT review is implemented as one internal collector loop:

`collecting goal → validated preferences → explainable shortlist → feedback → evidence-only comparison → exact focus → separate catalog selection`

This closes the recommendation gap without a marketplace API, model call or catalog-wide aesthetic annotation. Existing character/artist facets and catalog coordinates supply the matching evidence. The catalog/relationship dataset is unchanged. This implementation has not been pushed or deployed; the previously recorded private Cloud Run deployment still serves the earlier runtime. Pivota registration and caller service authorization remain separate work.

## Behavior and limits

- Collecting preferences are optional patches to the existing preferences action: mode, preferred/excluded dex IDs, exact current illustrator credits, language/release pairs and subjective notes. Arrays replace; empty arrays clear; null removes. Unknown fields, duplicates, unsupported releases/artists, boolean dex IDs and conflicting preferred/excluded species are rejected.
- A completed collection is context, not a new search axis or verified inventory. A language-only reply still asks one focused preference question. Supported character, exact artist and release replies can continue the original goal. Arbitrary replies are retained as unapplied taste; they are not concatenated into the original query. Parsing is deliberately bounded, with current catalog names and narrow Chinese Pikachu/Mew aliases; broader natural-language understanding is not established.
- Rank the complete bounded query before pagination: explicit matching axes, then source-backed character/artist axes shared with liked examples. Equal-score coordinate groups alternate in stable ID order; each version keeps its own ID. There is no price, rarity, newness, popularity or investment boost. The 10,000-record ceiling asks for narrowing rather than silently truncating the pool.
- Hard language/set/number/variant scope remains separate from soft preferences. Explicit supported number assertions are not discarded; multiple/alphanumeric number assertions ask for clarification/exact IDs. Existing unsupported scope constraints survive the recommendation path.
- Feedback requires a card shown in the current recommendation context, including visited pages. Latest reaction wins. Dismiss excludes exactly that card; clear removes its reaction. Feedback/preference changes reset pagination and withdraw a target. New goals preserve explicit preferences/inventory and start fresh feedback; goal/scope/preference/inventory changes invalidate old comparison/page membership.
- Shared inventory partitioning excludes both resolved and possibly owned records. Unresolved inventory prevents selection. User assertions do not verify ownership.
- Comparison remains evidence-only, with no candidates or target intent. Explicitly choose a resolved side and exact member ID to obtain one freshly hydrated focus; a separate select is still required. Alphanumeric IDs do not pass through the digit-only scope parser.
- Per-card selection blockers check structural identity eligibility, endpoint/source-number conflicts, held/stale number evidence, source-fact warnings, coordinate-family restrictions, numbered parts and source-only families. A blocked record remains inspectable but cannot be selected even if another page record is selectable.
- `candidate_pool_complete` describes only the bounded current catalog query. It never means complete physical-printing, depiction or worldwide coverage. Budget/grade availability and aesthetic fit remain unknown. Pure cheapest/buy/profit goals retain market blockers. Prices/offers remain empty; product URL, priceable unit and quote remain null; physical, commerce and public-display approvals remain false.

The caller validates exact action shapes and recommendation/page correspondence, actual-source-reference shapes, absolute ranks, group identity and nested authority flags. The new runtime is included in the catalog revision; a coordinated server/caller rollout must restart/reconfirm older sessions.

## Actual before/after examples

| Request | Before the change, reproduced in the DOT review | Current local behavior |
|---|---|---|
| Completed Pikachu → what next? → English → Mew | No candidates; taste reply entered generic scope clarification | Returns five English Mew catalog candidates with facet provenance and individual identity holds |
| Recommend Japanese Pikachu under $50; like cute cards | Ordinary date-ordered character search; budget/style omitted | Source-backed ranked shortlist; USD 5,000 minor units retained as an assertion; budget fit unknown and cute preferences explicitly unapplied |
| Select `ja:20TH:001/072:unverified` | Could produce a catalog target despite `match_eligible=false` | Inspectable record; `catalog_identity_review_needed`; selection denied |
| Dismiss a shown card | No feedback action | Exact ID excluded; other versions/species matches remain |
| Compare two shown IDs → choose right → select | Comparison had no explicit exit | Evidence-only comparison → single exact focus → separately confirmed catalog-only target |

The current whole-catalog examples deliberately retain research records. For example, some English Mew candidates have disabled structural matching and cannot be selected. This demonstrates the guard; it does not establish that the broad catalog is a production recommendation allowlist. [Final local examples](sandbox/collector_journeys/recommendation-v1/verified-catalog-examples.json) bind the snapshot/revision and contain actual actions/responses, including dismissal and catalog-only selection. The snapshot bytes are unchanged.

## Validation actually run

| Check | Result |
|---|---|
| Full Python regression suite | **626 passed**, including 25 recommendation tests; existing resource-cleanup warnings remain |
| Node caller/operation tests | **15 passed** |
| Frozen new synthetic suite, direct replay vs actual Python HTTP → Node caller | **13 journeys / 42 prefix steps passed**, English/Japanese/Chinese continuations, six A–F families; catalog bytes unchanged |
| Original unchanged v2 conversations on the current catalog | **36/39 expectations passed**; three old candidate statuses changed to evidence-needed because every visible record was already `match_eligible=0`; original report retained |
| Versioned v2 compatibility fixture | **8 journeys / 39 prefix steps passed**, with only those three states tightened to require selection blocking and an identity hold on every candidate |
| Whitespace/diff checks | Passed |
| Docker build | **Not run: Docker is unavailable in this environment** |
| Cloud rollout / remote CI / push | Not performed |

The original v2 fixture is unchanged. The [three expectation changes](sandbox/collector_journeys/recommendation-v1/legacy-expectation-changes.json), [unadjusted result](sandbox/collector_journeys/recommendation-v1/legacy-v2-http-report.json), [final compatibility result](sandbox/collector_journeys/recommendation-v1/final-legacy-http-report.json) and [final new-loop result](sandbox/collector_journeys/recommendation-v1/verified-local-http-report.json) remain distinct. These are authored engineering diagnostics, not independent or real-user recommendation quality measurements.

Commands:

```bash
python3 -m unittest discover -s tests -q
node --test integrations/pivota/collectorClient.test.cjs integrations/pivota/collectorOperation.test.cjs
python3 -m scripts.rehearse_collector_recommendations --output /tmp/new-recommendation-report.json
python3 -m scripts.rehearse_pivota_collector \
  --db /tmp/pokemon-source-binding-v1.sqlite3 \
  --suite sandbox/collector_journeys/recommendation-v1/legacy-v2-identity-holds-suite.json \
  --output /tmp/new-legacy-compatibility-report.json
git diff --check
```

Reports require a new output path. The real-catalog compatibility replay uses the existing source-binding snapshot; no catalog import or price feed was performed.

## Main changed files

- `pokemon_index/collector_recommendation.py`: bounded preferences/parser, source-backed candidate generation, complete-pool ranking, diversity and feedback validation.
- `pokemon_index/collector_journey.py`: context/reset rules, recommendation integration, per-record blockers and explicit comparison bridge.
- `pokemon_index/collector_inventory.py`: shared exact/possible inventory partitioning reused by ordinary inventory comparison.
- `integrations/pivota/collectorClient.cjs`: new actions, recommendation validation, nested authority guards and five-card default.
- `tests/test_collector_recommendation.py`, caller tests and `sandbox/collector_journeys/recommendation-v1/reviewed-suite.json`: outcomes and misuse/uncertainty coverage, alongside existing suites.
- Rehearsal scripts, integration README, project README and build sequence: reproducible diagnostics and updated product priority.

## Next product gate

Evaluate a deliberately supported collector slice with questions and expected outcomes selected independently of implementation tuning. Measure relevant candidate precision, explanation evidence and clarification usefulness separately from safety abstention. Prioritize catalog/graph gaps exposed by these tasks; do not use catalog counts or agreeing AI votes as a user-quality score.

Fresh offers, actual copy-condition assessment, landed-cost merchant comparisons and transaction handoff still require an authorized listing feed and relevant evidence. Subjective style annotation or an LLM preference extractor may be added later through the same validated action contract; neither may mint identities, prices or approvals.

# Seller routing v7 — 2026-09-30

## What changed

V7 preserves selling tasks that the frozen v10 diagnostic exposed as gaps:

| User request | Structured intent | Evidence plan |
| --- | --- | --- |
| Sell the collection all at once | Explicit `lot`; no inferred bulk sale | Clarify inventory, supported game, channel and selling goals. |
| Does BOOKOFF buy rotated normal cards? | `merchant_acceptance` | Check current acceptance and submission terms for the named store. |
| Find a buyback store in Tokyo | `merchant_discovery`, `merchant_location` | Retrieve a current store directory, then verify candidate acceptance terms. Location remains distinct from a shipping destination. |
| Mercari versus store profit | `seller_net_proceeds` | Establish exact units and copy conditions; request settled-sale evidence, coverage, fees, shipping, store quotes and terms. Paid acquisition cost is needed for profit. |
| Multiple chains, Pokémon and Yu-Gi-Oh | All explicit `merchant_refs`, `mixed_tcg` | Ask to separate the supported game scope before catalog or merchant comparisons. |

`merchant_ref` is retained for backward compatibility: it equals the sole named store, or null when no store or multiple stores are named. Secondary seller tasks remain in `seller_tasks`. V6 code and the original v10 evaluation remain unchanged.

## Operational boundary

These are **evidence plans**, not an executed merchant-search service, payout calculator or recommendation engine. A ready action means its declared capability is available; it does not mean retrieved evidence exists or passed review. Candidate-specific terms also depend on the merchant-candidate retrieval action. Future execution must enforce action dependencies and validate returned data before making claims.

A paid-cost phrase is distinguished from a market ask or proposed purchase price. Net proceeds can eventually be compared before acquisition cost is known; profit cannot. A lot price cannot be derived by adding single-card asks. Direct planner callers must supply trusted cohort envelopes; the CLI verifies the envelope against a read-only catalog snapshot and rejects stale or fabricated hashes.

The new `current_merchant_directory` capability is independent of merchant buyback terms, quotes and fulfillment outcomes. A directory alone cannot establish store reliability or best payout. The index still requires an authorized marketplace feed and data-use scope for live prices. No credentials or market observations were added by this change.

## Validation

The [development freeze](sandbox/public_questions/v10/v7_development/manifest.json) pins eight previously viewed, source-condensed v10 cases, the v7 extractor/planner, the catalog and pre-call AI researcher expectations. They are targeted regression cases, **not unseen generalization, raw-language accuracy, human truth or answer accuracy**. The old [v10 diagnostic](QUESTION_ROUTING_V10_DIAGNOSTIC.md) remains the baseline.

| Development replay measurement | Result |
| --- | ---: |
| Schema-valid extraction | 8/8 |
| Goal within pre-call AI researcher expectations | 8/8 |
| Selling formats within expectations | 7/7 evaluated |
| Cases with all specifically expected fields matching | 6/8 |
| Cases missing required evidence-plan actions | 0/8 |
| Cases with market retrieval ready without market capabilities | 0/8 |

Two facts rows (012 sorting requirements and 014 channel profit) returned an empty `seller_tasks` array despite preserving the correct primary goal. The planner deterministically includes the primary goal's task, so no requested evidence action was lost. These field disagreements remain in the report; this is not a complete extraction-accuracy pass. Question 007 correctly leaves the game scope unknown because its source-condensed wording does not name Pokémon; it asks for game scope and inventory rather than inventing a catalog match. One extraction required the bounded output-budget retry, retained in the [invocation summary](sandbox/public_questions/v10/v7_development/invocation_summary.json).

The [route report](sandbox/public_questions/v10/v7_development/route_report.json) retains every case and the original expectations. No real offers, merchant responses or profit calculations were evaluated.

Full test suite: **327 tests passed**. Coverage includes exact cohort validation against an unchanged read-only database, missing capabilities, multiple merchants, location versus destination, mixed-game scope, secondary tasks and rejecting lot classification without selling context.

## Use and reproduce

Extracted facts use the v7 schema, which extends v6 with `merchant_refs`, `merchant_location`, `tcg_scope`, `seller_tasks` and `cost_basis`.

```bash
python3 -m pokemon_index question-route-plan-v7 facts.json \
  --catalog-db catalog-index-rarity-v2.sqlite3

python3 -m scripts.evaluate_question_routes_v7 \
  --frozen-dir sandbox/public_questions/v10/v7_development \
  --catalog-db catalog-index-rarity-v2.sqlite3 \
  --facts sandbox/public_questions/v10/v7_development/gemini_facts.jsonl \
  --expectations sandbox/public_questions/v10/v7_development/development_expectations.jsonl \
  --output /tmp/pokemon-v7-development-report.json
```

The catalog file must match the frozen snapshot hash. Explicit `--capability` options are assertions by a trusted caller, not evidence of integration. Adding one does not invoke a connector.

## Next validation gate

Freeze the implementation before collecting another fresh cohort. Include unseen whole-collection phrasing, merchant acceptance/submission rules, city and online store discovery, channel net proceeds, mixed-game requests, and evolution-line selling. Include negative controls for buying collections, unnamed locations, shipping destinations, old quotes and mere ownership of many cards. Check canonical post IDs against prior cohorts; preserve source fidelity and failures in the denominator. Evaluate goal, retained facts and required actions separately. Production answer quality and exact-printing/photo precision need separate evidence.

The current cloud deployment serves the corrected private catalog. V7 is a CLI/sandbox addition; it is not yet a cloud conversational endpoint. The immutable deployment receipt continues to describe the earlier deployed revision.

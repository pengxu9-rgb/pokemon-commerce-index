# V6 — selling a class of cards

## What changed

`seller_saleability` routes questions such as “Which recent normal Pokémon cards sell individually or as evolution lines?” It separates that request from pricing one owned card, choosing when to sell, and sorting a collection. Existing goals delegate to the frozen v5 planner.

Two new facts retain the user's boundaries: `sale_scope` is a literal short substring, and `sale_formats` contains explicitly mentioned `single`, `evolution_line`, `lot` or `bulk` formats. The Gemini extractor requires source spans for both. A large collection alone does not establish bulk or lot selling. Question language alone does not establish card language.

## Evidence order

1. Explain demand, condition, net proceeds and listing effort in general terms.
2. Clarify the scope, sale formats, channel, acceptable proceeds/effort, analysis period and condition where absent.
3. Plan catalog candidate retrieval and exact-unit cohort review.
4. Only with a separately supplied unit cohort, plan per-unit live asks, verified sales and coverage checks. Marketplace selling also needs fee and shipping evidence; store selling needs buyback quotes. Evolution-line composition needs reviewed relationships.

These are **action plans**. V6 does not execute catalog category search, select a sellable-card ranking, fetch market data, or recommend a selling price. Each evidence action has a capability gate. Asks and disappearance cannot establish sales; single-card prices cannot simply be summed into a lot quote.

## Cohort integrity

The extractor cannot supply `sale_cohort`. A separate envelope contains existing priceable-unit IDs and a `catalog-unit-cohort-sha256:` evidence reference. `build_sale_cohort` checks exact unit coordinates and match eligibility, then hashes the catalog rows including provenance and rarity. Unknown condition, duplicate IDs, missing rows and changed evidence fail validation.

The CLI requires a read-only catalog snapshot to verify that envelope. This binding proves which catalog units were selected; it does not prove item condition, certify market comparability or replace review of why those units belong in the user's scope.

```bash
python3 -m pokemon_index question-route-plan-v6 \
  examples/seller_saleability_example.json \
  --catalog-db catalog-index-rarity-v2.sqlite3 \
  --capability internal_catalog
```

This example enables the catalog planning steps. It produces clarification and evidence requirements; no market action is ready without a validated cohort and the relevant capabilities.

## Known-question Gemini replay

[`sandbox/public_questions/v9/v6_development/route_report.json`](sandbox/public_questions/v9/v6_development/route_report.json) records six previously seen v9 questions against the corrected catalog. The generic normal-card question enters `seller_saleability` and preserves `single` and `evolution_line`. The SV4a question now surfaces the SAR candidate while retaining its missing-language clarification.

Five initial extractions were valid; one exhausted its output budget. A separately frozen retry used the revised extractor, logged an 8,192-token exhaustion, then completed with a 16,384-token budget. All six eventually produced valid structured facts. Initial and retry manifests, records and original invocation code snapshots are retained. The report pins the final planner and extractor hashes.

This is development replay, **not a new blind accuracy estimate**. It includes only one generic saleability question and does not establish general coverage. The next evaluation should freeze the final code and independently collect fresh questions covering single versus bulk, evolution lines, store buyback, marketplace net proceeds, explicit language/finish, and ambiguous product scope. Validate routing and evidence requests separately from factual market answers.

# Fresh v10 questions against frozen v6 — 2026-09-30

## Sources and evaluation boundary

Collected 16 new public posts, covering vintage non-holo singles, lots, bulk resale, collection sorting, store acceptance, platform versus store proceeds and a sealed-pack buyer control. Post-ID checking found no overlap with 115 prior unique posts from v1–v9, including Reddit URLs with different slugs. The [collection lock](sandbox/public_questions/v10/collection_lock.json) pinned v6 before question preparation.

Codex inspected the original question bodies through web reads or public HTTPS page reads. Five Yahoo pages needed HTTPS fallback after the web reader failed; their evidence locators retain page hashes. Only question context is used: replies, on-page AI answers and uncollected images do not supply facts. Gemini assessed researcher-transcribed contexts rather than fetching the pages independently. The [source gate](sandbox/public_questions/v10/preflight/report.json) accepted **15/16**; question 009 was excluded because its condensation converted a disposal consideration into a more explicit disposal question.

The accepted cohort has **7 English and 8 Japanese questions**, 13 text-only questions and two with uncollected images. Questions are condensed from sources, not verbatim natural-language inputs. The [manifest](sandbox/public_questions/v10/manifest.json) pins the catalog, v6 extractor/planner, resolver, runtime dependencies and pre-call researcher expectations. No routing rules were changed during this evaluation. The non-root cloud database-access fix was completed before extraction and is separately recorded in the runtime hashes.

## Results

| Measurement | Result | What it establishes |
| --- | ---: | --- |
| Schema-valid extraction | 15/15 | These questions produced validated structured facts after bounded retries. |
| Goal within pre-call researcher alternatives | 14/15 | Agreement with qualitative AI expectations, some allowing multiple interpretations. |
| Explicit selling formats within expectations | 12/13 evaluated | One batch-sale expression was missed; two cases had no committed format expectation. |
| Market actions ready without market capabilities | 0/15 | The plans do not enable quote, paid-sale, fee or buyback retrieval from absent capabilities. |
| Seller-saleability routes | 5 | New wording extends beyond the single known development question. |

The [complete route report](sandbox/public_questions/v10/route_report.json) stores each evidence plan and disagreement. The [invocation summary](sandbox/public_questions/v10/invocation_summary.json) and facts retain retries, token budgets and transport failures; failures are not silently dropped from the denominator.

This is a **small fresh diagnostic**, not measured answer accuracy or proof of production generalization. The expectations came from the same AI researcher who collected the questions; they are not blind human truth. No independent Astra labeling was run in this batch. Four rows have a stored holdout tag, but all 15 have now been evaluated once; none is an untouched future holdout. There are no verified answers, real prices, sold transactions, photo judgments or new exact-card precision measurements in this run.

## Useful outcomes and remaining gaps

- **001, 002, 004 and 010:** old non-holo cards, buying bundles to resell as singles, bulk economics and expensive XY/DP normal-card features reach the saleability evidence plan. The planner requires exact unit cohorts and market evidence before naming sellable cards or margins.
- **003:** sorting a card pile to avoid submitting valuable cards at a bulk rate reaches collection triage. That is an acceptable first step, but the current plan ends at asking for an inventory; it does not execute classification or sorting.
- **007:** “sell my collection all at once” reaches channel choice but emits no `lot` format. It needs a rule for explicit batch-sale wording, distinct from merely owning many cards. Its plan also lacks channel and inventory clarification.
- **011:** asking whether BOOKOFF accepts rotated normal cards reaches saleability. The action plan does not request current merchant acceptance terms, despite the policy question. Schema validity and an allowed coarse goal therefore do not establish an adequate plan.
- **013:** a Tokyo store recommendation request for rotated cards reaches collection triage, outside the pre-call goal alternatives, and loses the merchant-discovery task. Location and current merchant buyback scope need a dedicated representation and evidence route.
- **014:** platform-versus-store profit comparison requests fee and buyback terms, but a net-proceeds comparison still needs explicit shipping, unit scope, current buyback quotes and stated cost assumptions. Historical forum replies cannot supply those figures.
- **015:** the SNKRDUNK loose-pack authenticity question correctly explains the current single-card catalog scope. No pack contents or seller authenticity is asserted.
- **016:** multiple named chains plus another TCG expose a scope boundary. The current single `merchant_ref` field cannot faithfully represent a multi-merchant comparison.

The fresh cohort contains no new evolution-line question, so this run does not establish generalization for that relation path. Existing evolution-line regression tests remain separate.

## Next sequence

1. Preserve v10. Add explicit batch-sale language and separate merchant acceptance, merchant discovery and net-proceeds comparison from collection triage.
2. Carry merchant candidates and location separately from a shipping destination. Ask for card-language/era, sale formats and condition before requesting comparable offers or buyback quotes.
3. Collect another fresh source cohort targeting those revised boundaries and evolution-line composition, after freezing the next implementation. Keep exact-card/title precision, route quality and answer correctness as separate measurements.

Deployment verification also exposed a catalog metadata follow-up: the source set title for SV4A is recorded as `レイジングサーフ`. Audit official set-name metadata separately before treating those titles as trusted query aliases; the rarity correction itself is bound to the exact SV4A card number and official page.

## Reproduce the report

```bash
python3 -m scripts.evaluate_question_routes_v6 \
  --frozen-dir sandbox/public_questions/v10 \
  --catalog-db catalog-index-rarity-v2.sqlite3 \
  --facts sandbox/public_questions/v10/gemini_facts.jsonl \
  --expectations sandbox/public_questions/v10/researcher_expectations.jsonl \
  --output /tmp/pokemon-v10-route-report.json
```

The exact local snapshot hash is required. A rebuild has timestamped overlays and may have a different byte hash; it must not silently replace the frozen evaluation snapshot. The build manifest separately checks logical catalog counts and evidence inputs.

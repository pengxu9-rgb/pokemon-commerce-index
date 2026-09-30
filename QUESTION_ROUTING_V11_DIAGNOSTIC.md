# Fresh v11 questions against unchanged v7 — 2026-09-30

## Freeze and sources

The [collection lock](sandbox/public_questions/v11/collection_lock.json) pins v7 before new-post collection, together with the catalog, resolver, inherited routing dependencies and extractor. The planner and extraction prompt are unchanged from commit `6fe90f6`. A separate [source review lock](sandbox/public_questions/v11/source_review_lock.json) pins the concurrent runner, source questions, evidence and source-audit token budgets before the source model calls. The [evaluation manifest](sandbox/public_questions/v11/manifest.json) binds all evaluation inputs before fact extraction.

Collected 16 source posts: nine English, seven Japanese; eight Reddit posts, seven Yahoo Chiebukuro questions and one Elite Fourum topic. Canonical source checking found no overlap with 131 prior unique posts from v1–v10, including rejected candidates. The [overlap record](sandbox/public_questions/v11/source_overlap_check.json) uses Reddit thread IDs rather than slugs; the existing preflight separately checks prior question URLs.

Codex inspected original poster questions through web reads. Two failures needed direct HTTPS fallback: the Elite Fourum topic JSON and a Yahoo question page; their evidence locators retain content hashes. Gemini's source review sees researcher-transcribed contexts and short anchors, **not independently fetched pages**. Both AI reviews accepted all 16 candidates as faithful in the [source gate](sandbox/public_questions/v11/preflight/report.json). This agreement does not establish human accuracy or source truth.

The questions are source-condensed, not a benchmark of verbatim user language. Images, respondent answers, on-page AI answers and suggested merchants from replies are excluded. All questions are evaluated as fresh diagnostic cases once; there is no untouched holdout after evaluation.

## Coverage that matters

- **001 — evolution-line selling:** the original poster [asks for auction-lot suggestions](https://www.elitefourum.com/t/what-lots-bundles-do-you-like-and-recommend/21323), then in their own follow-up explicitly proposes evolution-line bundles and asks which Pokémon are most popular. Quote text from another respondent is removed. This is related to choosing sale bundles, rather than proof that a particular evolution line commands a price premium. Norway is the auction region, not an invented shipping destination or buyback-store location.
- **002, 014 — selling economics:** minimum profitable selling prices and reducing fee deductions. Historical or hypothetical forum figures remain context. The index has no current fee, shipping or settled-sale evidence for answering them.
- **003, 005 — store payout and channel choice:** liquidation horizon, risk constraints, platform options and collection scope. Merely wanting to sell a collection does not state that it must be sold as one lot.
- **007, 008, 013 — merchant discovery:** Osaka Nipponbashi, Osaka/Kyoto PSA10 buyback and Tokyo/Kanagawa condition-sensitive appraisal. Store names and era details supplied only by respondents must not enter extracted facts. A directory cannot establish fair handling, reliable fulfillment or best payout.
- **009–012 — submission and acceptance rules:** bubble-wrap transport, sleeve removal, sorting by rarity/name/buylist, and a friend's claim about BOOKOFF thickness pricing. The unnamed-shop case must clarify the merchant. Quantities of 100, 500 or 20,000 alone do not prove a selling format.
- **004 — sealed scope control:** a [sealed-product eBay-versus-shop comparison](https://www.reddit.com/r/PokeInvesting/comments/1r8ejlt/ebay_vs_local_shop/) must stay outside the single-card index even when selling economics are explicit.
- **006, 015 — collector/buyer controls:** a [cross-language Ralts-family checklist](https://www.reddit.com/r/PokemonTCG/comments/1v55rlj/is_there_an_app_or_site_that_shows_all_the/) and a casual player's proposed purchase of a random lot. Neither creates a seller format or priceable cohort.
- **016 — cost-basis control:** a [proposed business inventory purchase](https://www.reddit.com/r/PokemonTCG_UK/comments/1vmue6f/anyone_vend_on_ebay_with_a_business_account_got/) with projected expenses is not a confirmed paid acquisition cost.

The cohort has one fresh evolution-line selling situation, but no pure question comparing evolution-line sale prices against singles. It has no new mixed-TCG question, no explicit shipping-destination contrast and no complete “sell everything in one transaction” phrase. These remain coverage gaps. Positive controls for explicit all-at-once selling exist only in the older development replay and must not be presented as fresh evidence here.

## First frozen results

| Measurement | Result | Interpretation |
| --- | ---: | --- |
| Source fidelity gate | 16/16 | Agreement with supplied contexts, not independent source truth. |
| Schema-valid extraction | 14/16 | Two failures remain in the full denominator. |
| Goal within pre-call researcher alternatives | 13/14 valid | 13/16 if every failed extraction counts as a failed case. |
| Stated selling formats within expectations | 14/14 valid | Buying and collecting evolution lines did not become seller formats. |
| Specifically expected facts within expectations | 14/14 valid | Checks selected facts, not all fields or semantic precision. |
| Cases missing a required action | 1 valid case | Cost-basis clarification follows unsupported-game clarification in the implementation. |
| Cases with market retrieval ready without market capabilities | 0/14 valid | Source prices are not treated as live offers or paid sales. |

The [route report](sandbox/public_questions/v11/route_report.json) and [invocation summary](sandbox/public_questions/v11/invocation_summary.json) retain all rows, attempts, initial failures and hashes. Required-action checks apply only to cases with explicit action expectations; see the invocation summary for the relevant denominators.

### Gaps and disagreements

- **002:** the first attempt exhausted the output budget; the second timed out. No accepted facts or plan were produced. This is a runtime failure, not an intent disagreement.
- **016:** the first attempt combined a buyer transaction with a seller channel and was rejected by the existing consistency guard; the second exhausted its output budget. The user is considering buying inventory in order to sell it, exposing the limits of a single transaction-context field. A failed row is not a fabricated cost or profit estimate.
- **014:** the user did not explicitly name Pokémon in the condensed question. The planner asks for supported game scope and inventory before acquisition costs. The frozen researcher expectation also requested `ask_cost_basis`; that missing action remains recorded. This is partly question sequencing rather than an unsafe profit claim.
- **015:** Gemini chose `channel_choice`, outside the frozen researcher alternatives. Because the question is a proposed purchase and contains no seller format, it did not become a seller plan. The resulting `explain_general` action is too coarse for the combined deck-composition and buying request.
- **006:** the cross-language evolution-family checklist maps to `other` and general explanation, which is within the deliberately broad alternatives but does not retrieve a chronological catalog checklist. Goal agreement therefore does not demonstrate useful graph behavior.
- **001:** the fresh seller explicitly requested evolution-line bundles and reached the class-saleability candidate/cohort plan. This preserves the seller format but does not yet compute popularity or recommend bundles from verified demand.

A separately frozen same-code recovery re-evaluates only the two initial error rows. It must never replace these first-run results or count as new unseen evidence.

### Separate same-code recovery

The [recovery report](sandbox/public_questions/v11/recovery_same_code/route_report.json) is separate from the first frozen diagnostic. One of two failed rows became schema-valid; the other still failed. These are known-case retry results, not new generalization evidence.

- **002:** now extracts as `seller_pricing` with no `net_proceeds` task, outside the pre-call alternatives. The required inventory/cost clarifications are absent. A one-channel question about minimum profitable selling prices needs explicit economic-task preservation, even without comparing channels. The current extraction wording is too tightly tied to channel comparisons.
- **016:** both recovery attempts again produced the buyer-transaction/seller-channel conflict. The repeated consistency rejection supports prioritizing separate planned buy and sell activities. Do not weaken the guard or invent paid acquisition costs to force a pass.

Full test suite: **330 tests passed**. The new tests check frozen-input integrity, retaining failed source calls and rejecting unsupported source verdicts. Passing those tests does not remove the two first-run extraction failures or prove answer quality.

### Next implementation sequence

1. Preserve this diagnostic. Represent a planned inventory purchase and planned resale as separate activities; preserve proposed prices separately from paid cost basis. The answer must still wait for exact-unit, condition, fee, shipping and settlement evidence.
2. Represent checklist/collection-completion and evolution-line composition as graph tasks distinct from selling formats. Preserve buying/deck-building requests without enabling seller actions. List catalog coverage and missing regions/releases rather than promising all printings or cameos.
3. Give clarifications explicit dependencies: game scope → inventory/unit/condition → costs/channel/period. Evaluate action sequencing instead of requiring every later question to be asked immediately.
4. Validate the two initial failures and the buyer/checklist cases in development, then freeze another version before collecting new posts. Add fresh explicit all-at-once selling, mixed-TCG and shipping-destination controls, which this cohort does not cover.

## Measurement limits

Researcher expectations were recorded before Gemini extraction. Some allow multiple plausible primary intents; agreement with those alternatives is not exact intent precision. Goal agreement, stated formats, specifically expected facts and missing action cases are measured separately. Cases without required-action expectations do not establish action completeness. A source-condensed question that omits an explicit Pokémon reference may correctly trigger game-scope clarification before later questions about costs or selling channels.

This run generates evidence plans only. It does not execute offer retrieval, quote a merchant, estimate net proceeds, evaluate copy photos, measure exact-printing accuracy or create new relationship edges. None of the forum prices or answers enter the live price index.

## Reproduce

```bash
python3 -m scripts.evaluate_question_routes_v11 \
  --frozen-dir sandbox/public_questions/v11 \
  --catalog-db catalog-index-rarity-v2.sqlite3 \
  --facts sandbox/public_questions/v11/gemini_facts.jsonl \
  --expectations sandbox/public_questions/v11/researcher_expectations.jsonl \
  --output /tmp/pokemon-v11-route-report.json
```

An exact hash match for the frozen catalog and code is required. The private cloud catalog remains on its existing deployed revision; this is sandbox evaluation work.

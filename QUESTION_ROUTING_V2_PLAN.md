# Question routing v2: identity facts before commerce claims

## Evidence from the frozen v5 cohort

V5's planner was pinned before fact extraction. On 11 new source-checked public questions, two independent AI reviewers agreed on all seven v1 facts for 2 and on the deterministic plan for 5. The disagreements concentrate in product scope (4), language scope (4), exact printing (2), physical copy (2), and focus (1). See [the immutable row-level report](sandbox/public_questions/v5/facts_report.json) and [both computed plans](sandbox/public_questions/v5/plan_trace.jsonl). This is a small convenience cohort and measures reviewer agreement only.

## New extraction contract

Keep object, task, and transaction context in separate fields:

| Field | Proposed values or representation | Reason |
| --- | --- | --- |
| `object_type` | `single_card`, `card_collection`, `sealed_tcg`, `non_tcg_card`, `unknown` | A return dispute still concerns a single card. |
| `primary_goal` | Identification, relationship, price, condition, grading, merchant, channel, platform rule, collection preference, or general explanation | One stated goal determines the first useful action. |
| `transaction_context` | `none`, `prospective_buy`, `owned`, `listed_for_sale`, `completed_purchase`, `seller_buyback` | Distinguishes an actual copy or listing from a category discussion. |
| `identity_tokens` | Explicit card name, set, collector number, language, finish, grade; each may be absent | Extract what is stated. Catalog resolution, not the model, decides if one printing is uniquely identified. |
| `media_state` | `available`, `referenced_not_collected`, `none` | A link or mention is never equivalent to having the actual image. |
| `language_mentions` | Explicit language codes plus `unspecified_foreign` when the text only says “overseas” | Avoid inferring English from an unspecified foreign-language comparison. |

The extractor should also give a short text span or reason for each nonempty field. A schema validator should reject unsupported values, contradictory identity facts, and claims of available media when the frozen input marks media unavailable. The catalog resolver should return `unique`, `multiple_candidates`, or `no_match`, with evidence IDs. Neither model confidence nor agreement may upgrade a relation edge to a verified printing match.

## Deterministic plan

1. Reject unsupported object types and request clarification when the object is unknown.
2. Give general education or preference guidance when possible, then request case-specific evidence.
3. Resolve card identity from extracted tokens. Keep broad name, set, number, language, finish and grade distinct. Never join prices from shared artwork alone.
4. For an actual copy, require supplied front/back photos before condition observations; no image review may guarantee a grade or authenticity.
5. For current buyer asks, require an authorized listing feed. For paid price, require verified settlement. For seller payout, require current authorized buyback quotes. For a return or authentication-policy claim, retrieve the current platform rule. For merchant reliability, use fulfilment outcomes.
6. Emit the action sequence with evidence references, blocked capabilities and explicit abstentions. No model may mark a feed or policy as available from its own prose.

## Current implementation

The [experimental v2 planner](pokemon_index/question_routing_v2.py) and internal `question-route-plan-v2` command implement the separated fields and conservative evidence gates. The command accepts a structured fact JSON file, an optional **independent** catalog-resolution JSON file (`status`, `candidate_ids`, `evidence_ref`), and explicitly available capabilities. A model cannot make a printing unique merely by filling set or number tokens; the planner accepts `unique` only when the separate resolution supplies one catalog ID and an evidence reference. The reviewed relationship graph is a further separate capability for a cross-printing relation claim. Seller buyback and buyer offers are different actions. The command generates a plan; it does not call any marketplace, inspect photos, or answer the question.

```bash
python3 -m pokemon_index question-route-plan-v2 facts-v2.json \
  --resolution catalog-resolution.json --capability internal_catalog
```

The [v2 tests](tests/test_question_routing_v2.py) cover marketplace disputes about a single card, generic seller signals, an owned copy without photos, foreign-language ambiguity, unique-printing evidence, seller payout, landed quotes, and every object/goal combination. They are synthetic engineering checks. No AI extractor is yet wired to v2, and v5 was evaluated only against the pinned v1 planner.

## Next evaluation gate

Freeze the v2 extraction schema, prompt and planner before collecting a new, nonoverlapping v6 source cohort. Report source-fidelity yield, model field agreement, plan agreement, and any actual target-agent replay separately by language and development/holdout split. No accuracy claim is supported until an independent adjudicator or observable evidence checks the route against the source question and available capabilities. Keep all rejected or disputed rows in the denominator.

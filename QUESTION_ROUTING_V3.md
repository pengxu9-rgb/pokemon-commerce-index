# Question routing v3: seller state and evidence provenance

V2 remains pinned to the [v6 source-checked cohort](sandbox/public_questions/v6/). V3 is a new, experimental contract. It changes fields that v6 showed were ambiguous; it does not change any v2 labels or scores.

## Fact contract

The [v3 planner](pokemon_index/question_routing_v3.py) keeps card object and primary goal separate. It adds:

- `observed_listing` for a third-party listing discussed without an expressed intent to buy; `listed_for_sale` is reserved for the user's own listing.
- `sold_pending_fulfillment` and `completed_sale` for the seller's transaction, apart from the buyer's `completed_purchase`.
- `seller_channel` for marketplace sale, store buyback or an explicit channel comparison. This is separate from ownership and transaction stage.
- `platform_refs` for named platforms or proxy services, distinct from `merchant_ref` for an identified seller or shop. Known platform names cannot be accepted as merchant identifiers.
- `identity_tokens.rarity` apart from `identity_tokens.finish`. Codes such as MUR, SAR and UR are rejected in the finish field.

The planner still requires a separate catalog resolution with one card ID and an evidence reference before treating a printing as unique. The v3 `catalog_query` includes rarity and finish, but neither token by itself proves an exact printing. A seller's marketplace payout calls for current fees and sale evidence; store buyback uses authorized buyback quotes. Comparing channels also requests current platform policy. These actions remain **blocked** until the corresponding capability is explicitly available.

Run the internal planner with a v3 facts JSON file:

```bash
python3 -m pokemon_index question-route-plan-v3 facts-v3.json \
  --resolution catalog-resolution.json --capability internal_catalog
```

The read-only catalog resolver can now supply that resolution directly from a local
snapshot:

```bash
python3 -m pokemon_index question-route-plan-v3 facts-v3.json \
  --catalog-db catalog-index.sqlite3 --capability internal_catalog
```

`--catalog-db` and `--resolution` are mutually exclusive. The output includes
`catalog_lookup`: normalized query tokens, a bounded candidate list, total matches,
the reason for the decision, and a SHA-256 reference to the query and matching row
evidence. This reference is a lookup trace, not a hash or freshness guarantee for
the entire database. A unique result requires one named card plus explicit language,
set, number and exactly one eligible catalog row; rarity must be supported by the
row when stated, and finish must match its recorded variant when stated. Missing
coordinates or excluded/unverified rows ask for printing details. Multiple variants
remain multiple candidates. A unique **catalog printing** still does not identify
the condition, authenticity or final price of a marketplace copy. The resolver does
not provide live offer or verified-sale capabilities.

## Extractor and error record

The [Gemini v3.3 extractor](scripts/vertex_public_question_facts_v3.py) asks for the exact structured facts, a short rationale and direct question-text spans for platforms, merchant, rarity and finish. The validator checks these spans against the blind question; a rarity span must exactly match its code, so `MUR` cannot support `UR`. Linked or mentioned photos remain unavailable. Every call records a prompt hash, model version and response hash. Failed attempts record the stage, safe validation code, finish reason and response hash without keeping raw model text. The checkpoint is bound to the frozen question, prompt and code hashes.

## Development replay, not a fresh evaluation

The [v6 replay directory](sandbox/public_questions/v6/v3_regression/) reuses the same 11 questions that exposed v2's gaps. The first v3 prompt yielded 9 valid outputs, v3.1 yielded 10, and v3.2 and v3.3 each yielded **11/11 valid JSON and schema outputs**. The [final replay report](sandbox/public_questions/v6/v3_regression/report.json) lists each extracted state and resulting action sequence. All three earlier attempts are retained alongside it; the v3.2 code snapshot is preserved with its report. These iterations were tuned against the same questions, so 11/11 is a **development validity check**, not a blind accuracy or generalization score. There is no independent v3 fact adjudication in this replay.

The replay demonstrates that v3 can encode a seller's sold-but-pending Mercari authentication, a third-party listing without invented purchase intent, MUR as rarity, and a seller comparing Mercari/Yahoo with store buyback. It also exposes a remaining buyer-channel gap: a general question about Japanese buying agents currently receives explanation but no structured destination or parcel-cost follow-up. This belongs in the next planner iteration rather than being silently treated as solved.

## Next evidence gate

Before reporting v3 route quality, collect new original questions with no v1–v6 source overlap, run the source-fidelity gate, freeze the v3 planner and extractor hashes, and obtain independent fact reviews. Compare field validity, plan agreement and actual answer evidence separately. The next product integration step is an evidence-backed catalog resolver that can return `unique`, `multiple_candidates` or `no_match`; current pricing and transaction conclusions still require authorized listing and sale data.

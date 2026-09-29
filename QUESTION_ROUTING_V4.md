# Question routing v4: trends and purchase timing

V4 adds two question goals to the [v3 routing contract](QUESTION_ROUTING_V3.md):
`price_trend` (whether or why prices changed) and `purchase_timing` (whether
to buy now or wait). It also recognizes `card_market_segment` when the user
asks about a class of cards rather than one printing. The v3 planner and its
frozen source-checked evaluation remain unchanged.

## Evidence plan

The [v4 planner](pokemon_index/question_routing_v4.py) first needs a specific,
eligible catalog printing. A name, translated alias, rarity or historical
forum quote cannot establish that printing. A question about a broad market
segment asks the user to define a comparable cohort. An unresolved printing
asks for release, language, number or card-face evidence before any price
series is retrieved.

For one resolved printing, the planner keeps four sources distinct:

| Evidence | Required for | Meaning |
| --- | --- | --- |
| Authorized historical asks | Trend | Dated listing prices for a comparable unit |
| Verified sale series | Trend | Dated actual transactions, separate from asks |
| Validated series coverage | Trend | Sample count, missed listings, time window and source mix |
| Authorized current offers | Buy or wait | Fresh actionable listings for the same unit |

The unit must preserve language, printing, grade, finish and relevant condition.
`purchase_timing` also asks for a decision horizon and buyer constraints such
as budget, target condition and risk tolerance. These are retrieval and
clarification actions. Even when all capability flags are present, the planner
does **not** produce a trend verdict, forecast or buy recommendation. A later
evidence-quality and decision layer must inspect the returned observations.
Old forum asks never become current prices or verified paid prices. The route
also guards against guaranteed future-price predictions.

Use a v4 facts JSON file with the read-only local catalog:

```bash
python3 -m pokemon_index question-route-plan-v4 facts-v4.json \
  --catalog-db catalog-index.sqlite3 --capability internal_catalog
```

The [Gemini v4 extractor](scripts/vertex_public_question_facts_v4.py) requires
direct question-text spans for the goal, time window and purchase constraints.
Its run command requires a *new* frozen cohort manifest with hashes of the v4
planner and extractor; it cannot run as a blind extraction against the v7
manifest, which pins v3.

## Development regression

The [v7 development replay](sandbox/public_questions/v7/v4_development/report.json)
reuses eight already viewed questions. Gemini 3.8 Flash produced 8/8
schema-valid records. It assigned `price_trend` to the historical auction
question (003) and broad Japanese/English market question (008), and
`purchase_timing` to the buy-or-wait question (005). The two first questions
ask for a printing or market scope, and 005 asks for printing details,
decision horizon and buyer constraints. No live offer or sale capability was
enabled, and no price claim was made. The report records the catalog result
and actions for every question. This is a regression check, **not** a blind
accuracy score or independent truth adjudication.

Next: freeze v4 on a newly sourced question cohort and separately audit goal,
object and evidence-span correctness. A live trend remains dependent on an
authorized feed with enough historical coverage; buy-or-wait needs that plus
fresh offers and the user's constraints.

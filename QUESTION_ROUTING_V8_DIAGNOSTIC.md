# Fresh v8 questions and the v5 response

The [v8 cohort](sandbox/public_questions/v8/) contains nine new public posts:
four Japanese and five English. Its URLs do not overlap v1–v7. Codex opened
the original posts and wrote short source contexts. Gemini 3.8 Flash checked
those contexts against the candidate questions, without opening the pages
itself. Both paths marked 9/9 paraphrases faithful. This is a source-fidelity
gate, not independent card or market truth. The [preflight report](sandbox/public_questions/v8/preflight/report.json)
retains every decision. The [manifest](sandbox/public_questions/v8/manifest.json)
froze the question text, v4 code and catalog snapshot before fact extraction.

## V4 result and observed gaps

The unchanged v4 Gemini extractor returned 9/9 schema-valid records. The
[route report](sandbox/public_questions/v8/route_report.json) has actions for
each question. No authorized offer or sale capability was enabled; no current
price or buy/sell recommendation was generated. The catalog resolver produced
zero unique printings, seven `not_attempted` and two `no_match` results. These
counts are about this convenience sample, not catalog recall.

Source inspection after the run found these important disagreements:

| ID | Original question | V4 route | Gap |
| --- | --- | --- | --- |
| 002 | Owner asks whether to sell a pulled card now or hold it | `price_trend` | Seller timing is distinct from buyer timing and a trend question. |
| 004 | Buyer first asks whether a quoted PSA 10 price is high | `price_trend` | A current-offer comparison is primary; future appreciation is secondary. |
| 005 | Why English releases command a premium over earlier Japanese releases | `price_trend` | A static relative-value explanation does not assert movement over time. |
| 009 | Which card to choose for a collection and budget | `collecting_preference` → `explain_general` | The route fails to request the missing pictured choices or preferences. |

These are post-run qualitative adjudications by the same researcher who
constructed the questions, **not** blind human labels or a percentage accuracy
estimate. Question 006 is an explicit buy-or-wait case and question 008 asks
about timing for several named cards; both remained `purchase_timing`.

## V5 implementation and development replay

The separate [v5 planner](pokemon_index/question_routing_v5.py) adds
`seller_timing` and `relative_value_explanation`, a seller-constraints field,
and a candidate-selection path for `collecting_preference`. It requires a
concrete time horizon instead of treating “今後” or “future” alone as one. Seller
timing asks about sale state, channel, horizon, constraints and copy condition;
seller proceeds require separate fee and buyback evidence. Relative-value
claims need a comparable cohort or reviewed printing counterpart, then dated
asks, verified sales and coverage. Card selection asks for the pictured choices
or usable preferences before retrieving catalog candidates. All market and
graph evidence actions remain blocked without explicit capabilities. The
planner still does not issue a trade or card recommendation.

The [v5 Gemini extractor](scripts/vertex_public_question_facts_v5.py) names
these boundaries in its prompt and requires direct spans for seller
constraints. On a [development replay of the already viewed v8 questions](sandbox/public_questions/v8/v5_development/report.json),
all nine records were schema-valid. It routed 002 to `seller_timing`, 004 to
`price_comparison`, and 005 to `relative_value_explanation`. Question 009 now
asks for the unavailable photographed choices. These changes show that the
implementation addresses the known examples; **v8 is not a fresh evaluation
of v5**.

## Next gates

Freeze a new source-checked cohort before evaluating v5. Separately, inspect
the two `no_match` catalog cases and any new-release coverage gap against an
authorized catalog source; do not turn a named but unresolved card into a
priceable unit. Live trend and transaction claims still require authorized
listing and sale data with measurable coverage.

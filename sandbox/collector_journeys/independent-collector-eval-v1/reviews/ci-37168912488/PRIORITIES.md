# First full-catalog collector evaluation: observed gaps

CI run: [37168912488](https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/37168912488)

This is an agent-reviewed diagnostic, not human collector testing. The reviewer also authored the frozen scenarios and is independent of implementation tuning, not a blinded second evaluator. Questions and expectations were not changed. Full evidence and case-by-case rubric judgments are in `agent-review-v1.json`.

## What executed

- Baseline `024a72d`: 28 completed case executions; two product-routing failures
- Current `7382318`: 13 completed case executions; 15 initial-prefix timeouts plus the same two product-routing failures
- All 30 cases remain in each denominator. Incomplete cases have null score axes; absent current answers are not replaced with baseline answers
- The 13 completed current cases have identical response content to baseline after removing revision identifiers
- Neither run reports an observed safety violation. This does not prove every intended safety scenario was reached
- The recorded 21 baseline / 12 current mechanical passes are not usefulness scores. No overall quality percentage is reported

## The two baseline errors are product failures

ICU-13 asks “Show me Japanese Pikachu 236/190 from Shiny Treasure ex.” The response contains zero candidates, `task=need_release_scope`, and asks which release accompanies the number. The already supplied release name was not understood. The subsequent separate selection is safely rejected because discovery never reached its expected state.

ICU-28 asks “Compare Japanese SV4A Mew ex 327/190 and 347/190.” It is routed to a one-number clarification rather than a comparison. `choose_comparison` correctly refuses because no active comparison exists; selection is never executed. The baseline parser requires a preceding language token for each number's segment, rather than understanding the question's shared Japanese/SV4A scope.

Both action sequences use valid schema. Neither error is a timeout or an evaluator malfunction. The runner's `execution_error` classification includes these failed product preconditions; it should not be read as proof of infrastructure failure. Preserve the failed receipts and frozen outcomes.

## Priority order

1. **Restore recommendation latency.** Fifteen current questions produce no answer before the configured ten-second prefix deadline. Fix and rerun unchanged cases before interpreting current recommendation quality; do not raise the deadline to make this run pass
2. **Honor all hard constraints.** ICU-04 requests Mew ex but shows five ordinary-Mew names, with no disclosed unmet suffix/illustration requirement. ICU-09 requests Pikachu AND Yuka Morii but returns source species 11, 574, 568, 568 and 57. These are semantic relevance failures, not missing market data
3. **Make ordinary release/comparison wording work.** ICU-10/13 lose “Shiny Treasure ex”; ICU-28 never enters comparison. ICU-29's stale-comparison rejection is a vacuous mechanical pass because no comparison was ever active. It supplies no evidence that changing preferences invalidates a live comparison
4. **Let relevant replies advance the task.** ICU-18 asks for an illustrator, then rejects “Yuka Morii” and stays empty. ICU-26 keeps a generic negative-preference hold after exact inventory is supplied. ICU-03 ignores the already supplied Japanese Charizard name
5. **Ask about the actual missing fact.** ICU-12 demands a single release code without explaining era versus release; ICU-15 asks again for language instead of flagging a possibly mistyped coordinate; ICU-30 exposes a hold but asks about exclusions/checklists instead of the underlying name/finish conflict
6. **Improve exploration and preserve constraints visibly.** ICU-11 uses five page slots for only two coordinates. ICU-23/25 do not acknowledge the unparsed $50 and £40/UK conditions in the next step. Typed EUR/DE/PSA10 preferences in ICU-24 are retained correctly, but remain an explicitly partial catalog result

## Useful behavior worth preserving

The baseline demonstrates an answerable novice-to-Pikachu continuation (ICU-01), source-backed illustrator matches (ICU-06/07/08), non-repeating pagination (ICU-19), idempotent likes (ICU-20), exact dismissal/undo (ICU-21), and artist refinement overriding earlier taste (ICU-22). The uncertain-inventory flow (ICU-27) exposes possible variants and holds selection without claiming verified ownership or a complete physical checklist.

Keep this evidence separate from physical printing accuracy, current offers, delivered prices, European shipping support and public/transaction readiness. None is established by these catalog responses.

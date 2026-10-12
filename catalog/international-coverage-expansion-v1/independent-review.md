# Independent review — GPT-6.1 Sol, high

Final outcome: no remaining actionable findings. The existing independent reviewer was reused; Astra was not used. Review was read-only and offline.

Two P2 audit findings were corrected and independently rechecked:

1. Independent full rebuilds regenerate four existing bookkeeping timestamp columns, not just relationship asserted_at. The audit now explicitly reports 19 identity-exception, two number-rule, 532 rarity-correction applied_at differences and 657 relationship asserted_at differences. Incremental history still compares every column exactly.
2. Searchable JSON and idempotence alone can mask a wrong SQL catalog_locale_evidence.card_id. The audit now verifies exact evidence IDs, stored card IDs, canonical JSON and six-field source mappings against the batch in both snapshots. Wrong stored-ID and missing-mapping regressions reject. Current data was correct before and after the audit fixes.

Independent verification:

- All 19 new stage7 tests passed.
- All 87 locale rows, selection/source inventory and copied licence reproduced from the exact authorized TCGdex pin; prior DB bytes stayed unchanged.
- Actual three-snapshot audit passed 87 target-ID checks, ten unfiltered searches, exact installation, all 51 historical table checks and idempotent reimport (unchanged 87, no quarantine).
- 87 target-ID gaps use 72 distinct query strings; 62 Japanese variants occupy 47 number groups, plus 25 English comparison IDs across SM and SV scopes.
- Full logs support 743 Python cases, 741 passes/two existing skips; 34 focused and 15 Node tests pass.
- Original 65-input ordered prefix, earlier 68-input prefix, existing IDs, all 65 holds, zero approvals and trading boundaries remain intact.
- Proposed next batch reproduces 25 Japanese and 25 English gaps from pinned sources, is disjoint from installed bindings, and is absent from the manifest. Unknown region, retrieval time, demand and offer supply stay explicit.

Final conclusion: the code, evidence, coverage report, backend handoff and next-batch plan are consistent. No identities, physical approvals, counterpart assertions or commerce/display rights are promoted.

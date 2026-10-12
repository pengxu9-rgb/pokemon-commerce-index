# Stage 3 verification — offline publisher captions

- Full Python suite: `python3 -m unittest discover -s tests` — 669 run, 667 passed, two existing skips, no failures (69.159 seconds).
- Node integration suite: `node --test integrations/pivota/*.test.cjs` — 15 passed, no failures/skips.
- Product-caption suite: 15 new regression checks included in the full suite. The earlier 14-test focused run passed; the independent reviewer separately passed those 14 and the added installation regression.
- `python3 -m compileall -q pokemon_index scripts tests` and staged/unstaged `git diff --check` — passed.
- Explicit 68-step snapshot build — all expected counts passed; original 65 source-binding inputs and preceding 67-step prefix preserved.
- Coverage audit — all 68 hashes verified; exact four installed canonical payloads/current events; four full-caption Japanese queries 0→1, exact bound IDs only and English excluded; 60 stage-1 translated searches and full v2 responses preserved.
- Incremental scratch append — inserted4, unchanged0, quarantined0; every pre-existing table/column unchanged, including rights, source mappings, references, release metadata, relationships, trading data, held candidates, quarantine and historical timestamps.
- Idempotent scratch re-import — inserted0, unchanged4, quarantined0; all pre-existing rows still exact.
- Before/after audited database file bytes unchanged. All 65 held candidates remain current; quarantine65; source records70,006; display and commerce approvals0.
- Four cached caption events recompiled after parser corrections — byte-identical to the hash-bound JSONL artifact.

The suite's local HTTP tests require localhost socket binding; automatic approval allowed that isolated offline test run. No external network, artwork download, price ingestion, frontend changes or cloud actions occurred. Independent rebuild differences are limited to four named existing generated timestamp columns documented in the coverage report; incremental append excludes none.

The initial sandbox-only focused run had one localhost bind error. It was rerun with permitted localhost binding and passed. Review-discovered empty/grafted/unbalanced anchors and nested plain list items were corrected and covered before the final full run.

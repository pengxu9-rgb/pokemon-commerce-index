# Independent review — stage 2

Reviewer: GPT-6.1 Sol (`gpt-6.1-sol`), high reasoning. Review reused the explicitly authorized independent-review agent and remained offline and local. Astra was not used.

Two actionable findings were corrected:

1. Baseline `attributes_json.test_only=True` could be counted as a current real-style held candidate despite the submitted row's `test_only=False`. Validation now rejects marked baseline records and marks historical events stale on such drift; selector and regression tests exercise this boundary.
2. The audit checked submitted rows against the after database without proving that the queue had actually been installed there. `verify_installed` now verifies exact current event/subject counts, exact stored IDs/card IDs/canonical payloads, and exact quarantine append/history. Missing-install and forged-quarantine regressions fail closed.

Final reviewer conclusion: **No remaining actionable findings.**

- All 13 qualification tests passed independently, including read-only HTTP, malformed inputs, test-only drift and audit installation checks.
- The actual database contains 65 current held events across SMH/DS/SC/LL, four cached page records and zero admissions.
- All 67 input hashes and the preserved 66-step prefix match. Incremental append preserves historical data; re-import adds nothing.
- Documentation distinguishes held evidence from identities, aliases, release facts, source mappings and permissions, and discloses four bounded generated timestamp exclusions.
- Recorded full-suite results confirm 654 Python tests with two existing skips and 15 passing Node tests.

This review does not validate physical printings, actual customer demand, authorized supplier supply or new rights. No artwork/marketplace acquisition, live ingestion, frontend changes or deployment occurred.

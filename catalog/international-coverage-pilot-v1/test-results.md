# Verification — 11 October 2026

Final complete Python suite: **641 tests run, 639 passed, 2 existing skips**, zero failures/errors (58.394 seconds). Node adapter suite: **15 passed**, zero failures/skips. Dedicated international suite: 15 tests, all passed with permitted localhost. `compileall` and `git diff --check` pass.

The initial unmodified baseline ran 626 tests: six existing HTTP tests failed because sandbox socket binding was denied; two tests were skipped. This limitation was resolved with local execution permission; it was not treated as a product failure. Original failed baseline log is included in the delivery bundle.

Coverage audit: all 66 SHA-256 bindings verified; the original ordered 65-step prefix is identical. Source rows, IDs, references and facets are unchanged. Incrementally adding the pilot preserves every original table/column. Independent rebuilds disclose 657 legacy generated relationship timestamps separately. Idempotent re-import: inserted=0, unchanged=60, quarantined=0. All 60 translated-name and 60 native-name target checks pass. Existing resolver results remain 59 unique and one ambiguous.

New regressions cover scoped/stale/withdrawn aliases, provider native-ID collisions, distinct regional release holds, malformed nested fields, missing names/dates, Unicode normalization, absent/wrong-language negatives, legacy EL and Ho-Oh retrieval, repeated numbers, shared artwork, promos, foil/stamp variants, Pocket/path traversal rejection, pinned synthetic third-language extraction, dirty source rejection, read-only HTTP bytes, and unchanged card/reference IDs.

GPT-6.1 Sol high independent review: no remaining actionable findings. This is local engineering verification, not physical-card certification, user recall, display licensing or live commerce validation.

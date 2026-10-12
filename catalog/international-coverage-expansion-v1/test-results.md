# Stage7 verification

- Full Python suite: 743 run, 741 passed, two existing skips; 41.122 seconds.
- Focused international suites: 34 passed, including 19 new stage7 tests; 3.651 seconds.
- Existing Node caller tests: 15 passed; 278.159 milliseconds.
- 87 exact target-ID retrieval checks (72 distinct translated queries):before missing, after found, native Japanese/English found, NFKC/fullwidth/decomposed Unicode found, wrong-language target excluded, resolver status/IDs unchanged.
- 10 additional unfiltered internal search checks passed.
- Source compiler reproduces locale, selection and licence files byte-identically.72 card files plus LICENSE match the existing reviewed TCGdex Git pin. No network fallback.
- Exact installed SQL evidence IDs, card IDs, canonical payloads and source tuples match the batch.
- Every historical column in all 51 tables is preserved in the incremental snapshot; only 87 locale and 87 source mapping rows append.
- Independent69-input rebuild matches all other records. Only four existing generated bookkeeping timestamp columns differ:identity exceptions 19,number rules 2,rarity corrections 532,relationship assertions 657.
- Reimport:inserted 0,unchanged 87,quarantined 0; all table contents unchanged.
- Original 65 ordered hash-bound inputs and prior 68-input prefix preserved; Dockerfile unchanged.

The initial focused run included one existing localhost socket test blocked by the default sandbox; the authorized localhost exception was used for successful final runs. Three initial fixture errors (a NOT NULL count, duplicate variant labels and a lock-protected test write) were corrected; the failed logs are retained. These were test-fixture issues. No final tests fail.

New regressions cover bounded/disjoint selection, ambiguous and withdrawn reviews, source-category disagreements, Pocket/digital exclusion, unknown region/missing date, source/license drift and late changes, idempotence/unchanged IDs, Unicode and variant siblings, source collisions, regional reuse, immutable output refusal, and exact stored SQL context/source mapping validation. Existing international tests cover shared artwork, promos, foil/stamps, repeated numbers and synthetic test-only French. Results are engineering checks, not user-demand, physical-card, listing, price or transaction accuracy.

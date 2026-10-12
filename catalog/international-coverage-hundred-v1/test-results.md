# Stage8 verification

- Full Python suite: 756 run, 754 passed, two existing skips; 42.484 seconds.
- Focused international suites: 47 passed, including 13 new hundred-level cases; 5.374 seconds.
- Node caller tests: 15 passed; 272.058 milliseconds.
- 125 exact target-ID checks (122 distinct translated query strings): before missing; after found; native/fullwidth/decomposed Unicode retrieval preserved; wrong language excluded; resolver statuses/IDs unchanged.
- Ten unfiltered internal queries pass.
- Reimport: inserted 0 / unchanged 125 / quarantined 0; all table contents preserved.
- All historical columns in 51 tables are preserved in the incremental candidate; only 125 locale and 125 source mapping rows append. Exact stored SQL evidence IDs/card IDs/canonical JSON and source tuples match.
- Independent 70-input rebuild matches all records outside four explicitly named existing generated timestamp columns: identity-exception applied_at 19, number-rule applied_at 2, rarity-correction applied_at 532, relationship asserted_at 657.
- New locale/selection/licence files reproduce byte-identically; prior-stage five-set outputs also reproduce byte-identically with generalized operator helpers.
- All original 65 and prior 69 ordered hash-bound inputs and expected counts remain unchanged. Dockerfile and runtime/schema/frontend are unchanged in this stage.
- Source pin/licence checks cover 122 card files plus LICENSE. No network fallback or new sources.

The first focused run had one synthetic overfull-fixture error because SQL integer booleans were passed to import_cards. The fixture now supplies explicit booleans. The failed log is retained; all final tests pass. No production data changed for this correction.

New tests cover exact hundred/set scopes, immutable profiles, invalid or unvalidated scopes, overfull/short/missing sets, missing English comparisons, duplicate IDs, repository-relative audit paths, pinned source bindings, false permissions, input drift, exclusive outputs, idempotence, exact history and unchanged legacy defaults. Earlier tests cover Unicode, localized metadata, source collisions, unknown regions, foil/stamps/promos, shared artwork, repeated numbers, missing fields and synthetic test-only French. These results are engineering checks, not physical-copy, real-user, market or transaction accuracy.

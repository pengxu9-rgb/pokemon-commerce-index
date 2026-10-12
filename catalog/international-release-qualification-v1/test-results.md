# Stage-2 qualification validation

- Full Python suite: 654 run, 652 pass, two existing skips, zero failures/errors (40.805 seconds).
- Focused qualification/international/release suite: 33 pass, including 13 qualification tests and read-only localhost CLI/HTTP checks.
- Node integration suite: 15 pass, zero failures/skips.
- 67-step offline snapshot build passes all expected inventory/evidence counts.
- 67 hashes verified; exact ordered 65-step source-binding and 66-step stage-1 prefixes preserved.
- 65 exact installed held payloads and appended quarantine payloads/history verified; zero admitted identities or release facts.
- All 65 native searches preserve target IDs; explicit English filters exclude Japanese targets.
- Re-import: inserted=0, unchanged=65, rejected=0; quarantine count remains 65.
- Incremental append preserves every historical catalogue/trading row/column, including original timestamps.
- Independent rebuild comparisons exclude only generated timestamps on four named tables: 657 asserted_at, 19 + 532 + 2 applied_at differences. All other old data match.
- Strict malformed/missing field, provider namespace, wrong coordinate, test-only drift, stale sibling/reference/release, shared artwork, promo/stamp and permission negatives pass.
- Audit regression rejects an uninstalled batch and forged quarantine evidence in the actual after snapshot.

Initial sandbox-only HTTP attempts could not bind localhost. Permitted offline reruns passed. Synthetic compiler fixtures are confined to tests; no synthetic record is in the real queue or manifest.

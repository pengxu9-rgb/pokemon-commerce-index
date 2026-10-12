# Stage 4 validation — read-only release-readiness planner

- Full Python suite: 685 run, 683 passed, two existing skips, zero failures/errors (45.424 seconds).
- New readiness suite: 16 passed; independent reviewer also passed all 16.
- Stage3 Node integration results carry forward: 15 passed. No Node/runtime change in this stage; no repeat Node run required.
- Real planner build and same-time recompilation produce byte-identical JSON; independent reviewer separately reproduced every byte.
- All 68 snapshot-input hashes, original 65 ordered inputs and prior 67-step prefix verified. Manifest remains 68 steps; no new operation/input/table.
- All 151 manifest/input/receipt/HTML file signatures plus receipt inventory remain unchanged. Input database SHA/bytes unchanged.
- Fixed installed queue: 65 exact held subjects; four publisher-caption priorities; 61 remaining. Request groups: 61 exact card pages+four product documents, with native IDs and individual coordinate/fragment bindings retained.
- Missing/partial date and physical-region evidence remains null; related SMH family document cannot substitute for the exact caption target or infer a year from campaign URLs. Price/copy text is excluded.
- Namespace, cached-hash/redirect/collision/path escape, source/reference drift, foil/stamp siblings, repeated numbers, foreign language, uninstalled evidence, forged permissions, concurrent input changes and output overwrite negatives pass.
- All pre-existing runtime data remains unchanged, including quarantine 65, held 65, source records 70,006, localized bindings 60, publisher-caption events 4, display/commerce approvals 0.
- Compilation and staged/unstaged Git whitespace checks pass.

Independent review found and corrected a draft input-integrity issue: hashing before a later parse could allow changed bytes into a report. Same-read parsing/hashing, exact observed-SMH hash checking and completion-time input/inventory rechecks close it. Mutation regressions pass. Existing localhost HTTP tests ran with automatic approval for the isolated offline suite; no external network or live systems were used.

# Stage17 before-only gap baseline

The frozen pilot contains **89 Japanese and 25 English existing IDs**. This read-only baseline used pilot code `f0c20e25f2f736fbad04280e820b1ad5b8ecefdb` and unchanged expanded snapshot `5289fb3167fe193257e4d58e715f9600a8f585443fdb9c61563aecd8c80f86cf`. The database still has 2,282 locale bindings and zero of the 25 new Johto concepts; their independent semantic approval is external evidence, not a database import.

| Before-only check | Japanese | English |
| --- | ---: | ---: |
| Exact translated catalog search finds target | 0/89 | 0/25 |
| Native-name catalog search finds target | 89/89 | 25/25 |
| Native Unicode catalog search finds target | 89/89 | 25/25 |
| Broad discovery translated query finds target | 89/89 | 21/25 |
| Discovery native Unicode query finds target | 89/89 | 21/25 |

Structured translated lookup remained `not_attempted`: 17 old Kanto residual records require exact reviewed-name record bindings, while the 72 new Japanese and 25 English records lack installed cross-language concepts. Native structured queries retained all target identities and existing multiple-candidate clarification. The 25 English comparison records each lack their exact Japanese-name catalog search binding. Unicode equivalents preserve the same observed results, and wrong-language constraints exclude every target.

Four English discovery queries remain blocked by an existing dotted-set-code parsing defect: SM3.5 Totodile018, Croconaw019, Feraligatr020 and Raikou032 (all `/073`). The default parser detects both `SM3` and `SM3.5` and asks for release scope, for translated and native Unicode queries alike. Explicit language/set/number/variant scopes return each original exact ID in eight read-only controls. This is a separate backend parser issue; locale imports alone will not fix it. No parser change was made by this audit.

Broad discovery already searches native card names and singleton Dex facets across languages. Its coordinate branch can therefore return these records before translation binding. That success does not mean the exact translated catalog query or source-bound structured resolver already works, and it grants no printing, physical-copy, counterpart, display or market authority. The baseline records both paths separately; it makes no blanket claim that these records are globally missing.

All 114 future provider mapping keys are disjoint from current mappings, all 52 Japanese eligible coordinate groups are complete, and no priority image group, held identity or previously bound ID is selected. All 44 holds remain current; five priority media states and empty market tables are preserved. No import, database/source mutation, image acquisition, network request, frontend change, deployment, push or trading action occurred.

The frozen source pool's eight leftover records are **outside the 25 approved pairs**: Hoppip, Skiploom, Jumpluff, Shuckle, Tyrogue, Cleffa, Slugma and Magcargo. There are zero remaining records under these same 25 names within that 80-record fixed pool. Each of the eight needs a separate exact-name semantic review. A preliminary SQL projection in S10A, S11A and SV9A finds 2 rows with the current 25 exact names; none was source-qualified or imported here. It requires pinned source/variant/release checks and measured gaps before another batch. The existing SV4A correction remains preserved; original HTML was not reverified.

[Machine-readable baseline](/Users/pengchydan/Documents/Codex/2026-10-11/implement-a-staged-international-pok-mon/work/stage17-gap-readiness.json) stores each exact ID/query/result, native/Unicode results, resolver reasons, source hashes, code/DB signatures, mapping/group checks and future exclusions. Confidence describes deterministic local observations, not real-user accuracy or physical verification. Demand and live Buy&Ship supply remain unmeasured; metadata licensing grants no artwork/display rights. Buy&Ship remains intended MoR, and Pivota holds no customer funds.

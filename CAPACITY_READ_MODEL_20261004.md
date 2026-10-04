# Bounded catalog read model: local capacity continuation

## Status and scope

This follows the independently reviewed concurrency/recovery repair published as
`65a8b15f43c73aeac8ea344900e6b2bf78066388` (CI run `37192941078`).
It optimizes successful catalog computation. It does not change the Node client's
10-second attempt deadline or two-attempt limit, Python's one worker / four
waiters / 250ms queue wait / eight-second work budget, or Cloud Run's reviewed
1 CPU / 512MiB / concurrency 16 / max instances 1 / 30-second request limit.
No Cloud deployment, normal-traffic change, resource tuning, ingestion, display,
printing approval, offer joining or transaction capability is part of this change.

The original Cloud incident's root cause remains unproven. Eight sampled 503
logs could not be correlated to the 32 possible caller attempts. Local baseline
reproduction did not produce the historical Cloud recovery timeout. The published
65a8 per-attempt request IDs, timing/status diagnostics and server delivery logs
are required for the remaining private, zero-normal-traffic Cloud comparison.
See `PRIVATE_STAGING_ROLLOUT.md` and `CONCURRENCY_RECOVERY_20261004.md`.

The capacity implementation was published as `2244f91ed5df44f380ac07dc09d5f7237b7f1fa6`.
Its exact-SHA CI passed, but a fresh post-publication review requested a schema
compatibility correction. The follow-up below is a separate, locally tested
candidate; 2244 CI and prior review do not approve these changed bytes.

## Evidence-based local bottleneck

The 70,006-record CI catalog repeatedly evaluates the effective facet view and
rebuilds fixed parser vocabulary and source-pinned affiliation proofs for each
fresh request. A single-CPU profile of the original 20-turn Ken Sugimori workload
attributed about 1.12 of 1.98 profiled seconds to SQLite execution, including
repeated effective-view work. Fixed vocabulary construction and affiliation
validation accounted for substantial overlapping portions of that profile.
These are local measurements, not an attribution of Cloud admission behavior.

An indexed, immutable image of the **existing effective** facet relation removes
repeated view evaluation. It does not copy raw facets in place of corrections or
manufacture new source facts. Both indexes are necessary: an unindexed diagnostic
copy exceeded the existing eight-second budget on representative requests.

## Implementation and integrity boundaries

- The internal HTTP server calculates its runtime/catalog revision, checks the
  unchanged catalog file identity, and prepares a bounded read model before
  accepting requests. Initialization time and memory are measured separately.
- The image contains only effective facets and two indexes. Its values, SQLite
  storage types, duplicate counts and declared column affinities match the canonical
  effective relation. That does not establish arbitrary SQL comparison equivalence
  for SQLite compound views. Only explicit, audited string equality/IN and
  explicit CAST lookup sites use the image; the generic view is never shadowed.
  The canonical database remains opened with `mode=ro`.
- SQLite's image page quota is 64MiB. The measured image is 35,655,680 bytes.
  Three fixed vocabularies are immutable tuples; affiliation proofs are retained
  as bounded JSON and decoded into a new object for each request. No user query,
  session, feedback, inventory, ranking, selected target or response is shared.
- Every admitted request gets a **fresh SQLite connection and fresh attached
  image clone**, with `query_only=ON`. There is no shared mutable SQLite
  connection. The roughly 14ms local clone is inside the existing work deadline;
  it does not obtain a fresh budget. Closing the request connection releases it.
- Resolved database path and file/WAL identity are checked before and after
  preparation and request use. Ordinary replacement or mutation fails closed
  and requires restart/reconfirmation. This is the existing immutable-snapshot
  model, not adversarial filesystem attestation.
- Character-mention memoization is bounded to 64 immutable results within one
  replay. Main/temp schema changes, local/external writes and transactions retain
  the direct caller's invalidation behavior. Parser matches never cross requests.
  Ad-hoc direct vocabulary lookups retain at most three entries.
- The entire stored main schema and database encoding must exactly match a fresh
  schema created by this package. Altered collations, intermediate views, indexes,
  types or encoding disable acceleration. Older supported catalog shapes or a
  Python SQLite build without image methods retain the original native server path. Other preparation errors,
  memory-quota failures and deadlines are not silently swallowed. The Docker CI
  smoke explicitly requires successful read-model construction and exact replay
  equivalence inside the built production image.

The real catalog's typed multiset and affinities were compared in both directions
for all 86,512 effective facet rows. Python 3.12 / SQLite 3.53.1 and Python 3.13 /
SQLite 3.46.1 diagnostic checks agree. Production-image compatibility still needs
its exact-SHA Docker CI check; local versions alone are insufficient.

## Original pre-publication measurements at unchanged limits

All measurements below are local, single-CPU-pinned, actual production Node
caller → Python HTTP unless marked direct. OS caches were not flushed. A busy
rejection remains unsuccessful work in every denominator.

| Profile | 65a8 baseline | Read-model candidate |
|---|---:|---:|
| Existing strict 58-request profile: completed | 22/58 | 34/58 |
| Existing strict profile: explicit busy | 35 | 23 |
| Existing strict profile: intentional cancellation / timeouts | 1 / 0 | 1 / 0 |
| Existing profile: 16-way burst completions | 1/16 | 2/16 |
| Existing profile: sustained 4-way completions | 4/16 | 11/16 |
| Distinct-session 97-request profile: completed | 52/97 | 71/97 |
| Distinct-session profile: explicit busy | 44 | 25 |
| Distinct-session profile: intentional cancellation / timeouts | 1 / 0 | 1 / 0 |
| Distinct-session 2 / 4 / 16-way burst completions | 1 / 1 / 1 | 2 / 2 / 3 |
| Distinct-session sustained 4-way completions | 8/32 | 22/32 |

The mixed profile uses 16 different valid 20-turn transcripts, not identical-call
coalescing. It covers illustrators, species, EN/JA language, preference changes,
feedback dismissal/restoration, ownership ambiguity/resolution, and comparison →
exact focus → separately selected target. Every completed response matches its
frozen baseline semantic hash after removing **only** `catalog_revision` and
`expected_revision`. It includes 16 post-load isolation replays, burst/sustained
recovery and cancellation recovery. The paired 58-request baseline was rerun on the same local catalog and CPU
selection. Both mixed baseline and final runtime measurements were repeated. Clean portable-harness measurements are recorded separately;
never relabel an earlier receipt as a later harness run.

The post-review schema/workload-bound pair measured Python peak 62.46 → 155.67MiB
and sampled simultaneous Python-plus-Node peak 129.73 → 227.17MiB. Fresh server
preparation was 1.177 → 2.007 seconds after read-only identity inspection. Serial
successful p95 was 2.504 → 0.555 seconds; sustained successful p95 was
3.417 → 1.980 seconds. The local interpreter was Python 3.12.14 / SQLite 3.53.1.
The reference caller is outside the collector process; these combined local
measurements are not Cloud Run container telemetry, and 50ms RSS sampling can
miss brief peaks.

Earlier candidate repetitions completed 72–73/97 overall and 23–24/32 sustained,
with 2–3/16 burst completions. The final post-review pair completed 71/97 and
22/32 sustained, with 3/16 burst completions. Retain this scheduling variation. These results do
not establish successful 16-user burst capacity: 13 of 16 burst requests were
still explicitly rejected in the final pair. Load-only successful work improved
from 11/54 to 29/54; overall denominators also include serial and recovery checks.

The portable profile and logical-evidence binding are described in
`COLLECTOR_MIXED_CAPACITY.md`. Run the same shipped harness against each source
root, use a fresh process and available single CPU, keep both receipts/journals,
and verify that source, workload, evidence, policy and harness identities match.

## Regression and evidence limits

- 18 new cache/read-model tests include full 42-prefix fixture equivalence,
  concurrent distinct sessions, immutable/detached facts, source path/mutation
  guards, clone isolation, readonly enforcement, quota/deadline cleanup,
  transaction/schema invalidation, bounded retention and legacy fallback
- 29 new mixed/evidence harness tests and the unchanged 18 strict-journal tests
  pass, including actual HTTP smoke, partial receipts, callback isolation and
  logical evidence/byte-bookkeeping distinction
- 41 Node tests, 42 recommendation HTTP/Node prefixes and 39 legacy prefixes pass
- All 60 original uploaded Cloud-check assertions and all 60 historical response
  rows match in local HTTP/Node replay after removing only revision fields
- Stale sessions return `catalog_changed` with null result/session/target; a fresh
  start is unselected, and a separate explicit reconfirmation selects the target
- The final runtime's strict caller receipt accounts for all 58 requests and
  preserves its durable attempt journal, bounded retries and recovery checks
- Before mixed-harness integration, the partial checkout ran 847 Python tests
  with the same 12 missing-input
  errors as baseline's 829, two skips and no assertion failures. This is not a
  full aggregate pass. The unchanged frozen 30-case evaluation also stops at its
  input preflight with `blocked_incomplete_catalog_inputs`; it was not executed
  for this local candidate. The complete pinned build, full test aggregate, Docker
  smoke and exact published-SHA CI remain mandatory

The exact CI database used locally is 148,275,200 bytes, SHA-256
`2ee7448b7e42ab9fe7e423a6769b01c18f260b503f3cb6d633802c5b2300549b`.
Equivalent manifest rebuilds can have different bookkeeping bytes. Keep actual
before/after byte hashes in every receipt, and use only explicitly reviewed
logical-evidence normalization when comparing equivalent rebuilds. Do not replace
missing source fixtures with this database or relax a frozen input preflight.

The earlier 65a8 CI's frozen current evaluation passed 30 mechanical cases; this
was not a usefulness score or real-user test. Its deliberately non-gating 024a72d
historical baseline had two execution errors and nine mechanical failures.
Neither fact changes because of this capacity investigation.

## Independent-review hardening

Two demonstrated benchmark-integrity findings were repaired before publication:

1. The first logical-evidence digest did not bind table collations or all stored
   schema. An integrity-valid copy with a case-insensitive card-ID column could
   hash alike while changing lookup results. Version2 additionally binds all
   stored main-schema objects, encoding, application ID and user version. The
   changed-schema witness now has a different digest. Actual before/after database
   byte hashes remain mandatory, and only the two reviewed evidence-field
   timestamp normalizations remain allowed.
2. The first driver hashed the workload file only at the end. It now hashes the
   bounded bytes actually consumed at startup and requires the final file hash to
   match. Changed or missing input fails the receipt while retaining consumed-input
   identity and the durable journal. Actual HTTP mutation/deletion tests cover it.

The original frozen candidate and all earlier measurements are retained rather
than relabelled. The numeric mixed table above is the fresh matched run after
both fixes. A separate six-call actual Node/HTTP supplement covers a 20-turn
artist-plus-excluded-species session and a 20-turn changing-question/scope session:
baseline five completions/one busy versus candidate six completions, no timeouts,
with exact frozen semantics and successful recovery. Only its replaced payloads,
explicit supplement labels, hashes and actual outcomes constitute that supplement;
inherited descriptive metadata from its source fixture is not extra coverage.

## Remaining operator gate and separate tuning proposal

Before private Cloud verification, reinspect the exact project, service, private
target revision/image, IAM and traffic state. Bind reviewed source → source build
→ immutable image digest → zero-normal-traffic revision; stop on disagreement.
Keep the live/rollback revision untouched. Run the same fixed workloads and
original 60 assertions with the exact reviewed Node client, preserving sanitized
attempt IDs/status/body-stage deadlines and matching Python delivery events.
Successful `/health` or an anonymous 403 is not recommendation recovery evidence.
The actual deployed Pivota caller target is still unknown; an operator harness
pass would establish compatibility, not deployment of that caller.

Only after that unchanged-limit comparison should a **separate reviewed local
and private-revision experiment** consider queue wait/length or retry jitter.
Larger queues can trade fast rejection for head-of-line latency and lingering
cancelled work; a 16-way burst cannot be declared solved by hiding rejections or
extending deadlines. Measure completion denominators, successful p95/p99,
per-attempt error classes, memory and post-burst recovery before proposing a
setting change. No such tuning or resource change is applied here.


## Post-publication compatibility correction

The fresh review of published 2244 demonstrated a real two-turn replay mismatch
on a same-shaped effective view using `COLLATE NOCASE`: native preferred-artist
validation accepted lowercase `alpha`, while the image rejected it. The pinned
70,006-record catalog did not reproduce that user-path defect. The reviewer also
found that numeric inequalities against the canonical compound view can differ
from a materialized table despite identical stored values and declared affinities;
no production numeric-inequality caller was identified. Both findings limit the
original generic-view replacement, rather than justify broader SQL equivalence.

This follow-up removes the temporary `discovery_card_facet` alias entirely.
Generic SQL retains the original view. Fifteen audited production lookup sites
explicitly select the image only on the bound request connection, with typed
string equality/IN or explicit CAST operations. Construction checks all stored
main-schema definitions and encoding against a newly initialized package schema;
noncanonical catalogs fall back to native execution before an image is built.
Fixed vocabulary and affiliation preparation now read the native relation too.

The partial-journal reporting correction is independent: every started case now
carries its planned request count from the Python-owned execution plan. A case
interrupted after one completion and one unsettled call out of sixteen reports
1/16, with fourteen not started, rather than 1/2. Global strict pass/fail was
already correct; complete earlier receipts are unchanged. Eleven new tests cover
partial/zero-start cases, invalid counts, a real interrupted Node stream and
per-case producer overflow. The parser rejects an overfull case before mutating
its observations, retaining the earlier rows, global planned denominator, durable
partial marker and serializable structured receipt. This last guard closes a
separate nonblocking malformed-producer finding from the follow-up review.

### Fresh follow-up evidence

Same final harness, catalog, workload and single CPU; limits remain unchanged:

| Profile | 65a8 baseline | Narrowed follow-up |
|---|---:|---:|
| Mixed completed / planned | 52/97 | 73/97 |
| Explicit busy / intentional cancel / timeout | 44 / 1 / 0 | 23 / 1 / 0 |
| Load-only completed / planned | 11/54 | 31/54 |
| 2 / 4 / 16-way burst completions | 1 / 1 / 1 | 2 / 2 / 3 |
| Sustained 4-way completions | 8/32 | 24/32 |
| Fresh server preparation, seconds | 1.218 | 3.058 |
| Python peak RSS, MiB | 57.43 | 159.21 |
| Sampled simultaneous Python + Node peak, MiB | 125.57 | 236.02 |

These results retain scheduling variation. Published 2244's earlier matched local
pair was 71/97, and its complete CI mixed run was 69/97 (27/54 load, 2/16 burst).
Do not relabel those receipts. The follow-up's cold preparation is slower than
2244's roughly two-second local preparation because fixed facts use native SQL.
That startup trade-off still needs production-image and private Cloud cold-start
measurement. Thirteen of sixteen burst calls remain rejected; this is not a
16-user successful-capacity guarantee or approval to promote normal traffic.

The fresh strict caller profile completed 35/58, with 22 explicit busy responses,
one intentional cancellation, zero timeouts and all diagnostics/recovery checks.
All sixteen frozen semantic/session checks, 36 generic real-catalog SQL comparisons,
42 recommendation prefixes, 39 legacy prefixes and all 60 original historical
Cloud-check assertions pass locally. Historical response rows are equal after
removing only revision fields; stale restart still clears result/session/target,
starts unselected and requires separate explicit reconfirmation. The read-model
suite now has 22 tests, including the actual HTTP collation witness, generic SQL,
extra schema objects and UTF-16 fallback. The complete local checkout is still
missing original large inputs; the aggregate is not claimed to pass locally.

Published 2244 CI run `37199454729` reported **901 tests run: 899 passed, two
skipped**, plus 41 Node tests, 42 recommendation and 39 legacy prefixes. The
current frozen evaluation passed 30 mechanical cases with zero execution errors;
this is not usefulness scoring. The historical non-gating baseline retained two
execution errors and nine mechanical failures. The production-image smoke ran
Python 3.12.15 / SQLite 3.46.1 successfully. Those results bind published 2244,
not this follow-up; new independent review and exact-SHA full CI remain required.

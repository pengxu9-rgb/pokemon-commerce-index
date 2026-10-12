# Collector overload and recovery repair

## Scope and evidence boundary

Baseline source is `7871244b3627d7677a2686eaecf21df73865a8d8`.
The operator reported the private Cloud Run candidate `00044-vax` at zero normal
traffic, with `00043-2x6` retaining all normal traffic. Its 70,006-record catalog,
Ken Sugimori axis of 2,684 records, and valid 20-turn recommendation transcript
took 6.19 seconds serially. A 16-caller burst reportedly completed once, timed
out 15 times, and a subsequent recommendation recovery call timed out at 20.21
seconds. Eight available request-log entries reportedly showed 503 responses
around 0.25 seconds.

Those cloud observations are **not yet a proven root cause**. The supplied
[private draft evidence bundle](https://github.com/pengxu9-rgb/pokemon-commerce-index/releases/tag/untagged-87d69dc2d99f49344446)
was materialized and its ZIP SHA-256
`99ce04f30edbbd9e922adb07d3e0fcf60177435ddfe31dfb93eb0a946a6847c8`
and all 46 original file byte counts/hashes were verified. These are historical
receipts, not a fresh cloud-state inspection. The authorized deployment session
remains unavailable here. In particular, a server-side 503 log does not establish when a
Node caller received headers, completed the body, or settled cleanup. Neither
health 200 nor anonymous 403 proves recommendation recovery.

The original load script acquires one token before launching Node, then uses one
shared client/session for serial 1, burst 16, recovery 1. Token minting latency is
therefore outside the reported attempt timings. Eight burst failures took
12.14–13.40 seconds and seven took about 20.21 seconds. That is consistent with
eight early first-attempt rejections followed by retry timeouts and seven pairs
of timeouts, but the missing per-attempt traces prevent assigning those eight
server log entries to particular calls or proving where retries stalled.
All reported logical calls did eventually terminate; they are not evidence of
the indefinite mock-provider hangs reproduced below.

The actual Pivota Node deployment target is also unknown. Changes to the Node
connector here establish source/operator compatibility, not rollout to that
caller. No cloud traffic, deployment, resource, IAM, service-identity, credential,
or catalog-input change is part of this patch.

## Reproduced defects and repair

### Client attempt lifetime

Previously, the abort timer independently raced token acquisition only. Fetch,
body reads, and awaited `response.body.cancel()` / `reader.cancel()` relied on
dependencies honoring AbortSignal. Four controlled baseline cases with a
50 ms attempt budget were still pending after 250 ms: ignored fetch abort,
stalled body read, stalled response cancellation, and stalled reader cancellation.
This proves a local boundedness defect; it does not establish that one of those
dependencies behaved that way in the reported Cloud Run incident.

One independent watchdog now covers token lookup, fetch, body read and result
validation. Cancellation is best-effort and never awaited on the result path.
Late token/fetch/body continuations cannot accept a result or start another
stage after their attempt expires. A caller AbortSignal stops active work and
retry sleep without mutating the input session. An exhausted request cannot
partially commit an extra turn or establish a catalog target.

Independent review additionally identified a native reader-lock leak when its
underlying cancellation promise never settled, and mutable/throwing dependency
error accessors that could bypass error sanitization. Reader-lock release now
runs independently of cancellation settlement, including synchronous cancel
failure. Error fields are captured once inside a defensive boundary, including
prototype/accessor failure, then reconstructed from the fixed allowlist. Native
stream and hostile-accessor regressions cover both findings.

The defaults remain **10 seconds per attempt and at most two attempts**. The
normal 200 ms retry delay and bounded busy Retry-After handling, at most one
second, are retained. Explicit work-budget and snapshot-change responses remain
non-retryable. A timer is not hard preemption of synchronous JavaScript or an
uncooperative external provider; checkpoints reject a late result, and cleanup
requests are not proof that remote computation has stopped.

### Server work lifetime

The existing one-worker, four-waiter FIFO, 250 ms queue limit and eight-second
work limit remain. The eight-second budget now also covers request-body reading
and parsing, plus queue admission; a slow body cannot obtain a fresh work budget
after its original budget has expired. It starts after HTTP headers are parsed,
so an idle pooled TCP socket does not spend a future request's compute budget.
Headers have a separate ten-second inactivity timeout.

The SQL progress deadline is also a request-local Python budget. Checkpoints at
nested catalog entry/exit, parser vocabulary loops, journey turns, facet batches
and ranking rounds stop cooperative Python work before another stage starts.
Nested SQL guards restore the previous callback and every exception restores
the ContextVars. These are cooperative checks, not a hard process kill or a
claim that arbitrary blocking extensions can be preempted.

Admission is released before response delivery. A slow or disconnected reader
cannot retain the compute slot. Socket response delivery retains the existing
ten-second inactivity limit. Read-only catalog connections, snapshot-change
rejection, per-request vocabulary/ranking state and all commerce authority gates
are preserved. Source changes alter the catalog/runtime revision, so old caller
sessions still require an explicit restart and target reconfirmation.

## Safe diagnostics

`createCollectorClient({onAttempt})` optionally receives one bounded allowlisted
record per attempt: stage, durations, HTTP status, connector-owned error class,
retry decision, abort/cleanup state, validated generated request ID, and fixed
numeric server timings. It contains no token, URL, raw header/error, question,
body, session or target. Observer failure cannot change the result, and a
pending observer promise is not awaited. The observer must itself avoid blocking
the JavaScript event loop.

The Python response supplies a generated `X-Collector-Request-ID` and
`Server-Timing` values for body/parse receive, admission queue, and compute.
Sanitized `collector_http` stderr records contain the same ID, route enum,
status/error class, byte count, durations and socket-delivery result. A
`delivery=complete` record means the socket write returned, not that the client
consumed or validated the response. Incoming paths, query strings, credentials,
payloads, exception messages and sessions are not logged.

These timings start inside the application. They do not measure Cloud Run's
upstream admission/queueing or establish why a request never reached Python.
Correlate individual caller attempts with generated response IDs and platform
request logs before claiming an actual-cloud root cause.

## Acceptance boundaries

An explicit busy rejection is unsuccessful work, even when it is fast. This
repair does not turn one CPU/one compute worker into capacity for sixteen
simultaneous successful recommendations. Completion, rejection, timeout and
recovery must be reported separately with every request in the denominator.

The new actual-Node/HTTP benchmark saves exact 20-turn workloads and source and
catalog fingerprints. It includes serial controls, concurrency 2/4/16, sustained
load, recommendation recovery, cancellation, deterministic replay and separate
caller-session checks. The existing direct-HTTP and runtime benchmarks remain.

Run in a fresh process against an existing built read-only snapshot:

```sh
python -m scripts.benchmark_collector_caller --db /path/to/catalog.sqlite3 \
  --fixture-label real_pinned_catalog --require-current-client \
  --output /tmp/caller-recovery-receipt.json
```

Use `--repo-root` and explicit `--allow-legacy-client` for an independently
fingerprinted older baseline checkout, and keep
the same catalog and CPU affinity for the comparison. Never label the synthetic
fixture as a real catalog. CI retains the full receipt alongside its existing
diagnostics, under an outer 300-second harness watchdog; that outer watchdog
does not expand any individual attempt budget.

The current-client gate requires native per-attempt diagnostics and an exercised
cancellation scenario. Missing callbacks cannot silently turn the candidate into
a legacy baseline run or pass through empty-array timing checks. A bounded,
incremental sanitized journal preserves attempt stages and settled results while
work is still running. An inner watchdog shorter than CI's outer watchdog writes
a failed partial receipt with planned, started, settled, unsettled and not-started
counts. This avoids losing earlier observations when a later call hangs. These
two regression/evidence gaps were identified and closed during independent review.

Local affinity and peak RSS are diagnostics, not Cloud Run CPU/memory guarantees.
The available read-only database is 148,275,200 bytes, SHA-256
`d1118b9241e014b56455ff93228bb52d208a5856aac49eaa6489d6f7e045b4f9`.
It has the same logical input catalog as the baseline, but is not byte-identical
to the reported final baseline build hash
`c0294f93b42b1f84a6934b3cd8c043b5120fda291f788f97b9dcd1264891891f`.
The baseline evidence/runtime revision computed from these local bytes is
`e3eae1d645e0150191ad8e8b1933515e32ba99b1a12e07fb814accdae5b988ab`,
exactly matching the historical deployed candidate and original load receipt.
Ten raw build inputs and other archived test fixtures are absent locally; no
full-manifest rebuild or all-input local regression pass is claimed. The exact
reviewed remote commit must pass the unweakened full CI workflow.

## Measured local comparison

Both sources were run in separate fresh Python processes pinned to one CPU,
using Python 3.12.14 and Node 24.19.0. The final harness hashes, read-only database
hash and revision-independent workload hash were identical. The workload hash
is `d77d1b4e40aad4ff8c0eca16ef31d95d179762b7773bf813ccae821704fbf365`.
The candidate journal durably retained 740 events (379,815 bytes), with all 58
planned requests started and settled. A subsequent report-label-only correction
for runs interrupted before cancellation was covered by the 18-test harness
suite; it does not change this successful-run comparison. Exact-commit CI
repeats the benchmark against the final published files.
CI separately uses its unchanged Python 3.11 / Node 22 configuration; the image
uses Python 3.12.

| Scenario | Baseline | Candidate |
| --- | --- | --- |
| First serial full recommendation | 1.683 s, completed | 1.862 s, completed |
| Warm serial | 1.740 s, completed | 2.054 s, completed |
| Concurrent 2 / 4 / 16 completion counts | 1/2, 1/4, 1/16 | 1/2, 1/4, 1/16 |
| Sustained 4 callers, 16 requests | 4 complete, 12 busy | 4 complete, 12 busy |
| Normal immediate/delayed recommendation recovery | All complete, 1.729–1.981 s | All complete, 1.738–2.050 s |
| Shared 55-request denominator | 21 complete, 34 busy, 0 timeout | 21 complete, 34 busy, 0 timeout |
| Python peak RSS | 53.93 MiB | 51.48 MiB |

The candidate adds three cancellation observations: one intentional cancellation
returned in 15.102 ms with one attempt; the immediate recommendation was busy
after 1.516 s; a full recommendation after the eight-second server budget plus
500 ms scheduling allowance completed in 1.921 s. Thus its complete receipt is
22 completed, 35 busy, one cancelled, zero timeouts out of 58 requests. The server
log shows the cancelled computation continued for 1.827 s before a disconnected
write; cancellation is not misrepresented as backend preemption.

A separate adapter also replayed the **original** shared-client/shared-session
sequence, serial 1 → burst 16 → immediate recovery 1. Only source/database paths,
loopback transport and a synthetic constant token provider were adapted; the
original uploaded files were not edited. The original turn payloads, default
10-second/two-attempt limits and shared-session behavior were retained. Both
sources completed 3/18 requests and returned 15 explicit busy failures, with zero
timeouts and an unchanged input session. Baseline serial/burst winner/recovery
took 1.771/1.832/1.818 s; candidate took 1.859/1.790/1.733 s.

The successor passes 41 Node contract tests and 18 harness tests. The original
60 cloud assertion prefixes and stale restart/reconfirmation check also pass
over local HTTP using the same read-only catalog. The unfiltered local Python
run collected 854 tests: 811 passed, two skipped, and 17 missing-input errors
(16 methods plus one class setup) prevented a full pass; there were no assertion
failures. Full pinned inputs, image build and exact final-source aggregate
validation remain mandatory in CI.

These comparisons **do not reproduce the Cloud Run incident and do not establish
sixteen-caller completion capacity**. They establish that the code changes retain
local load shedding, deterministic session isolation and recommendation recovery.
The separately reproduced client hang cases are fixed, but deployment-side
causality and recovery still require the private zero-traffic verification below.

After independent review and exact-commit CI, repeat verification only on a new
private zero-normal-traffic candidate through the already authorized deployment
session. Reinspect the current service/traffic/settings/IAM/image before and
after verification, and stop on any conflict. Retain 1 CPU, 512 MiB, concurrency
16, max instances 1, timeout 30 seconds and the existing identity. Keep the live
rollback revision's normal traffic untouched. Any later tuning or normal-traffic
promotion is a separate decision; successful load shedding alone is insufficient.

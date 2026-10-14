# Runtime repair for the qualified 9,364-binding catalog

The previous private candidate failed its first-request 10-second budget and
four-client first-attempt capacity checks. The opening memory histogram also
had no observations. Its failed acceptance and zero-traffic receipt remain
historical evidence; this patch does not relabel that run or clear its gates.

This repair changes runtime work without adding catalog records or authority:

- Bounded JSON validation removes quoted strings and counts structural tokens
  with byte operations. The same byte/member/depth bounds, escaped strings,
  decoded duplicate-name rejection, typed restore and nonfinite literal checks
  remain. Full database/source/schema/engine/image/identity checks still run.
- Iterative allocation accounting visits each object identity once with the
  same `sys.getsizeof` semantics and optional visited set. Separate root calls
  remain separate. The 192 MiB decoded-state limit is unchanged.
- Immutable parser results are cached only within the active request and
  guarded snapshot. Cache reads validate the current file/WAL/alias, clone and
  static namespace; native mutable imports remain uncached. Results are copied
  before exposure, the cache is bounded, and sessions/queries are not shared
  across requests. Main-path resolution and handle identity checks remain.
- Numeric startup phase timings go to the private CLI diagnostic. They are
  passed through a plain dictionary after complete validation; sealed artifact
  receipts and model state retain their existing format.

Independent fresh host processes measured strict load medians of 0.620 seconds
before and 0.463 seconds after the initial startup optimization. Complete
metadata, facet-image bytes, model state and allocation totals matched. These
are host measurements, not proof of Cloud Run latency or one-vCPU equivalence.
The first parser prototype improved its host warm median from 20.36 to 16.38 ms
with an exact response comparison using the same disclosed test-only revision.
Later frozen-source and cloud results belong in the separate release report.

The 87 ordered manifest inputs and their original 65-input prefix are unchanged.
The two derived runtime pins are updated only after hashing the frozen policy
files against the existing data: `472217007cc4d69a674eca6a7764128e56afbc1ca0dd0e05434acd7892d7e0db`
for the 87-input catalog and
`d900d5d7a3d501fafb8a9478276d9389bec828af05b5509e088a1665ca68b170`
for the 86-input catalog. Logical database and full-query semantic pins remain.
Activation requires saved sessions to restart and reconfirm their context.

Validation requires the full Python/Node suites, immutable clone/namespace
negative tests, native/materialized/loaded catalog equality, all three exact
source CI jobs, an independently bound immutable image, and actual private
cold/2/4/16-client/recovery/sustained acceptance. Successes, retries, busy replies,
timeouts, histogram gaps and unknowns remain separate. A naturally cold run is
not prewarmed; a first-request timeout or four-client busy response still fails.
An empty histogram does not establish zero memory usage.

The deployment remains private at 1 CPU, 512 MiB, concurrency 4, min 0/max 1,
60-second service timeout, one compute worker, 250 ms admission wait, 8-second
compute budget and 10-second caller attempts with at most one retry. Promotion
requires every acceptance gate and independent review to pass; otherwise the
captured serving revision keeps default traffic. Capture a fresh baseline and
all tag mappings before any rollout, preserving other sessions' revisions.

Card IDs, variants, source history, holds, prices, offers, image/display rights
and purchase/payment permissions are unchanged. No new ingestion, artwork,
marketplace data, frontend work or IAM changes are included. Buy&Ship remains
the intended MoR; Pivota holds no customer funds.

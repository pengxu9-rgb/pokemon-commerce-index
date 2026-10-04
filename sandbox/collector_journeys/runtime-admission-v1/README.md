# Runtime admission diagnostic receipts

These are local actual-HTTP tests using a disclosed synthetic 70,000-record catalog with a 10,000-record candidate pool, not Cloud Run or user acceptance results.

- `http-concurrency-baseline-024a72d-v1.json`: initial baseline setup failure because the isolated source copy lacked an unchanged SQL resource. No load result is claimed.
- `http-concurrency-baseline-024a72d-v2.json`: corrected baseline execution; all 16 burst callers timed out and recovery also timed out.
- `http-concurrency-synthetic-default-v1.json`: revised default admission, with accepted and overloaded work reported separately.
- `http-concurrency-onecpu-workers{1,2,4}-v1.json`: initial one-CPU-affinity comparison. These are process-affinity measurements, not a Cloud Run CPU quota simulation.
- `http-concurrency-synthetic-final-v3.json` and `http-concurrency-onecpu-workers{1,2,4}-final.json`: final reruns with explicit health/resource guard checks. Earlier receipts remain historical.

Run against a complete pinned catalog in a fresh process:

```sh
python -m scripts.benchmark_collector_concurrency \
  --db /tmp/review-catalog.sqlite3 --fixture-label real_pinned_catalog \
  --output /tmp/new-http-concurrency-report.json
```

A passed resource-guard diagnostic does not mean every client completed its task. Keep overloads, timeouts, transport failures and successful completions in separate counts and retain all outcomes in the denominator. The deadline is cooperative, not hard preemption. Actual staging load acceptance remains open.

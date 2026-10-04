# Reproducible mixed collector profile

This local diagnostic uses the real production Node caller over HTTP against a
fresh read-only Python server. It does not deploy, contact a marketplace or
change runtime limits, catalog data, commerce permissions or public-display and
physical-copy gates.

## Run

Use a fresh process and an output path outside the source checkout. The optional
CPU number must be available to the process; the receipt records actual affinity.

```sh
python scripts/benchmark_collector_mixed.py \
  --repo-root . \
  --db /path/to/pinned/catalog.sqlite3 \
  --workload tests/fixtures/collector-mixed-workload-v1.json \
  --output /path/to/evidence/mixed-capacity.json \
  --cpu 0
```

The frozen fixture strictly binds versioned logical catalog evidence independently
of the source revision. Its original catalog-byte SHA-256 is
`2ee7448b7e42ab9fe7e423a6769b01c18f260b503f3cb6d633802c5b2300549b`.
That original byte hash is provenance, not a claim that rebuilt SQLite files are
byte-identical. Compatibility requires the fixture's `catalog_evidence` digest
to match exactly. The independent `pokemon.collector-catalog-evidence.v2` digest
includes the complete stored main-schema definitions (tables, collations, types,
indexes, triggers and intermediate views), encoding, application ID and user
version. It also binds the same five view definitions and twenty evidence tables
as the reviewed journey revision. It omits only `card_rarity_correction.applied_at` and
normalizes `asserted_at` for valid `ai-artwork-review-v1` proposed assertions.
All other scoped evidence values and all stored schema definitions remain bound.
The actual database byte SHA is always recorded before and after the run and
must remain unchanged. The exact workload bytes consumed at startup are hashed
then, and the workload file must still have that hash after execution; a changed
or missing fixture makes the receipt fail while preserving its captured-input
identity and journal. The report states whether database bytes equal the original
fixture catalog. No count-only or unchecked byte-mismatch fallback is allowed.

The harness recomputes the selected source's catalog revision; it never replaces
the baseline semantic references. Only `catalog_revision` and
`expected_revision` keys are omitted recursively from semantic comparisons.
All actual caller/server revision checks remain active.

To compare a successor source, keep this same harness and fixture and set
`--repo-root` to that source. Use another output stem. Receipts and journals are
created exclusively, so earlier measurements and failed attempts are preserved.
Exit status is nonzero if a correctness, safety, protocol or accounting check
fails. A setup error is recorded without arbitrary exception text.

## Workload and checks

The 16 distinct, source-backed synthetic sessions contain 20 valid turns each:

- Four illustrator-preference changes and restorations
- Four character feedback dismiss → hidden language scope → clear → restoration
- Four ownership assertions, explicit resolution, exclusion and restoration
- Four comparisons with exact focus and a separate final select action

Sessions alternate English and Japanese. Identity-held catalog records remain
held; comparison fixtures page to shown eligible IDs before selection.

The full 97-call plan includes 16 serial references, mixed bursts at concurrency
2/4/16, immediate and delayed full-workload recovery, sustained concurrency 4
for 32 calls, 16 post-load isolation replays, external cancellation and deadline
recovery. Burst payloads differ. Sustained lanes own disjoint payload sets, so
an early rejected lane cannot coalesce with another lane's still-active payload.

Caller defaults remain 10 seconds per attempt, at most two attempts, and an
8 MiB response limit. Server defaults remain one worker, queue size four,
250 ms queue wait, and an eight-second request budget. No setting is overridden.
Every successful response must match its complete frozen semantic hash, exact
caller-owned session, unchanged inputs and closed authority gates.

## Interpretation

Busy rejection is unsuccessful work. Inspect completed / all requests for every
load phase and successful-response latency/throughput. The overall 97-call
completion fraction includes serial and recovery checks and is not the load
capacity fraction. Explicit rejection, timeout, cancellation, other errors,
unsettled and not-started calls remain in the planned denominator. Each started
case also uses the Python-owned planned count, even when the stream terminates
early; `started_requests` and `not_started_requests` make that distinction
explicit. Older ad-hoc summaries without a plan keep their observed denominator.

The journal reuses the reviewed bounded parser/sanitizer: 64 KiB events,
8 MiB total, 5,000 events, exclusive durable writes and a maximum 240-second
Node watchdog. Explicit custom plans are limited to 64 cases and 128 calls.
Raw response bodies, arbitrary errors, credentials and URLs are not journalled.

Startup measures fresh-process server preparation after catalog identity and
revision inspection. OS page caches are not flushed. Python peak RSS, launched
child lifetime peak and 50 ms sampled Python/Node/combined RSS are distinct
measurements; sampling can miss brief peaks. Missing measurements are explicit.
Optional process observers run in guarded daemon threads and cannot delay or
fail caller completion. These are local measurements, not Cloud Run cgroup
guarantees or a measured production-traffic distribution.

## Tests

```sh
python -m unittest discover -s tests -p test_collector_mixed_benchmark.py
python -m unittest discover -s tests -p test_collector_caller_benchmark.py
python -m unittest discover -s tests -p test_collector_caller_partial_accounting.py
```

The mixed tests cover malformed plans, exact plan bounds, callback failure and
blocking isolation, partial-journal denominators, frozen payload integrity,
cross-lane uniqueness, all evidence tables/view definitions, both permitted
bookkeeping normalizations, source independence and a small synthetic actual
Node→HTTP smoke. Synthetic
smoke performance is not real-catalog capacity. CI should gate deterministic
correctness and contract bounds, retain receipts on failure, and report rather
than gate machine-specific throughput or latency targets.

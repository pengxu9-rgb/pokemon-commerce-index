# Independent collector evaluation v1

## What was frozen

Thirty fresh, purposively selected collector questions were authored by a separate evaluation worker before any of these cases were executed. Initial questions and natural-language continuations are raw text. Explicit preference, inventory, feedback, pagination, comparison-focus and selection actions represent separately stated UI controls. They are not post-hoc repairs to failed language interpretation.

- `questions.json`: 30 questions, personas, precommitted follow-ups and explicit expected outcomes
- `rubric.json`: independent relevance, evidence-honesty, clarification, completion and abstention axes
- `binding-contract.json`: deterministic bindings to previously displayed records; no database search or discretionary substitution
- `metadata/freeze.json`: hashes recorded before execution

Question SHA-256: `2c6013fe0362e0eb9164063e7184ad264ae337c363a15e2eb9b17e4ca0a03ab1`

Baseline commit: `024a72d79f30198301ca538cc818d07577343195`

The evaluator read the build sequence, independent review, actual action schema and a few pinned source records for exact-ID grounding. It was aware of the architecture and documented limitations. These are agent-authored diagnostic scenarios, **not blinded sampling, real collector interviews, user testing, or a population accuracy estimate**. Once disclosed for tuning, this cohort becomes a regression suite; a later independent acceptance claim needs a fresh cohort.

## Scope and denominators

The audience is US and European collectors exploring Japanese cards. Cases cover novice starts, English/Japanese names, illustrator and release names, compound constraints, exclusions, unknown aesthetics, feedback, pagination, budget/grade/destination limits, known/uncertain inventory, exact coordinates, a held identity, and comparison followed by distinct focus and selection actions.

Every case stays in the denominator of 30. Errors, empty results, lost continuations, justified abstentions and product gaps are retained. Top-five displayed candidates are evaluated; unseen results cannot rescue a poor first page. Distinct coordinates, source-version records, held identities, selectable targets, artwork evidence and physical-copy verification have separate meanings.

Safe abstention does not establish usefulness. Unsupported acquisition, budget, grade and complete-checklist objectives in ICU-23, ICU-24, ICU-25 and ICU-27 cannot get full completion merely from a truthful disclaimer. The rubric allows partial progress when a useful catalog next step is supplied.

## Run against a complete pinned catalog

The runner uses the existing read-only Python `collector_journey.replay` API. It records every resolved action, raw prefix response, source facet/classification evidence, derived-name affiliation and exact runtime/database hashes. It does not test HTTP, Node-caller behavior, deployed UI, authentication, concurrency or a live marketplace.

Reuse a snapshot built in the **same CI job**, capturing the existing builder's JSON receipt:

```bash
python -m scripts.build_catalog_snapshot \
  --manifest catalog-build-manifest-source-binding-v1.json \
  --db /tmp/review-catalog.sqlite3 > /tmp/review-catalog-build-report.json

python sandbox/collector_journeys/independent-collector-eval-v1/run.py \
  --repo-root . \
  --manifest catalog-build-manifest-source-binding-v1.json \
  --db /tmp/review-catalog.sqlite3 \
  --build-report /tmp/review-catalog-build-report.json \
  --output /tmp/independent-collector-eval-report.json \
  --label "$GITHUB_SHA"
```

Alternatively replace `--db` and `--build-report` with `--build-db /tmp/fresh-eval-catalog.sqlite3`. Existing DB/output paths cannot be overwritten. Full manifest inputs must exist and match their hashes in either mode. Same-job reuse checks the receipt's manifest, path, step count and expected values, then independently recomputes every manifest expected catalog count from the read-only DB. A builder receipt is a provenance record, not a signed attestation. The actual DB byte hash and portable catalog/runtime revision are retained; hashes are rechecked after evaluation.

Output files:

- `/tmp/independent-collector-eval-report.json`: complete raw evidence and blank reviewer scoring sheet
- `/tmp/independent-collector-eval-report.summary.json`: compact per-case mechanical results, prefix IDs, next questions, holds and errors

The optional `--expected-runtime-manifest` verifies a pre-recorded `{path: {sha256: ...}}` map, including all expected package resources. `--preflight-only` records readiness without executing any question. Each prefix has a ten-second local execution budget by default; override only with a disclosed `--prefix-timeout` value, not to hide failures.

### Original-baseline versus current replay in CI

To run the old baseline without adding another source tree to the repository, extract the immutable commit into a temporary directory in the CI checkout:

```bash
mkdir -p /tmp/collector-baseline-024a72d
git archive 024a72d79f30198301ca538cc818d07577343195 \
  pokemon_index scripts/__init__.py scripts/build_catalog_snapshot.py \
  | tar -x -C /tmp/collector-baseline-024a72d
python sandbox/collector_journeys/independent-collector-eval-v1/run.py \
  --repo-root /tmp/collector-baseline-024a72d \
  --manifest "$PWD/catalog-build-manifest-source-binding-v1.json" \
  --db /tmp/review-catalog.sqlite3 \
  --build-report /tmp/review-catalog-build-report.json \
  --output /tmp/independent-collector-baseline-report.json \
  --label baseline-024a72d79f30198301ca538cc818d07577343195
```

The source commit must be available locally (`actions/checkout` may need sufficient fetch depth). Reuse is appropriate only while the pinned catalog manifest/data are identical; runtime hashes/revisions are recorded separately. Keep baseline and current reports distinct. Neither report is a usefulness score until reviewers apply the frozen rubric.

## CI policy

| Exit | Meaning |
|---|---|
| 0 | Execution completed without a detected frozen safety violation; product constraints/usefulness may still fail |
| 2 | Unsupported authority, premature/stale selection or acceptance of the held-identity action |
| 3 | Missing/mismatched data, unexpected API/runner fault, timeout, changed runtime/database, or invalid snapshot receipt |
| 4 | Frozen fixture integrity failure |

A missing shown candidate that prevents a later Like/Dismiss action is a **product-path failure**, not a fabricated API call and not automatically an infrastructure error. The remaining steps stay explicitly unexecuted. Expected policy rejections are retained as outcomes; an unrelated internal exception cannot satisfy them. An unknown mechanical check is an evaluator failure.

Machine constraints are diagnostic signals, not a substitute for the full expected outcome. For example, an empty intersection does not violate an all-candidates predicate, but it still needs review for relevant candidates or a helpful evidence-qualified clarification. Derived-name affiliations are collected from the runtime and labeled **not independently revalidated**; a reviewer must inspect their source/anchor evidence rather than treat the same helper's output as independent proof.

## Scoring after execution

Use each full report's `reviewer_scoring_sheet` and the frozen rubric. Record reviewer identity/type (for example, `ai_agent`, `human_reviewer`, or `human_collector`) in the separate scoring artifact, along with the input report SHA-256. Cite prefix JSON paths and source facts for each judgment. Keep unscored axes null; never fill them with a success inferred from a mechanical pass.

Prefer separate scorers with an explicit disagreement record. Agent-scored results are an **agent-reviewed diagnostic**, never human or real-user validation. Report:

1. Executed, blocked, failed and independently scored case counts out of 30
2. Each axis separately, plus held-identity and abstention counts
3. Strict completed cases (`completion=2`, `evidence_honesty=2`)
4. Useful-progress cases (`relevance>=2`, `completion>=1`, `evidence_honesty=2`)

Do not publish a quality percentage from an incomplete run, synthetic data or the old supported-cohort receipt. Evidence honesty cannot compensate for irrelevant recommendations or an unmet collector goal.

## Local validation and retained limitations

The local full-catalog attempt is blocked: 55 of 65 manifest inputs are hash-verified; ten large source inputs are unavailable. Both baseline preflight receipts retain all 30 cases as `not_executed`. No local baseline usefulness result is claimed.

The early baseline materialization omitted two unchanged SQL resources. Their exact bytes were checked against the parent's pre-edit manifest before restoration; the initial smoke blockers remain in `metadata/harness-initial-blockers.json`. The original preflight receipt is retained; the v2 receipt includes stricter complete-resource validation and generic reviewer terminology.

Harness-only validation is separate:

```bash
python sandbox/collector_journeys/independent-collector-eval-v1/test_runner.py
python sandbox/collector_journeys/independent-collector-eval-v1/smoke_baseline_api.py \
  --repo-root /path/to/baseline \
  --synthetic-suite sandbox/collector_journeys/recommendation-v1/reviewed-suite.json \
  --output /tmp/evaluator-synthetic-smoke.json
```

The smoke invokes two real baseline API prefixes on the existing synthetic engineering fixture. It exercises bindings, evidence extraction and immutable read-only behavior. It executes **zero** of the 30 frozen evaluation cases and provides **zero** collector-usefulness evidence.

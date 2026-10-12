# Existing private staging rollout

Target: `pivota-staging`, `us-west1`, existing service `pokemon-commerce-index`.
Canonical URL: `https://pokemon-commerce-index-42ogcsuwxq-uw.a.run.app`.
Runtime identity: `sa-pokemon-commerce-index@pivota-staging.iam.gserviceaccount.com`.

This runbook changes only the reviewed catalog service in the existing staging
project. It does not register or deploy the Node caller in Pivota, enable a
marketplace feed, expose a public catalog, grant IAM, create credentials, or
establish physical-printing, offer-join, purchase, or payment readiness.

## Preconditions

1. Obtain the **final reviewed full commit SHA** from the review handoff. Do not
   deploy the old `f499b46` automatically if review fixes have produced a newer
   commit. Verify the remote commit and the exact commit's completed CI.
2. Use an execution session with existing authorized GCP credentials. On access
   denial, stop and report the exact command/resource. Do not create service
   accounts, keys, OAuth grants, IAM bindings, APIs, buckets, or repositories to
   make the deployment work. Do not copy credentials into chat or files.
3. Serialize this rollout with other operators. The CLI cannot make a multi-step
   check/deploy/smoke/promotion sequence atomic against a concurrent operator.
   If another revision or traffic change appears, stop and reconcile it.
4. From the final source, run the full Python and Node suites, rebuild the pinned
   catalog, and run the synthetic recommendation and real-catalog compatibility
   rehearsals. Report executed passes and skips separately. The original
   `37160347776` CI run was green for `f499b46`, with **626 Python tests collected,
   2 skipped**, plus a Docker build; that workflow did not explicitly run the Node
   suite or the HTTP-to-Node rehearsal.
5. Independently establish the build binding: clean final Git tree → exact
   uploaded build context → successful build ID/log → immutable Artifact Registry
   digest. Use the session's existing authorized build route. Export only the
   reviewed commit (for example `git archive` into a new directory), rather than
   uploading a working directory containing unrelated/ignored files. Record the
   full SHA, manifest SHA-256, build context hash, build ID, immutable image digest,
   final test/CI links and portable `catalog_revision` from a fresh pinned build.
   Never treat an image tag or an operator-supplied commit label as provenance.

The guard intentionally accepts an **already-built immutable image**, and does
not build, install tools, enable APIs, create storage, or authenticate a new
account. Its `--source-sha` field is recorded as
`operator_asserted_source_sha`; `source_binding_verified_by_script=false` stays
explicit. The operator must complete step 5. Its observed image digest and remote
catalog/runtime revision provide additional checks, not a substitute for build
provenance. Keep receipts outside the repo and out of the build context.

## Existing-state check

Run from the final clean repository checkout:

```bash
python3 -m scripts.stage_existing_cloud_run inspect
```

This is read-only. It fails if the existing service/IAM cannot be read, another
rollout is unfinished, the known runtime identity or service URL differs, invoker
IAM checking is disabled, or service-level IAM includes broad principals. It
prints the concrete current traffic targets, resource limits and fingerprints.
Raw environment values and IAM policy contents are not written to receipts.

The previous receipt `cloud-deployment-20261003-source-binding-v1.json` recorded
revision `pokemon-commerce-index-00043-2x6` at 100%, image digest
`dd2e381d7ce541d6b9c6b8c77eee7d6a4b57f7721e5a933a855b489bf4a51322`,
1 CPU, 512 MiB, concurrency 16, max instances 1, and timeout 30 seconds.
Those are historical observations; use the **live** state as the rollback
baseline. Do not reset settings to this receipt without investigating drift.

The container is Python 3.12, non-root UID/GID 65532, with an image-built,
read-only SQLite snapshot and internal-catalog routes. It uses a threaded Python
HTTP server; the recommendation path can inspect up to 10,000 candidates and
replay up to 20 turns. Preserve the observed resource settings. Include a bounded
parallel-request/cold-start check and inspect memory, latency and errors before
promotion; a green health endpoint does not establish that 512 MiB/concurrency
16 is sufficient under load. The Node caller has a 10-second per-attempt timeout
and at most two attempts (one retry). Record timeout behavior; do not silently raise
limits, concurrency, retries or memory to make a test pass.

**Current promotion hold from the independent local review:** even after the
review optimizations, 16 concurrent valid requests against the 70,000-record
catalog, exercising a 10,000-candidate query and a 20-page replay, all reached the
40-second client cutoff. The corresponding serial request took about 1.26 seconds;
observed peak process memory was about 261 MiB. This is a local stress result, not
a Cloud Run measurement, but it explicitly means the existing concurrency of 16
is **not validated**. Serial CI or serial smokes do not clear this hold.

The subsequent [discovery continuation](DISCOVERY_CONTINUATION_20261004.md)
adds one active computation, a bounded short queue and explicit overload responses.
Local synthetic HTTP results show recovery and lower resource use, but most requests
in a 16-client burst are rejected as busy. This is load shedding, not resolution
of the task-completion capacity hold. The eight-second computation deadline is
cooperative, not hard preemption. Record successful completion and overload rates
separately, including the Node caller's bounded retry behavior and recovery UX.

The [concurrency/recovery repair](CONCURRENCY_RECOVERY_20261004.md) adds a complete
Node attempt watchdog, non-blocking cancellation, shared body/admission/compute
budgets and sanitized per-attempt/server timings. Locally reproduced cancellation
hangs are not proof of the reported private Cloud Run failure's root cause.
Compare actual Node caller serial, 2/4/16-client, sustained and full recommendation
recovery results; retain explicit rejections and timeouts in every denominator.
Do not substitute health/anonymous-access checks or fast 503s for that evidence.

Stage at zero traffic and measure cold-start and sustained expected-load behavior
on the actual Cloud Run revision. Promotion requires evidence that requests finish
within the caller's **10-second per-attempt budget** at the expected concurrency,
with acceptable errors and memory. Do not count the retry window as extra latency
budget or replace timeout results with serial measurements. If configuration
tuning is necessary, record it as a separate reviewed change with before/after
measurements, while preserving private IAM and the existing service identity.
Do not weaken this helper's unchanged-settings guard: finish the separately
authorized configuration change, then capture a new explicit baseline and repeat
all rollout gates.

## Stage at zero normal traffic

Replace the placeholders with reviewed, verified values. Use an unused tag and a
new receipt path. The image must be in the existing staging image repository and
pinned by digest.

```bash
python3 -m scripts.stage_existing_cloud_run stage \
  --image 'us-west1-docker.pkg.dev/pivota-staging/cloud-run-source-deploy/pokemon-commerce-index@sha256:IMAGE_DIGEST' \
  --source-sha 'FINAL_REVIEWED_40_CHARACTER_SHA' \
  --catalog-revision 'REBUILT_64_CHARACTER_CATALOG_RUNTIME_REVISION' \
  --tag 'review-UNIQUE_TAG' \
  --receipt /tmp/pokemon-private-rollout-UNIQUE.json
```

Before any deployment mutation, the helper also probes the canonical `/health`
without credentials and requires 401/403. Service-level IAM alone cannot exclude
broad access inherited from project/organization policy; anonymous 200 stops the
rollout before a tagged revision can expose new code.

The helper records its baseline **before** the mutation, deploys with
`--no-traffic`, preserves the observed ingress and existing service identity,
and does not pass IAM, resource, environment, secret, or API-enabling flags. It
checks that actual resolved root traffic, IAM and configuration remain unchanged,
and that the tagged Ready revision has the exact supplied image digest. Changing
from `latestRevision: true` to the same explicit old revision at 100% is expected
Cloud Run behavior for `--no-traffic`.

Do not use `scripts/deploy_cloud_run.sh` for this guarded update. That older helper
can create a service account after any failed describe, imposes its own resource
settings, and lacks a no-traffic gate.

If deployment errors or times out, the outcome can be uncertain. Do not repeat it
blindly. Read the service, revisions and build state first. A `prepared` receipt
means the helper has not established success; it is not permission to promote.
Keep the baseline and failed evidence. An IAM/configuration mismatch stops the
helper without trying to repair permissions or security settings.

## Authenticated verification

```bash
python3 -m scripts.stage_existing_cloud_run verify \
  --receipt /tmp/pokemon-private-rollout-UNIQUE.json
```

The helper verifies:

- Root traffic remains on the captured baseline, and candidate tag, digest,
  service identity, settings and service-level IAM are unchanged
- Anonymous `/health` returns 401/403, then an existing operator ID token receives
  authenticated `{"ok": true}`; redirects are rejected
- Actual HTTPS → current Node caller → Python recommendation returns the expected
  catalog/runtime revision and passes the caller's nested authority validation
- Dismissal removes the exact shown ID, target reset retains no selection, and
  stale sessions return `catalog_changed` with no result/session/target

The token is acquired through existing `gcloud auth`, passed only in subprocess
memory, and never written to a receipt, command line or displayed error. For
service-identity ID tokens, the audience is the **canonical service URL**, even
when the HTTP destination is the traffic-tag URL. The helper's operator-token
probe does not prove access from any deployed Pivota service identity.

These are deliberately small smoke checks. Before promotion, the deployment
session must also exercise the frozen acceptance cases on the **tagged** revision:
preference set/replace/clear, feedback membership and context invalidation,
dismiss/clear, pagination, evidence-only comparison → explicit member choice →
fresh exact focus → separate selection, held identity/source-number conflicts,
unknown/possibly-owned inventory, new-goal reset, English/Japanese/Chinese paths,
all commerce/physical/public flags false and prices/offers absent. Compare
cloud responses with direct local replay for the final built snapshot/runtime.
Use the versioned identity-hold compatibility suite, preserving the original
historical failure report.

`scripts/rehearse_pivota_collector.py --cloud` currently discovers the canonical
service URL and reports `latestReadyRevisionName`; it does **not** target a
no-traffic tag. Do not use that unchanged command as evidence that the candidate
was tested. Supply the observed candidate URL in a purpose-built harness using
`integrations/pivota/replay.cjs`, keep token transport in memory, and explicitly
bind the resulting report to the actual tagged revision/digest. The synthetic
recommendation fixture is local fixture validation, not the deployed catalog.

## Promote only after all gates

After recording exact-source/image binding, final CI, the complete tagged
acceptance suite, resource observations and private-access checks:

```bash
python3 -m scripts.stage_existing_cloud_run promote \
  --receipt /tmp/pokemon-private-rollout-UNIQUE.json \
  --acceptance-report /tmp/pokemon-acceptance-UNIQUE/acceptance.json \
  --accept-reviewed-source-ci-and-full-smokes
```

The separate acceptance report is mandatory. It must use schema
`pokemon.private-staging-acceptance.v1` and bind `source_sha`, `image`,
`candidate_revision`, `candidate_url`, and `catalog_revision` to the staged
receipt. Its `checks` object must cover every name in
`REQUIRED_ACCEPTANCE_CHECKS` in the helper. Each entry requires `passed: true`,
`evidence_file` (relative to the acceptance report directory) and
`evidence_sha256` matching an existing artifact. Keep artifacts inside that
directory, and preserve the actual request/response and expected-result records.

The report also requires `source_binding` with `verified: true`, actual `build_id`,
`source_context_sha256`, `evidence_file` and `evidence_sha256`; and `ci` with the
exact `head_sha`, `conclusion: success`, workflow-run `url`, `evidence_file` and
`evidence_sha256`. A missing/failed check, different source/image/revision, missing
artifact or mismatched hash blocks promotion. The helper checks the record's
binding, completeness and file integrity; the operator is responsible for
reviewing whether the attached artifacts actually substantiate its claims. Do not
fill it by copying booleans from the small smoke suite.

The flag is an explicit operator assertion that these full records were reviewed.
The helper cannot independently infer them from its four Node smokes. It reruns
current candidate checks/smokes, moves 100% traffic to the exact verified revision,
then repeats configuration/IAM/traffic checks and canonical-URL smokes. Never
substitute `LATEST` for the captured revision name. No automatic promotion occurs
from stage or verify.

If the current receipt stops at `promoting`, inspect live traffic before deciding
what happened. If post-promotion validation fails, roll back promptly within the
authorized service scope, retaining the failed receipt and logs.

## Rollback

```bash
python3 -m scripts.stage_existing_cloud_run rollback \
  --receipt /tmp/pokemon-private-rollout-UNIQUE.json
```

Rollback restores the captured concrete revision percentages, never `LATEST`.
It refuses if IAM/configuration changed or a later/unrelated rollout owns traffic.
It does not delete revisions or tags or change settings/IAM. It verifies traffic
restoration; then rerun authenticated baseline health and the baseline-compatible
journey checks. The new caller/runtime may invalidate old sessions, so explicitly
restart and reconfirm selected targets after rollout or rollback.

## Node caller and completion boundary

`integrations/pivota/` is a CommonJS integration deliverable. The Python Dockerfile
does not package a Node server, and the repository does not identify an active
Pivota gateway deployment for it. Do not claim that catalog deployment deploys or
registers the caller. A coordinated real caller rollout would need its owning
repository, actual deployed service identity and existing invoker authorization,
all established separately; no IAM change is included here.

The final deployment receipt should include source SHA, CI result/link, build ID,
manifest hash, image digest, tagged and promoted revision, catalog/runtime
revision, prior/current traffic, verified private access, preserved identity and
resource settings, smoke/acceptance results, unresolved caller-deployment status,
and the rollback target. Explicitly record any stage not run. No cloud execution
has been established by this runbook or its mocked unit tests.

References: [Cloud Run no-traffic deployment](https://docs.cloud.google.com/sdk/gcloud/reference/run/deploy),
[traffic migration and rollback](https://docs.cloud.google.com/run/docs/rollouts-rollbacks-traffic-migration),
[service-to-service token audience](https://docs.cloud.google.com/run/docs/authenticating/service-to-service).

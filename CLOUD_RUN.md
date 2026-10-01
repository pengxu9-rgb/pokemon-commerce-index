# Google Cloud staging deployment

The catalog API runs as a **private Cloud Run service** in `pivota-staging`, region `us-west1`. The current image uses [`catalog-build-manifest-metadata-v2.json`](catalog-build-manifest-metadata-v2.json): 40 ordered SHA-256 checked inputs, **70,005 internal source-version/family records**, 33,543 existing structurally eligible records and zero public display approvals. The English historical expansion contributes 14,838 match-disabled records; it enriches 9,135 existing set/number groups and adds 26 new groups. Two official Japanese batches enrich 2,497 existing coordinate records: 1,900 known rarity declarations, 597 pages with no icon, four numbered-part page guards and ten artist conflicts excluded from discovery facets. Existing rarity corrections, identity/denominator holds, 100 original supported metadata targets and collector evidence remain intact. See [catalog coverage](CATALOG_COVERAGE.md). Revision **`pokemon-commerce-index-00026-9lt`** was deployed on 2026-10-02 and serves all traffic. The image runs as a non-root user and contains no marketplace credentials or live prices. Internal routes require `--internal-catalog-api`; Cloud Run IAM remains enabled.

## Verified Japanese expansion revision `00026-9lt` — 2026-10-02

[Current deployment evidence](cloud-deployment-20261002-japanese-metadata-v2.json) records the image digest, runtime/manifest hashes and **48 authenticated logical requests**: full pagination of 20 constructed questions, eight synthetic inventory checks, four numbered-part journey blockers, seven graph checks and status/input/query guards. Metadata counts match the 40-input manifest: 2,497 active records, 1,900 known rarity declarations and four numbered-part records. No stale metadata appears. Original supported targets remain 100; automatic live-offer approvals remain zero. IAM remains private and two unauthenticated requests return 403. No transport errors were recorded.

The same narrowly scoped comparison rule retains both local/cloud import application times for proposed AI artwork edges; it does not exclude source retrieval times, evidence or review state. Full numbered-part journey responses and their semantic revisions agree. 433 Python and 11 Node tests pass. These are private staging engineering checks, not independent listing precision or a deployed Pivota service connection. The official-page cache, review queues, Gemini research and held-group queue are excluded from the runtime image; only SHA-bound metadata evidence is loaded.

## Prior Japanese metadata revision `00025-zs7` — 2026-10-01

[Prior deployment evidence](cloud-deployment-20261001-japanese-metadata-v1.json) records the immutable image digest, source/manifest hashes and **49 authenticated logical requests**: 20 constructed question cases with complete pagination, eight synthetic inventory cases, four numbered-part journey blockers, seven graph checks and query/input/status guards. The 1,000 active official metadata events, 749 rarity declarations and four numbered-part records agree with the 39-input manifest. IAM has no public invoker binding; two unauthenticated checks return 403. One transient journey transport error recovered through the bounded retry; it is retained in the report.

The initial graph comparison found only a rebuild application-time difference on the same imported, proposed AI edge for M-P 046. [The original difference](cloud-verification-20261001-metadata-graph-rebuild-time.json) remains recorded. The final comparison excludes only `asserted_at` for proposed `ai-artwork-review-v1` candidates and retains both timestamps in its evidence. All identity, evidence, review, facet and official retrieval fields still compare exactly. Four full journey responses, including catalog revision binding, match the local replay. No runtime facts were altered to resolve this diagnostic difference. 430 Python and 11 Node tests pass; these checks establish private staging regression equivalence, not real listing accuracy or completed Pivota service integration.

## Prior coverage revision `00024-8qz` — 2026-10-01

[Prior deployment evidence](cloud-deployment-20261001-coverage-v1.json) records the immutable image digest, source/manifest hashes, **35 authenticated logical requests**, 14 constructed catalog question cases with complete pagination, eight synthetic inventory cases and query/input guards. Results match the rebuilt local catalog. IAM has no public invoker binding; unauthenticated checks return 403. Supported metadata and offer gates remain unchanged. This is a development regression check, not marketplace matching accuracy. The initial verifier attempt stopped because the new diagnostic report lacked two required metadata fields; the report was completed and the successful check ran from the beginning.


## Prior caller revision `00023-n84` — 2026-10-01

[Prior deployment evidence](cloud-deployment-20261001-pivota-caller-v1.json) records the immutable image digest, submitted source-file hashes and 156 authenticated logical HTTP requests: complete pagination of the 30-question development cohort, eight synthetic inventory cases, six official cameo queries, evidence status/context, AI-only abstention, scoped negative controls and invalid inputs; 14 new bilingual/scoped queries and four synthetic cameo-inventory checks; all 59 prefix requests from 20 collector journeys, five invalid journey requests and two ambiguity/exclusion guards. IAM has no public invoker binding; unauthenticated health, inventory and journey return 403. Catalog, support and collector-evidence counts agree with the 35-input manifest. Automatic live-offer approval and verified card-pair relationships remain zero.

An additional [Node caller replay](sandbox/collector_journeys/v2/cloud-caller-report.json) passes all 39 revised development steps from eight new source situations, with complete responses equal to the local HTTP/direct replay. Intent guards now preserve all-language scope, non-card accessories, next-collection preferences, purchase-location requests and natural counterpart questions. These are 195 authenticated logical calls across the two reports. The caller was driven by an authorized operator; Pivota's actual service identity and active operation registry are not integrated. See [the adapter readiness and diagnostic](PIVOTA_COLLECTOR_ADAPTER_20261001.md).

Private routes include `/collector-evidence-status` and `/catalog-evidence?card_id=...`, alongside `/supported-status`, `/collector-discovery?q=...&limit=20&offset=0`, `POST /collector-inventory` and `POST /collector-journey`. Eight cameo scopes return official-description partials. Mew has a source-bound AI review lead outside confirmed cards and inventory gaps. Release-level ball-pattern context does not approve a physical card's finish. Release, number, language and finish constraints prevent evidence transfer to an unrelated requested printing. See [the evidence expansion](COLLECTOR_EVIDENCE_EXPANSION_20261001.md).

The service uses a read-only catalog snapshot. Inventory is not persisted or included in request-body logs. Images, researcher source pages and model checkpoints are excluded from the image; serving does not call Gemini or fetch external sources. The controlled journey replays caller-owned actions and returns a catalog-only target intent; there is no public conversational agent or account inventory store. Its revision binds semantic catalog evidence and runtime code, ignoring rebuild application timestamps. See [the journey implementation](COLLECTOR_JOURNEY_IMPLEMENTATION_20261001.md). Market writes and feed schedules are not enabled.

[Revision 00017 evidence checks](cloud-deployment-20261001-evidence-v1.json) are retained; final inspection then added the explicit cameo scope guards. [Revision 00016 inventory checks](cloud-deployment-20261001-inventory-v2.json), [revision 00015](cloud-deployment-20261001-inventory-v1.json), the [first source-cohort rollout](cloud-deployment-20261001-collector-v3.json), its [engineering control correction](cloud-verification-20261001-inventory-control-correction.json) and the [initial supported-discovery rollout](cloud-deployment-20261001.json) remain historical evidence. No frozen source questions or expected card memberships were rewritten for the new enrichment.

## Previous revision — 2026-09-30

[Deployment evidence](cloud-deployment-20260930.json) records the image digest, build-manifest and runtime file hashes, and three authenticated HTTP checks: `/health` returned 200; `/catalog-status` returned 55,167 identities and 33,543 match-eligible identities; `/catalog-card` returned SAR plus the official rarity correction for `ja:SV4A:347/190:holo`. An unauthenticated health request returned 403, and IAM contained no public invoker bindings.

The initial rollout exposed an actual HTTP 503: temporary database files inherited owner-only permissions, so the non-root runtime could not open the snapshot. Revision 00010 fixed this by making the image snapshot readable (`0444`) and opening HTTP database connections with SQLite `mode=ro`; revision 00012 retains that protection. Upload and Docker exclusion files include all current manifest inputs and the build script while excluding research sandbox data and local databases. Read-only connection tests reject database writes and refuse to create a missing snapshot.

Service: `https://pokemon-commerce-index-184498324954.us-west1.run.app`. Google authentication is required. The cloud service serves catalog and bounded collector queries; model-based fact extraction and action planning remain sandbox/CLI tools, with no public chat endpoint.

Deploy from the repository root:

```bash
bash scripts/deploy_cloud_run.sh pivota-staging us-west1
```

The script creates a dedicated runtime service account with no project roles if it does not exist, then deploys `pokemon-commerce-index` with unauthenticated access disabled, zero minimum instances and one maximum instance. It refuses `pivota-prod`. It does not grant Cloud Run Invoker to anyone; access must be assigned deliberately to the calling Pivota service identity or an operator.

Private routes: `/health`, `/catalog-status`, `/catalog-search?q=...`, `/catalog-search?dex_id=25`, `/catalog-search?illustrator=Naoyo%20Kimura`, `/catalog-card?card_id=...`, `/catalog-neighborhood?card_id=...`. The existing commerce routes remain gated by `display_allowed` and source policy. The catalog routes expose internal source metadata and must never be deployed with public invoker access.

The SQLite file in the image is a read-only catalog snapshot. It has structural variant neighbors but no curated counterpart edges. The legacy exploration-session library remains local/CLI; the private HTTP collector journey instead replays caller-owned actions without persistence. Live offer collection, price observations, quotes and account-backed sessions need persistent storage outside Cloud Run's ephemeral filesystem before those features are deployed. A later production design can place normalized observations and session state in a managed database and use a separate scheduled ingestion worker; this staging service is the card catalog baseline.

Verify deployment:

```bash
gcloud run services describe pokemon-commerce-index \
  --project=pivota-staging --region=us-west1 \
  --format='value(status.url,status.conditions[0].status)'
gcloud run services get-iam-policy pokemon-commerce-index \
  --project=pivota-staging --region=us-west1 \
  --format=json
```

The IAM policy must not include `allUsers` or `allAuthenticatedUsers`. To query from an authorized principal, send a Google identity token in the `Authorization: Bearer` header to the service URL. No credentials are stored in this repository.

[Revision 00018 evidence checks](cloud-deployment-20261001-evidence-v2.json) remain the historical 44-event packet and final scope-guard deployment.

[Revision 00019 expansion checks](cloud-deployment-20261001-expansion-v1.json) remain historical evidence. Revision 00021 exposed a journey revision mismatch caused by rebuild timestamps; [the failure](sandbox/collector_journeys/v1/cloud-portability-failure.json) and [equivalent-rebuild check](sandbox/collector_journeys/v1/portability-rehearsal.json) are retained. Revision 00022 corrects it.

[Revision 00022 journey verification](cloud-deployment-20261001-journey-v1.json) remains historical evidence. Revision 00023 adds the collector goal-boundary repairs; catalog/evidence inputs and marketplace readiness are unchanged.

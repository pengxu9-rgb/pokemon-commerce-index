# Google Cloud staging deployment

The catalog API runs as a **private Cloud Run service** in `pivota-staging`, region `us-west1`. The current image build uses [`catalog-build-manifest-rarity-v2.json`](catalog-build-manifest-rarity-v2.json): 19 ordered, SHA-256 checked inputs with asserted output counts (55,167 internal identities; 33,543 match eligible; 532 official rarity overlays; 19 identity exceptions; two denominator-conflict rules; zero public-display approvals). Earlier manifests remain available for frozen research cohorts. Revision **`pokemon-commerce-index-00010-w7b`** was deployed on 2026-09-30 and serves all traffic. The image runs as a non-root user and contains no marketplace credentials or live prices. The service exposes internal catalog routes only when started with `--internal-catalog-api`; Cloud Run IAM must remain enabled.

## Verified revision — 2026-09-30

[Deployment evidence](cloud-deployment-20260930.json) records the image digest, build-manifest and runtime file hashes, and three authenticated HTTP checks: `/health` returned 200; `/catalog-status` returned 55,167 identities and 33,543 match-eligible identities; `/catalog-card` returned SAR plus the official rarity correction for `ja:SV4A:347/190:holo`. An unauthenticated health request returned 403, and IAM contained no public invoker bindings.

The initial rollout exposed an actual HTTP 503: temporary database files inherited owner-only permissions, so the non-root runtime could not open the snapshot. Revision 00010 fixes this by making the image snapshot readable (`0444`) and opening HTTP database connections with SQLite `mode=ro`. The upload and Docker exclusion files now include all 19 manifest inputs and the build script, while excluding research sandbox data and local databases. The read-only connection tests reject database writes and refuse to create a missing snapshot.

Service: `https://pokemon-commerce-index-184498324954.us-west1.run.app`. Google authentication is required. The cloud service serves catalog queries; the v6 natural-language extractor and action planner remain sandbox/CLI tools, with no new public chat endpoint.

Deploy from the repository root:

```bash
bash scripts/deploy_cloud_run.sh pivota-staging us-west1
```

The script creates a dedicated runtime service account with no project roles if it does not exist, then deploys `pokemon-commerce-index` with unauthenticated access disabled, zero minimum instances and one maximum instance. It refuses `pivota-prod`. It does not grant Cloud Run Invoker to anyone; access must be assigned deliberately to the calling Pivota service identity or an operator.

Private routes: `/health`, `/catalog-status`, `/catalog-search?q=...`, `/catalog-search?dex_id=25`, `/catalog-search?illustrator=Naoyo%20Kimura`, `/catalog-card?card_id=...`, `/catalog-neighborhood?card_id=...`. The existing commerce routes remain gated by `display_allowed` and source policy. The catalog routes expose internal source metadata and must never be deployed with public invoker access.

The SQLite file in the image is a read-only catalog snapshot. It has structural variant neighbors but no curated counterpart edges. Exploration sessions are available through the local library and CLI only; they are not exposed by the HTTP service or persisted across deployments. Live offer collection, price observations, quotes and user exploration sessions need persistent storage outside Cloud Run's ephemeral filesystem before those features are deployed. A later production design can place normalized observations and session state in a managed database and use a separate scheduled ingestion worker; this staging service is the card catalog baseline.

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

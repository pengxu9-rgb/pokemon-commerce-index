# Google Cloud staging deployment

The catalog API runs as a **private Cloud Run service** in `pivota-staging`, region `us-west1`. The current image uses [`catalog-build-manifest-discovery-v1.json`](catalog-build-manifest-discovery-v1.json): 33 ordered, SHA-256 checked inputs with asserted output counts (55,167 internal identities; 33,543 structurally eligible; 532 official rarity overlays; 19 identity exceptions; two denominator-conflict rules; zero public-display approvals), plus 100 source-bound supported metadata targets, three release overlays, six vocabulary records, three evolution families, 122 reviewed aliases and 460 concept review events. Revision **`pokemon-commerce-index-00012-7rl`** was deployed on 2026-10-01 and serves all traffic. The image runs as a non-root user and contains no marketplace credentials or live prices. Internal routes require `--internal-catalog-api`; Cloud Run IAM must remain enabled.

## Verified revision — 2026-10-01

[Deployment evidence](cloud-deployment-20261001.json) records the immutable image digest, submitted source-file hashes and twelve authenticated HTTP checks. Catalog membership agrees with the manifest. `/supported-status` returns 100 current targets, zero stale targets, 122 aliases, 460 review events and zero automatic-live-offer approvals. `/collector-discovery` returns an English Eevee family page and exact SV4A Mew target with supported metadata; a requested master-ball finish returns no match; a price request blocks; counterpart leads remain unverified. Invalid pagination returns 400. Unauthenticated health returns 403, and IAM contains no public invoker binding.

New private routes: `/supported-status` and `/collector-discovery?q=...&limit=20&offset=0`. The collector route executes bounded internal catalog patterns; it is not a public conversational agent. It uses the same read-only snapshot connection as the other catalog routes. The durable ingestion queue and 100-target synthetic commerce rehearsal run locally against separate files; neither market writes nor a feed schedule has been enabled on Cloud Run.

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

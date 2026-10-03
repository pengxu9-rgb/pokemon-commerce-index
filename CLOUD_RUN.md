# Google Cloud staging deployment

The catalog API runs as a **private Cloud Run service** in `pivota-staging`, region `us-west1`. The current image uses [`catalog-build-manifest-cross-release-source-facts-v1.json`](catalog-build-manifest-cross-release-source-facts-v1.json): **55 ordered SHA-256 checked inputs**, 70,006 internal source records, 33,543 structurally eligible records and zero display or automatic-offer approvals. It preserves all earlier 53 inputs and appends 99 number events and 99 source-image fact advisories. Revision **`pokemon-commerce-index-00038-jsw`**, deployed on 2026-10-03, serves all traffic. The runtime remains private, non-root and read-only, with no marketplace credentials, serving AI calls or live prices.

## Verified cross-release revision `00038-jsw` — 2026-10-03

[New cohort checks](catalog/cross-release-source-facts-v1/private-cloud-replay-v1.json) pass **118/118**, including every acquired-image subject and the unavailable-image hold; [prior fact checks](catalog/cross-release-source-facts-v1/prior-facts-cloud-v1.json) pass **23/23** on the same image. These **141 engineering checks include four repeated unauthenticated 403 denials**. Final logical failures and transport errors are zero. Local checks pass 116/116 and 21/21. **563 Python and twelve Node tests pass** on the final runtime; intermediate 561/562-test runs remain recorded. [Delivery bindings](catalog/cross-release-source-facts-v1/delivery-validation-v1.json) verify all input, source, review, snapshot and runtime hashes, private IAM and unchanged deployment revision/image.

The frozen hundred yields 99 acquired/reviewed scans, 98 title/number correspondences, one acquired-symbol hold and one unavailable image. Cumulative source facts cover 148 exact subjects, including the existing HP conflict. All 79 prior number rows, 49 prior fact rows and 42 other base tables are preserved. Catalog/graph/commerce decisions remain unchanged. A metadata-only next-thousand queue and fourteen unreviewed artwork-pair hypotheses are frozen for subsequent work. [Implementation, review scope and next sequence](CROSS_RELEASE_SOURCE_FACTS_20261003.md).

## Verified forty-image expansion revision `00037-5r7` — 2026-10-03

[New batch checks](catalog/source-image-facts-expansion-v1/private-cloud-replay-v1.json) pass **54/54** and [prior fact regressions](catalog/source-image-facts-expansion-v1/prior-facts-cloud-v1.json) pass **23/23** on the same revision. The **77 engineering checks include four repeated unauthenticated 403 denials**. No transport errors or final logical failures are recorded. Six actual Node journeys across both reports retain the existing timeout/retry policy.

[Delivery bindings](catalog/source-image-facts-expansion-v1/delivery-validation-v1.json) verify runtime/snapshot/review/input hashes, private IAM and unchanged revision/image. The runtime bytes are unchanged from the prior commit; ten source-fact guard tests and all twelve Node client/operation tests pass. The earlier full 559-test suite was not rerun for this data-only expansion. Local batch/default regressions pass 52/52 and 21/21.

All forty frozen source scans have separate recorded root/Gemini readings: forty title correspondences, thirty-six HP agreements and four absent trainer HP headers; no new HP conflict. Root prior catalog/number context remains disclosed, so these are advisories, not independent accuracy calibration. Cumulative source facts cover 49 selected promo scans and retain one HP conflict. All nine previous fact events, all 79 number events and 43 base tables remain preserved; the original five number holds and graph/commerce permissions stay unchanged. The next hundred research candidates span twenty releases and have no acquired images or imported observations. [Implementation and next scope](SOURCE_IMAGE_FACTS_EXPANSION_20261003.md).

## Prior source-image fact revision `00036-6gh` — 2026-10-03

[New interface checks](catalog/source-image-facts-v1/private-cloud-replay-v1.json) pass **23/23** and [promo regressions](catalog/source-image-facts-v1/promo-regression-cloud-v1.json) pass **59/59** on the same revision. The **82 engineering checks include four repeated unauthenticated 403 denials**; these are not 82 independent collector scenarios. No transport errors or final logical failures are recorded. Three actual Node caller journeys use the existing ten-second timeout and two-attempt policy.

[Delivery bindings](catalog/source-image-facts-v1/delivery-validation-v2.json) verify runtime/snapshot/review hashes, private IAM, unchanged revision/image and all 52 inputs. **559 Python and twelve Node tests pass**, plus 21 new local checks, 57 promo checks and 105 artwork regressions. Nine fresh Gemini image-only calls follow recorded root inspections; root had prior batch/advisory context, explicitly disclosed. Four symbolic energy names and five literal names have correspondence advisories; Ho-Oh's visible HP 100 conflicts with pinned source HP 80. The original five number holds and all 79 number events remain unchanged. No identity, graph, copy or marketplace approval is upgraded. [Implementation, next 40 targets and scope](SOURCE_IMAGE_FACTS_20261003.md).

## Prior promo number revision `00035-bk8` — 2026-10-02

[Promo interface checks](catalog/promo-number-expansion-v1/private-cloud-replay-v1.json) pass **59/59** and [artwork regressions](catalog/promo-number-expansion-v1/artwork-regression-cloud-v2.json) pass **107/107** on the same revision. The **166 engineering checks include four repeated unauthenticated 403 denials**, not 166 independent collector scenarios. One HTTP connection error recovered through bounded retry in the final complete suite. Two earlier Node timeouts remain in the incomplete first run; fresh probes succeeded, but the cause is unestablished. The ten-second Node timeout and two-attempt policy remain unchanged. [Failure history](catalog/promo-number-expansion-v1/diagnostic-failures-v1.json).

[Delivery bindings](catalog/promo-number-expansion-v1/delivery-validation-v1.json) verify runtime/snapshot hashes, unchanged deployment revision, private IAM, image digest and all 51 ordered inputs. **549 Python and twelve Node tests pass.** The catalog has 79 exact-source number-evidence subjects: 74 usable, five held, zero stale. Twenty-five usable observations do not establish catalog denominators as printed text. The batch used 49 fresh Gemini image reviews after separately saved root reviews; root had prior project context, so this is not blind ground truth. Source image/name disagreements and an incidental Ho-Oh HP discrepancy remain explicit. No card identity, relationship, physical-copy or marketplace permission is upgraded. [Implementation and limits](PROMO_NUMBER_EXPANSION_20261002.md).

## Prior number evidence revision `00034-gvg` — 2026-10-02

[Number interface checks](catalog/number-readings-v1/private-cloud-replay-v1.json) pass **57/57** and [artwork regressions](catalog/number-readings-v1/artwork-regression-cloud-v1.json) pass **107/107** on this revision. The **164 logical checks include four repeated unauthenticated 403 denials**, not 164 independent collector scenarios. One first-attempt discovery connection error recovered through bounded retry and is retained; final logical failures are zero. Actual Node calls use the existing timeout/retry policy.

[Delivery bindings](catalog/number-readings-v1/delivery-validation-v1.json) verify runtime/snapshot hashes, unchanged deployment revision, private IAM, image digest and all 50 ordered inputs. Thirty observations are extracted from existing separate image inspections, not new AI reviews or card identity approvals. Cleffa's visible `037` is separate from catalog `037/225`; its prior artwork hold remains. Siblings do not inherit evidence. [Implementation and coverage](NUMBER_EVIDENCE_20261002.md).

## Prior artwork controls revision `00033-kkh` — 2026-10-02

[Current control deployment evidence](catalog/artwork-controls-v1/private-cloud-replay-v3.json) passes **107/107 checks**: fifty-four source-led authored questions, thirty unique structured pairs, six actual Node caller journeys, eleven negative-evidence neighborhoods, catalog status, three malformed request rejections and two unauthenticated 403 checks. Local/cloud semantic responses agree; no final transport errors are recorded. The first run's Node timeout and a later diagnostic report-path error remain recorded; the completed suite was rerun on the same immutable deployed image. [Failures and bindings](catalog/artwork-controls-v1/diagnostic-failures.json).

The [previous expansion](catalog/artwork-controls-v1/legacy-expansion-cloud-v1.json) passes **104/104** and the [six-comparison regression](catalog/artwork-controls-v1/legacy-six-cloud-v2.json) passes **32/32** on this same revision. [Delivery validation](catalog/artwork-controls-v1/delivery-validation.json) binds all three complete cloud reports and the local control report to current runtime/snapshot hashes and all 49 manifest inputs. Their **243 checks include six repeated unauthenticated 403 denials**; this is not a count of independent user scenarios. The first six-comparison attempt also recorded a Node timeout and remains in the failure record. Final complete replays contain no transport errors.

[Received request logs](catalog/artwork-controls-v1/cloud-latency-scope.json) sample 35 journey calls, all HTTP 200, with maximum service request latency 0.107 seconds. These logs do not locate the two client timeouts or establish end-to-end availability/latency. The existing ten-second Node client timeout and retry policy was retained.

Only eleven qualified exact-endpoint stock-image differences are newly imported. Six existing positive controls add no approvals, and one Cleffa promo-number mismatch stays held because its catalog denominator is not printed. A withdrawal/absent edge does not become a difference fact, stale/blocked endpoints fail closed, and sibling versions inherit neither positive nor negative artwork evidence. Catalog/source records and the previous 48 build steps remain preserved. **527 Python and twelve Node tests pass.** [Implementation, evidence and limits](ARTWORK_CONTROLS_20261002.md).

## Verified artwork expansion revision `00032-rdq` — 2026-10-02

[Prior expansion deployment evidence](catalog/relationship-expansion-v3/private-cloud-replay-v1.json) passes **104/104 checks**: fifty source-led multilingual questions, forty exact reviewed pairs, six actual Node caller journeys, three legacy scope guards, catalog status, two rejected malformed requests and two unauthenticated 403 checks. One transport failure recovered through bounded retry and remains recorded. The immutable deployed image and unchanged revision are bound in the report; local/cloud responses agree. This is a diagnostic across five wording patterns, not fifty independent language patterns or real-user accuracy.

The forty new pairs have source-hashed images and separately recorded root/OpenAI and Vertex Gemini 3.8 Flash reviews. They establish artwork-only evidence, with no physical-printing, condition, price or purchase approval. The latest graph has 63 verified pairs, 594 proposals and 36 identity-blocked proposals still held. All 47 prior build inputs and prior raw/evidence records remain preserved. [Review, scope and implementation](ARTWORK_EXPANSION_V3_20261002.md).

The [six earlier comparison cases rerun on `00032-rdq`](catalog/relationship-expansion-v3/legacy-six-cloud-v1.json) pass another **32/32 checks**, including two repeated unauthenticated 403 checks, with no transport errors. Across both reports there are 136 engineering checks and four authentication denials. The prior 160-check source-correction cloud suite was not rerun; its 82-question source regression was rerun locally. [Delivery bindings](catalog/relationship-expansion-v3/delivery-validation.json) verify current runtime/evidence/input hashes and preserve the earlier 47 build steps.

## Verified comparison revision `00031-l5p` — 2026-10-02

[Prior comparison deployment evidence](catalog/two-card-comparison-v1/private-cloud-replay-v1.json) passes **32 checks**: six structured comparisons, six natural-language questions, six bounded journeys, six actual Node caller responses, three rejected malformed requests, two single-number scope guards, catalog status and two unauthenticated 403 checks. Thirty requests are authenticated. Local and cloud responses agree; there are no recorded transport errors. All six questions expose their expected reviewed endpoints and three retain missing-release confirmation. No copy, physical-finish, price or purchase approval is added. These are development acceptance checks, not complete answers or real-user accuracy.

The new route is `POST /card-comparison`, gated by the internal catalog API and Cloud Run IAM. The same partial result is available under `collector-discovery` and the existing caller-owned journey. Runtime revision binding includes the comparison implementation, so previous selected journeys need reconfirmation. [Implementation and limitations](TWO_CARD_COMPARISON_20261002.md).

## Verified source-correction revision `00030-x8r` — 2026-10-02

[Prior source-correction deployment evidence](cloud-deployment-20261002-source-corrections-v1.json) verifies **160 authenticated logical requests** and two unauthenticated 403 checks. No transport errors were recorded in the final run. Local/cloud source responses, 31 graph responses, 14 exact card-detail responses, 82 authored query cases and source-family/numbered-part/inventory guards agree. The source-only 154 family cannot be selected through a broad query. The service remained on the same revision throughout verification; its image, runtime files and manifest hashes are recorded.

The [source correction and graph implementation](SOURCE_CORRECTIONS_AND_GRAPH_20261002.md) preserves all 45 earlier inputs and raw card/reference/facet/evidence rows. The first new question replay supports 22/24; the unchanged final expectations support 24/24 after card-ID language routing repairs. A separate legacy professor-inquiry regression was found and repaired; final 20 printing-source and 18 release-name checks pass. 494 Python and 11 Node tests pass, plus two additional focused cloud-comparison tests. These are engineering diagnostics, not blind marketplace or collector-answer accuracy.

The initial cloud catalog-detail comparison stopped on a different rarity-overlay application time. [Both original responses and the sole difference](cloud-verification-20261002-source-corrections-card-difference-v1.json) remain recorded. The final comparator excludes only that import bookkeeping time, validates its card binding and retains both original values; all source/review/evidence timestamps and fields remain compared. No deployed data or runtime changed for this diagnostic repair.

Raw research images/pages, review queues and authored questions are excluded from the runtime image; only frozen metadata/evidence records are imported. Pivota registration, authorized live ingestion, managed market storage and real-title/variant/grade calibration remain open.

## Prior priorities revision `00029-9cn` — 2026-10-02

[Prior deployment evidence](cloud-deployment-20261002-next-priorities-v1.json) verifies **100 authenticated logical requests** and two unauthenticated 403 checks, Two first-attempt transport errors succeeded on bounded retry; no final logical failures remain. The diagnostic checks 20 family regression questions with complete pagination, 20 printed-source questions, 18 release-name queries, eight synthetic inventory cases, nine family-copy blockers, four numbered-part blockers, eleven graph responses and input/status guards. The same 18 release questions initially passed 11/18; after routing fixes all 18 pass. Three reviewed artwork edges and three disabled-identity proposal scopes are included in the graph checks.

The manifest preserves all 41 earlier inputs and immutable card/reference rows. It adds 21 total release evidence records, 42 vocabulary rows, 14 current printing-source observations, nine holds, ten separately evidenced printed credits and three verified artwork-only events. The eleven family-copy holds and ten conflict facets stay blocked/excluded. Graph evidence/current endpoint drift invalidates relation use and stale conversation revisions. Physical finish, actual seller copies, price equivalence and live-offer permissions remain unverified/disabled.

**470 Python tests and 11 Node tests pass.** [Integrated local replay](catalog/printing-source-pilot-v1/final-integration-rehearsal-v1.json) and [integration validation](catalog/printing-source-pilot-v1/integration-validation-v1.json) retain first-run failures, source hashes and scope. These checks establish private staging behavior, not blind marketplace precision, complete collector-answer accuracy or deployed Pivota service registration. Raw research pages/images, review queues and question artifacts are excluded from the runtime image; only frozen evidence/metadata rows are imported. The intermediate `00028-pq2` rollout was superseded after seven alias-routing failures were fixed; its diagnostic was not accepted as the final deployment.


## Prior coordinate-family revision `00027-z58` — 2026-10-02

[Current deployment evidence](cloud-deployment-20261002-coordinate-families-v1.json) verifies **56 authenticated logical requests**: 20 constructed questions with complete pagination, eight synthetic inventory checks, nine coordinate-family journey blockers, four numbered-part blockers, five graph responses and status/input/query guards. A broad SV8A query followed by direct selection of an unresolved family member returns 400, so browsing cannot bypass copy evidence. The 41-input manifest matches 2,497 active single-reference metadata records, 269 supported coordinate families and eleven explicit holds; no stale family evidence appears. Original supported targets remain 100 and automatic live-offer approval remains zero. IAM is private; two unauthenticated checks return 403.

Family metadata is separate from per-variant metadata: official pages are not assigned to a physical finish/edition, source snapshots remain unchanged and full membership/reference drift invalidates the proof. The new family evidence and runtime module are included in journey revision binding. The deployed source/manifest hashes and image digest are recorded. 439 Python tests and 11 Node tests pass. Read-only catalog operation, non-root runtime, external market-state requirements and default-disabled Pivota integration remain as described below. See [the source-family and whole-catalog review](CATALOG_COVERAGE.md).

## Prior Japanese expansion revision `00026-9lt` — 2026-10-02

[Prior deployment evidence](cloud-deployment-20261002-japanese-metadata-v2.json) records the image digest, runtime/manifest hashes and **48 authenticated logical requests**: full pagination of 20 constructed questions, eight synthetic inventory checks, four numbered-part journey blockers, seven graph checks and status/input/query guards. Metadata counts match the 40-input manifest: 2,497 active records, 1,900 known rarity declarations and four numbered-part records. No stale metadata appears. Original supported targets remain 100; automatic live-offer approvals remain zero. IAM remains private and two unauthenticated requests return 403. No transport errors were recorded.

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

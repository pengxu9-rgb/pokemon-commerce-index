# Active build sequence — 2 October 2026

## Product objective

Help a collector explore Pokémon cards, choose an exact printing, compare fresh authorized offers and destination-specific landed costs, and hand the selected URL/quote to Buy&Ship. Merchant recommendations must explain their price and condition evidence; reliability scores require fulfillment outcomes.

The [holistic alignment decision](HOLISTIC_ALIGNMENT_20260930.md) is the current plan. The [independent adversarial review](ADVERSARIAL_ALIGNMENT_REVIEW_20260930.md) challenges its assumptions and the implementation. Earlier review rounds and question cohorts remain historical diagnostics, not competing current schedules.

## Current implementation

The 1 October catalog expansion adds 14,838 source-declared English versions, enriching 9,135 existing number groups and adding 26 new groups. See [coverage and Japanese follow-up](CATALOG_COVERAGE.md). Two metadata batches are now delivered: 2,497 exact official Japanese coordinate records, 1,900 recognized rarity declarations and 597 undeclared. The second batch adds 1,497 records across 13 releases. Four numbered-part pages preserve copy blockers. Ten printed artist credits now have source-scoped corrections; raw HTML/seed conflicts remain visible. This enriches existing records and does not expand physical-printing or offer permissions. The 280-group follow-up now yields 269 official coordinate families and eleven explicit holds, including a wrong-reference number. Whole-catalog and graph quality findings are recorded in [CATALOG_COVERAGE.md](CATALOG_COVERAGE.md). Live feed work remains held for Buy&Ship.


| Layer | Evidence | Main remaining gap |
|---|---|---|
| Catalog | 70,006 internal source-version/family records; 45,438 language/set/number groups; 33,543 structurally eligible; 532 original official rarity corrections plus 2,497 separately versioned coordinate metadata events plus 269 official coordinate families and eleven held groups; 100 original supported metadata targets, 21 release overlays and 42 vocabulary records | Physical finish/copy evidence and real listing precision remain unverified; supported metadata does not approve automatic joins |
| Graph | Character/artist facets covering 40,666 / 45,510 records, explicit coauthor retrieval and four numbered-part guards, structural version neighbors, three official evolution families; 657 latest artwork-pair states: 63 reviewed artwork agreements and 594 proposals; 13 active official collector declarations and 142 proposed visual findings | Independent depiction and broader artwork coverage, localization counterparts and exact printing coverage; artwork-only approvals, no price/printing equivalence |
| Bilingual retrieval | 122 reviewed aliases and 460 review events included in the new ordered deployment manifest | Translation evidence is not printing equivalence; real marketplace vocabulary recall remains unmeasured |
| Agent discovery | Authored 30-task replay; first source cohort has 16 qualified questions; a second fresh 30-question cohort has eight catalog partials and 22 evidence blockers; stateless inventory comparison; 20 bounded collector journeys / 59 prefix requests; Node caller and eight new source-led development journeys | Active Pivota registration/service identity, artwork/region/printing evidence and an independent held-out outcome evaluation; no real-user answer quality score |
| Pricing | Observation/resolution/index contracts; ask, last-list-at-transition and paid amounts separate | Zero live observations; separate authorized listing feed, real matching audit and sustained freshness |
| Merchant/checkout | 100-target synthetic ingestion rehearsal; complete quote, restart, expiry and URL preview checks; Pivota contract | Real offer-bound quotes, condition/fulfillment evidence, confirmed payment/order lifecycle |
| Cloud | Recorded private read-only catalog deployment | Recoverable market/session storage, ingestion/retention scheduling and monitoring before live use |

Public card display approvals remain zero. Catalog-only internal work can proceed; a public shopping product cannot yet launch.

Implementation evidence and commands: [SUPPORTED_DISCOVERY_IMPLEMENTATION.md](SUPPORTED_DISCOVERY_IMPLEMENTATION.md). The 100 targets deliberately cover one audited modern release (SV4A). Their finish labels remain pinned-source declarations. This is a narrower metadata milestone than a physical-printing allowlist. The original physical verification gate is still open.

## Next sequence while Buy&Ship's feed is unavailable

### 1. Make one identity slice dependable

Select 100 modern Japanese exact-printing targets and the English identities required by collector journeys. This is an engineering cohort, not measured market coverage.

- Add an explicit, evidence-backed supported allowlist; omitted/unverified eligibility must fail closed through imports, migrations and re-imports.
- Audit each supported name, release, number and physical variant. Correct known release metadata conflicts, including SV4A's set title, using official evidence.
- Add sourced printed codes, localized set names and marketplace aliases shared by discovery, matching and feed queries.
- Include selected reviewed bilingual aliases and their review events in an ordered manifest. Translation is not printing equivalence.

**Done when:** every supported target has positive evidence and no unresolved identity conflict, ambiguity abstains, and local/container/staging membership and alias counts agree.

### 2. Execute collector discovery tasks

Connect natural-language facts to an actual result: exact-card clarification, character/artist retrieval, a scoped cross-language family checklist, structural printing neighbors and separately labelled artwork/counterpart evidence. Record sources and omissions; unknown dates and unsupported cameos remain visible.

Reuse existing graph primitives. AI can collect evidence and review routine cases; disagreement escalates and confident approvals also need a random audit. AI agreement is not an accuracy score. Keep weak links proposed under the existing verification policy.

Fix mixed planned-purchase/resale facts only enough to preserve the task and avoid invented paid costs. Defer broader selling economics, store directories and another generic taxonomy round.

**Done when:** a frozen 30-question suite tests returned card IDs/results and useful clarification, with a proposed internal target of 27 useful outcomes and zero unsupported market, same-printing or completeness claims. This is task acceptance, not population accuracy. Hand-authored structured constraints alone do not satisfy it.

**Development implementation delivered:** raw authored questions execute without manual fact translation; the first run was 28/30 and retained, and the corrected replay is 30/30. A second fresh source-qualified diagnostic now has 30 originals (18 English, 12 Japanese); first runtime 7/30, corrected replay eight catalog partials plus 22 evidence blockers. The sampling-size milestone is met, but source selection and fixes were performed with knowledge of the implementation. This is not an independent held-out acceptance measurement or evidence of complete answers. Stateless owned-inventory comparison is implemented without physical ownership claims or persistence. See [the implementation and diagnostic](COLLECTOR_INVENTORY_IMPLEMENTATION_20261001.md).

### 3. Rehearse the commerce path on the same slice

Exercise exact target → normalized offer → immutable observation → versioned resolution → fresh ask → bound landed quote → price-only recommendation → Buy&Ship URL preview with explicitly synthetic fixtures. Verify mutation, expiry, unknown costs, bundles and ambiguous condition behavior.

Add recoverable storage, bounded retry/quota controls, freshness monitoring and permission-driven retention cleanup before scheduled live ingestion. Cloud Run's catalog file remains a read-only snapshot; it cannot persist observation or session writes.

**Done when:** a source-independent rehearsal produces a fully traceable recommendation or a specific evidence blocker, survives restart/retry, and does not present fixtures as live prices.

**Offline rehearsal delivered:** 100 synthetic listings resolve to the same target coordinates; 14 checks cover restart/replay, conflicting observations, bundles, condition separation, missing costs, quote expiry/invalidation, freshness and retention. A persistent operator-owned SQLite queue now reserves source call budgets before adapter calls, leases work and bounds retries. It has no enabled live adapter or cloud schedule. Managed durable storage, operational monitoring and provider-specific quotas remain necessary before live ingestion.

## Next implementation and measurement

The second Japanese metadata batch is complete. Ten printed artist credits now have scoped corrections. Continue the excluded source-name and multiple-version cohorts. Gemini search was requested; returned advisory text lacked grounding evidence and the remaining calls timed out. The original conflicts remain visible while exact printed corrections participate in retrieval. The 597 pages without a rarity icon retain an explicit unknown. See [the batch audits and reproducible build](CATALOG_COVERAGE.md). That metadata-only milestone used 40 inputs, 433 Python / 11 Node tests and 48 private-staging logical checks. The 280-group follow-up is now audited. The current corrections manifest has 47 ordered inputs; the integrated suite passes 494 Python and 11 Node tests. These figures do not measure listing precision.

1. The source-bound evidence expansion now has 100 frozen image targets across seven Japanese releases: 94 qualified reviews, six excluded/unresolved targets, a deterministic ten-image Codex audit and fresh Gemini replication. The ledger has 190 historical events, 13 active official declarations and 142 active AI proposals; eight cameo scopes return official-description partials. Three official named cameos were still omitted by the fresh model, and four Codex sample cases show positive differences/uncertainty. Keep AI findings proposed and require exact card/copy evidence for finish or edition approval. Scoped discovery and inventory are now connected through caller-owned multi-turn replay; see [the journey implementation](COLLECTOR_JOURNEY_IMPLEMENTATION_20261001.md). Preserve the first 2/16 and second 7/30 initial outputs; further acceptance measurement must use held-out questions. See [the expansion and calibration](COLLECTOR_EVIDENCE_EXPANSION_20261001.md).
2. The controlled journey now has a dependency-free Node caller and a default-disabled, caller-authorized `collector.explore` wrapper, prepared for Pivota registration. Eight newly opened source situations produced a frozen 26/37 first run, then 33/37 on unchanged expectations after intent repairs. Two declared fixture defects were repaired and two recovery steps added; all 39 revised development steps pass through real HTTP. All 59 original journey prefixes and 30 original question memberships/tasks remain unchanged; 412 Python and 11 Node tests pass. See [the caller implementation](PIVOTA_COLLECTOR_ADAPTER_20261001.md). Confirm the current Pivota repository/entry and service identity, register the operation, then exercise the authenticated agent entry. Operator-token staging checks do not establish deployed Pivota integration. Independent question selection/labels/outcome measurement remain open. Keep unknown versions, AI leads and unsupported exclusions blocked. Independently evidence physical finishes before any live-offer approval; current automatic-live-join-ready count remains zero.
3. Select managed market storage and a separate ingestion worker deployment. Add provider-specific adapter, pagination, request timeout, quota and retention behavior only against the confirmed feed contract. Keep market/session state outside the read-only catalog image.
4. Execute the external feed and real-listing gates below when access arrives. No catalog totals or fixture scores substitute for them.

## Holistic decision after the quality audit

We currently have a private catalog and evidence-aware collector discovery service. Price, landed-cost and merchant/transaction libraries exist as offline contracts and rehearsals; the cloud image is read-only and contains zero market observations. The product objective remains the original canonical identity → authorized ask index → destination landed cost → merchant comparison → Buy&Ship handoff. The discovery graph helps choose the target before that commerce path begins.

Structural integrity is good, and internal character/artist retrieval is usable. Overall semantic/physical-printing accuracy has not been measured independently. Coverage is uneven: 20,090 records carry unverified version labels. Following 18 official release overlays, 7,745 Japanese records lack names and 8,114 lack dates across 200 remaining gap groups; three newly named scopes retain unknown dates. A total of 70,006 records does not establish a complete physical catalog. Official coordinate-family evidence and actual printing/copy approval must remain distinct.

The relation graph supports same-character, artist and structural sibling retrieval. Its 657 latest artwork-pair states contain 23 artwork-only agreements from separately saved actual agent inspections and 634 proposals. There are still zero verified localization counterparts; 36 proposals involve match-disabled endpoints and remain held. Those pairs are review candidates and cannot support price-series merges or claims of identical regional printing. The next graph milestone is a frozen, independently reviewed artwork cohort with explicit region/printing/finish scope and uncertainty escalation, followed by fresh collector-task evaluation. Increasing edge counts alone is not an acceptance gate.

### Quality-first next sequence

1. Prioritize the 215 release metadata gaps and localized set-code aliases, starting with high-volume catalog groups and user-query relevance. Record source-backed names and unknown dates separately; no fabricated date or market-volume priority.
2. Resolve the remaining physical-copy requirements for eleven family holds. Ten artist conflicts now have exact printed-card corrections, two professor subtitles are scoped, and the wrong 153/154 reference has a preserved correction. Establish an explicit printing cohort with positive finish/edition evidence. Keep the current family copy blockers and stale-proof checks.
3. Freeze a source-bound subset of artwork pairs, including the 36 match-disabled cases. Obtain distinct independent reviews, adjudicate conflicts and keep confidence tiers separate from price equivalence. Shared character/artist metadata is already retrieval-useful and need not wait for artwork approval.
4. Evaluate new collector questions selected independently of the implementation: edition/region clarification, scoped checklists, characters/artists, alternative artwork and uncertainty handling. Development replays are regression evidence, not population accuracy.
5. When the authorized feed arrives, add managed durable observation storage, real listing/copy/grade calibration and a narrow fresh ask pilot; then attach actual landed quotes and Buy&Ship URL handoff. Sweep-fidelity Gate 1 still governs any sale/clearing-price claims. Fulfillment outcomes precede reliability scoring.

Evidence and reproducible audit: [whole-catalog report](catalog/coordinate-family-evidence-v1/whole-catalog-quality-v2.json). No public shopping launch or automatic live-offer approval is implied.

## When external access arrives

1. Confirm source-specific discovery/search, detail, stable IDs, statuses, quota, storage/display/statistics/media-AI scope and partner URL support. Run actual Gate 0 probes. Buy&Ship's URL-to-quote API is a separate transaction capability, not a listing feed.
2. Freeze an authorized real listing sampling frame and evaluate exact printing/grade precision. Use [AI-first review](AI_FIRST_REVIEW.md) plus uncertainty escalation and random approval auditing. The [existing proposed gate](BLIND_LISTING_BENCHMARK.md) requires at least 300 fully evaluable accepted joint labels, a Wilson 95% lower bound of at least 0.98, and zero accepted multi-card listings. Preserve failures, unknowns and abstention in reporting.
3. Run a narrow ask-only pilot with exact units, source, sample count, timestamp and freshness. Attach live destination-specific landed quotes where available.
4. Run the original sweep-fidelity Gate 1, including sample-size and panel-representativeness checks, before transition-price or liquidity claims. A passed sweep does not establish paid prices; those require settlement evidence.
5. Connect Pivota's agreed identity/offer/quote contracts and confirmed checkout lifecycle. Fulfillment evidence and calibrated condition assistance precede comprehensive merchant ranking.

## Main progress measures

Track source-backed supported printing coverage, useful executed collector outcomes, independently evaluated graph coverage, real exact-unit match precision/abstention, fresh offer coverage, valid landed quotes and eventual sale/fulfillment evidence. Catalog totals, AI agreement and engineering test counts are supporting diagnostics.

Detailed rationale, acceptance criteria and evidence: [HOLISTIC_ALIGNMENT_20260930.md](HOLISTIC_ALIGNMENT_20260930.md), [SQL evidence](HOLISTIC_ALIGNMENT_EVIDENCE_20260930.json). Earlier plan: [ASTRA_REVIEW_AND_PLAN.md](ASTRA_REVIEW_AND_PLAN.md). Earlier independent review response: [INDEPENDENT_REVIEW_RESPONSE.md](INDEPENDENT_REVIEW_RESPONSE.md).

## Dispatched implementation — 2 October 2026

Three agents delivered the next priorities and the root integrated them into [`catalog-build-manifest-priorities-v1.json`](catalog-build-manifest-priorities-v1.json).

- **Release metadata:** 18 exact Japanese release scopes, 2,043 existing records, 15 product dates and three explicit unknowns; 36 name/code vocabulary rows. [Source audit](catalog/release-metadata-next-v1/README.md). Mixed-product XY scope is held; no promo date is invented.
- **Relationship review:** a frozen 39-pair cohort, including all 36 disabled-identity cases, with 78 pinned source-byte checks. Three controls have separate actual image inspections and three verified same-artwork events. Both agents inherit the same model; this is not an independent population accuracy score. Full reviewed endpoint snapshots and current identity blockers now guard imports, retrieval, number explanations and price comparisons. History remains append-only. [Review result](catalog/relationship-independent-priority-v1/review-summary.json).
- **Printed source evidence:** 23 events: 14 source observations and nine holds. Fourteen official images were inspected twice, exposing ten exact printed credits, two professor sublabels/stamps and the wrong 153/154 reference. Two finish declarations stay at release scope. The ten source-conflict discovery facets and eleven family copy holds stay excluded/blocked pending scoped corrections; separate printed facts are available in catalog responses. [Pilot and chronology](PRINTING_SOURCE_PILOT_20261002.md).

Initial diagnostics are retained: the source-fact replay starts at 5/20 before ledger data and reaches 20/20 for first-page fact visibility/abstention; official release-name retrieval initially reaches 11/18 and exposes seven routing failures; the unchanged 18-case replay now passes 18/18 after scoped routing repairs. Genuine gameplay requests and ambiguous titles remain blocked/clarified. These are authored development cases, not held-out real-user acceptance. No listing, paid transaction, fulfillment outcome, physical printing approval, display permission or automatic live-offer approval is added.

At this earlier priority milestone, the planned data work was an immutable, source-scoped credit correction for the ten inspected credits; exact printed-subtype aliases for the two professor cards; and a traceable correction of 153's misassigned 154 reference. Broader artwork review should scale from source-qualified coordinate candidates, while exact finish/copy mapping remains a separate gate.

The prior priority revision `pokemon-commerce-index-00029-9cn` passes [100 authenticated logical checks](cloud-deployment-20261002-next-priorities-v1.json); two unauthenticated calls return 403, with two first-attempt transport errors resolved by bounded retries. The unchanged 18 release queries now pass 18/18. All 41 earlier manifest inputs and immutable card/reference rows are preserved. These are engineering regressions, not live-marketplace or independent population accuracy.

## Source correction and artwork follow-up — 2 October 2026

[Implementation and evidence](SOURCE_CORRECTIONS_AND_GRAPH_20261002.md) now deliver 13 append-only corrections, one new source-only 154/SV-P family and 20 additional separately inspected artwork pairs. All 45 earlier inputs and original card/reference/facet/evidence rows remain unchanged. Effective artist coverage is 45,510; artwork heads are 23 verified and 634 proposed. Physical copy/price/automatic offer approvals remain zero.

The 24 frozen new development questions initially support 22 expectations; after fixing card-ID language inference, all 24 pass. A legacy regression in two generic professor inquiries was also found and fixed, preserving its failed report. The final combined replay covers 20 family questions, 20 printing questions, 18 release queries, 31 graph responses and 14 exact catalog records. 494 Python and 11 Node tests pass. These counts are engineering diagnostics, not independent population or real-listing accuracy.

The historical mixed-question diagnostic yielded five clarifications and one market blocker. The [new two-card comparison flow](TWO_CARD_COMPARISON_20261002.md) now exposes separate number namespaces, reviewed exact stock-image endpoints and remaining variant/market uncertainty. Six source-led authored questions meet their frozen expectations; three still require release confirmation. No physical-printing or market approval follows from artwork. Continue qualified graph review and fresh question checks; live ask indexing and Buy&Ship handoff await an authorized listing feed and real-title calibration.

The new structured tool is internal and read-only. The existing Pivota caller can pass nested comparison partials, rejects nested commerce approvals and does not issue a target intent from comparison results. The full suite passes 509 Python and 12 Node tests; local HTTP and actual Node caller checks pass 30/30. Existing source regression still preserves 82 queries, 31 graph results and 14 exact card details. These remain engineering checks, not held-out real-user or marketplace accuracy.

Private staging revision `pokemon-commerce-index-00031-l5p` passes [32 comparison checks](catalog/two-card-comparison-v1/private-cloud-replay-v1.json), including 30 authenticated requests and two unauthenticated 403 denials. The catalog build inputs and live-data permissions are unchanged. The 160-check source-correction cloud run below records the prior revision, not a repeat of that complete suite on the new revision.

## Two-model artwork expansion — 2 October 2026

[Forty additional source-bound pairs](ARTWORK_EXPANSION_V3_20261002.md) across twenty Japanese releases now have separately recorded root/OpenAI and Vertex Gemini 3.8 Flash image reviews. Eighty source files and image hashes were checked. The graph has 63 verified artwork-only pairs and 594 proposals; thirty-six blocked-identity proposals remain held. This positive-enriched cohort establishes neither population accuracy nor physical-printing/price equivalence.

Fifty source-led questions across five wording patterns initially meet 44/50 expectations; six failures exposed decimal release codes matching shorter prefixes. The fixed code preserves the original questions and passes all fifty scope expectations. Local HTTP/caller verification passes 102 checks, the full suite passes 513 Python and twelve Node tests, and existing source/copy guards remain intact. The ordered build now has 48 inputs, preserving all 47 earlier inputs and raw/evidence rows. Next: source-qualified different-artwork controls, broader wording and ambiguous-version cases, then qualified coverage expansion. Live feed calibration remains gated on Buy&Ship.

Prior private staging revision `pokemon-commerce-index-00032-rdq` passes [104 expansion checks](catalog/relationship-expansion-v3/private-cloud-replay-v1.json) and [32 prior comparison checks](catalog/relationship-expansion-v3/legacy-six-cloud-v1.json). Both reports include two unauthenticated 403 denials; one transport failure in that expansion replay recovered through bounded retry. Local/cloud responses agree. The earlier 160-check source-correction suite remains historical revision `00030-x8r` evidence.

## Artwork difference and version calibration — 2 October 2026

[Implementation](ARTWORK_CONTROLS_20261002.md) adds eleven source-qualified artwork differences, retains six existing positive controls and holds one unconfirmed promo coordinate. Current pair heads comprise 63 verified same-artwork pairs, 594 proposals and eleven differences; 36 blocked proposals remain held. The 49-input manifest preserves the earlier 48 steps, raw/evidence tables and 720 graph events. Neither sibling variants nor actual-copy/price permissions inherit artwork findings.

The frozen question diagnostic initially routes 47/54 against the correct API task name; an original task-label spelling error is separately preserved/corrected. Chinese “比较” and alphanumeric exact IDs now route correctly, with all 54 scopes supported. Final local checks pass 105/105; 527 Python and twelve Node tests pass. Existing 82-question source regression and forty-pair/six-case comparison checks are retained.

Current private staging `pokemon-commerce-index-00033-kkh` passes [107 control checks](catalog/artwork-controls-v1/private-cloud-replay-v3.json), including two unauthenticated 403 denials. The previous expansion and six-comparison cloud suites also pass 104/104 and 32/32 on this revision: [243 checks across three completed suites](catalog/artwork-controls-v1/delivery-validation.json), including six repeated unauthenticated 403 denials. Two earlier Node timeouts and the diagnostic report-saving error are preserved, followed by complete reruns. Received-service request logs do not locate those client timeouts or establish end-to-end reliability. Next priority: separate source catalog numbering conventions from observed printed text, then expand harder artwork/version controls and independently sourced question wording. Buy&Ship feed and production Pivota registration remain pending.

## Number evidence layer — 2 October 2026

[Implemented separation](NUMBER_EVIDENCE_20261002.md) preserves raw identities and graph decisions, labels the legacy `printed_number` as a catalog coordinate, and adds thirty exact source-image number observations. Twenty-nine agree with catalog text; Cleffa only supplies `037`, so `/225` remains unobserved and its artwork hold remains. All sibling/version and physical-copy/price boundaries persist. The 50-input manifest preserves the prior 49 steps.

The next research queue contains fifty source-labeled promo coordinates, 25 per language, awaiting actual image readings. Expand that evidence and separately establish inventory-to-printed-number mappings before broadening promo-number matching. Do not infer new artwork edges from number agreement.

Private staging `00034-gvg` passes 57 number checks and 107 artwork regressions, including four repeated 403 denials. [Delivery binding](catalog/number-readings-v1/delivery-validation-v1.json) retains the one recovered discovery transport error and proves current runtime/snapshot/input hashes. Full tests pass 541 Python / 12 Node.

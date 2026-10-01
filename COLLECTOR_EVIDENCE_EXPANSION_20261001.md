# Collector evidence expansion and AI calibration — 1 October 2026

## Delivered

The frozen research cohort now contains **100 Japanese card identities across seven releases**, including SV-P promos. It repeats the initial 20 targets and adds 80 targets from SV2A, SV4A, SV5K, SV5M, SV6 and SV8. This is purposive artwork research, not new catalog SKUs or measured market coverage.

The new Gemini pass completed 96 parsed reviews. **94 passed the exact printed identity checks.** Three request failures, one image-fetch failure and two printed-text mismatches remain excluded and visible. The mismatches include spacing in an Ogerpon name and a collector number returned with a trailing rarity; they were not silently repaired. Both previously failed SV2A reviews completed in the new packet. The original failures remain unchanged in v1.

The append-only ledger now contains **190 historical events, with 13 active official source declarations and 142 active AI proposals**. The packet adds 146 events, including explicit revisions of the original proposals. Four new official-caption facts describe subjects and cameos on two exact illustrations:

| Exact catalog record | Subject | Officially described cameo |
|---|---|---|
| `ja:SV6:109/101:holo` | Timburr | Gurdurr |
| `ja:SV4A:339/190:holo` | Palafin | Finizen |

Codex read the preview names/numbers and inspected both illustrations. The compiler checks the adjacent official captions, hashes their preview assets, and binds the claims to the official card-detail page and pinned image. These are source-supported artwork facts; the catalog's `holo` label is not independently certified physical finish.

Eight cameo scopes now have official-description partials. English and Japanese Gurdurr/Finizen queries work, and the stateless inventory comparator handles their partial scopes. Requested release, number, language and finish still constrain both confirmed results and AI leads. Mew remains an AI-only lead, even with AI agreement.

The catalog remains 55,167 internal identities, with 100 supported metadata targets. Public display, verified card-pair relationships, automatic live-offer approvals and real market observations remain zero. Twelve of the 13 official declarations concern depicted Pokémon; one is the earlier release-level Poké Ball finish declaration.

## What the audit found

The Gemini pass enumerated each scene afresh without previous findings. It shares the earlier model family and is **replication, not independent model validation**. Of the 18 prior valid reviews, 15 returned the same positive species/role set and three changed. A repeated set is not an accuracy score.

A separately frozen, deterministic hash sample selected ten of the prior 18 valid reviews. Codex inspected the images and wrote its findings before opening the Gemini findings. The reviewer knew prior official captions, so this is an AI sample audit with disclosed context, not a fully blinded human benchmark. Four sampled illustrations have positive identification differences or unresolved details. Omitted species are not negative labels.

The fresh model still did not return three official named cameo facts: Jigglypuff on SV2A 173, Gurdurr on SV6 109 and Finizen on SV4A 339. Official descriptions support these facts independently of model enumeration. On the Palafin illustration, the model supplied other species instead; those remain proposals. AI agreement therefore cannot replace source checks or resolve shared omissions.

Each revised proposal carries its replication result and, where sampled, Codex support/uncertainty. Findings missing from the fresh pass receive a new audit annotation without being erased or treated as absent. All image-only findings remain `proposed`.

## Reproducibility and verification

Before model work, the runner freezes queue, prompt template, runtime file hashes, source revision, model, project/location and bounded concurrency. Resume refuses changes to that protocol. Received model responses are retained, including malformed responses; requests, authorization tokens and image bytes are not committed. The research limit is 100 cards per frozen run with three concurrent workers.

The [35-input manifest](catalog-build-manifest-evidence-v2.json) imports v1 followed by the new append chain and asserts all output counts. Only event packets enter the runtime image. Research queues, responses, audits and images are excluded from the container. Runtime discovery has no model/network calls.

Verification:

- 391 engineering tests pass, including protocol-resume and duplicate/truncated-output rejection.
- All 30 frozen source questions retain their original card memberships and tasks. Enriched evidence context changes are declared; this is not a held-out acceptance score.
- The expansion rehearsal checks 14 bilingual/scoped queries and four synthetic inventory cases. It preserves the catalog bytes and confirms that physical/market approvals remain disabled.
- Private staging revision `pokemon-commerce-index-00019-lxn` serves the new manifest. See [cloud verification](cloud-deployment-20261001-expansion-v1.json) for authenticated equivalence and private IAM checks.

Research, exclusions and comparisons: [compiler audit](catalog/collector-evidence-v2/build-audit.json), [Codex audit](catalog/collector-evidence-v2/codex-visual-audit.json), [calibration and rehearsal](catalog/collector-evidence-v2/expansion-rehearsal.json). The [initial evidence implementation](COLLECTOR_EVIDENCE_IMPLEMENTATION_20261001.md) remains a record of the first packet.

## Next sequence

Connect these scoped results and stateless inventory comparison to the controlled multi-step collector journey. Keep evidence tier and unresolved versions visible before selecting a purchase target. Prioritize disputed background figures and exact printing evidence; expanding AI proposal totals alone does not approve counterpart pairs, physical variants or offers. Authorized feed, fresh quotes, copy-condition evidence and confirmed Buy&Ship checkout remain the commerce gates.

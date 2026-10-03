# Thousand-target source-image screening — 3 October 2026

## Completed scope

All **1,000 previously frozen targets** have an explicit outcome: fifty distinct coordinates in each of twenty releases, Japanese/English 500 each. Selection is deterministic, not random, demand-weighted, or a marketplace precision benchmark. All pinned source files and current endpoint snapshots were checked.

First acquisition returned 832 image files; publisher-reference recovery raised this to 962 files. Decode checks found ten damaged transfers. A fresh recovery pass yields **976 decodable images (476 Japanese, 500 English) and 24 unavailable assets**. Original acquisition/decode failures are retained. The missing assets are three S8B V-UNION parts and twenty-one M6A entries, including two filename/numerator discrepancies. Missing images remain unknown.

This batch uses **Apple Vision image-only OCR plus Vertex Gemini 3.8 Flash image-only reading**. It is an initial screening tier, **not OpenAI plus Gemini dual image-model review**. Native inputs contain only target id, image path and language; expected titles, collector numbers, HP and custom vocabulary are absent. All 976 native results and derived literal readings were frozen before Gemini's protocol began. Gemini receives neither catalog fields nor previous readings or search tools.

The initial three-worker process was paused after 137 completed attempt records, preserving its outputs. The remaining 839 subjects resumed at bounded concurrency with request-start ledgers. Eleven transport failures were retried separately. There are **987 completed attempt records: 976 valid structured replies and eleven transport failures**. Up to three interrupted in-flight outcomes were not saved; total billable API calls is unknown. Every original result, retry and selected record hash is retained. No disagreement was retried merely to obtain a preferred answer.

[Acquisition history](catalog/source-facts-thousand-v1/assets-v4.json), [frozen OCR protocol](catalog/source-facts-thousand-v1/vision-protocol-v1.json), [chronology](catalog/source-facts-thousand-v1/chronology-and-tests-v1.json), [attempt selection](catalog/source-facts-thousand-v1/gemini-attempt-selection-v2.json).

## Results and limitations

| New-batch observation | Subjects |
|---|---:|
| Full catalog-number text with corresponding names in both channels | 670 |
| Number initial-screening holds | 306 |
| No bound source image | 24 |
| Source-title correspondence advisories | 743 |
| Source-title unconfirmed | 233 |
| Both channels' HP agree with pinned source | 440 |
| Both channels observe absent HP headers | 2 |
| HP unconfirmed | 534 |

English targets yield 443 scoped number correspondences; Japanese targets yield 227. This difference concerns native OCR screening yield and missing scans, not verified correctness or demand.

These columns overlap and are **not an accuracy score**. Native engine confidence is uncalibrated. A failed OCR reading does not prove a catalog error. No new paired HP conflict or agreed-but-different number was found in this selected batch; unknown fields remain unknown.

Literal text and structured comparisons remain separate. A targeted repair normalizes only a trailing mixed-case OCR `eX` into `ex` in the comparison structure. Raw readings remain intact. Legacy uppercase `EX`, `GX`, `V`, trainer ownership, missing mechanics and symbol placement remain distinct. Tests specifically guard those boundaries; the comparison repair does not identify a physical printing.

**SV2A is the clearest next priority:** all fifty selected subjects have number holds because the native first reader did not supply an accepted fraction. Root viewed one actual Squirtle source image after seeing both readers: `ゼニガメ`, `007/165 C`, HP 60 are visible, while native OCR assigns low confidence to the footer. This is one disclosed diagnostic, not an independent review or proof of the cause across all fifty. It adds no evidence event, physical foil assignment or approval. The displayed source scan's repeated Poké Ball motifs do not verify a seller's copy.

[Release breakdown](catalog/source-facts-thousand-v1/batch-breakdown-v2.json), [all thousand number outcomes](catalog/source-facts-thousand-v1/number-compilation-v1.json), [title/HP outcomes](catalog/source-facts-thousand-v1/compilation-v1.json), [context-disclosed actual-image spot check](catalog/source-facts-thousand-v1/contextual-image-spotcheck-v1.json).

## API and cumulative state

Card details and comparison evidence now expose `inspection_tier`. Catalog status separates OCR screening subjects and agreements from two image-model subjects and agreements. An OCR agreement is never counted as a newly completed OpenAI/Gemini review. All identity, physical printing, price, display and automatic-offer approvals remain false.

The [57-input manifest](catalog-build-manifest-source-facts-thousand-v1.json) preserves all 55 ordered prior inputs and hashes, appending 976 number events and 976 source-fact events. Cumulative totals:

| Layer | Current total |
|---|---:|
| Catalog source records / language-set-number coordinates | 70,006 / 45,438 |
| Structurally eligible catalog records | 33,543 |
| Source-fact subjects: two image models / OCR screening | 148 / 976 |
| Title advisories: previous / new initial screening | 147 / 743 |
| Number subjects: two image models / OCR screening | 178 / 976 |
| Usable number observations: two image models / OCR screening | 172 / 670 |
| Number holds in imported evidence | 312 |
| HP agreements / absent headers / conflicts / unknown | 578 / 11 / 1 / 534 |
| Stale source-fact or number subjects | 0 |
| Reviewed same-artwork pairs / reviewed differences / proposals | 63 / 11 / 594 |

The 24 unavailable-image targets have no new imported number/fact event and are outside the 1,154 number subjects. The existing Ho-Oh HP conflict and older holds remain intact. These image observations add neither catalog SKUs nor graph edges. [Preservation](catalog/source-facts-thousand-v1/preservation-v1.json) verifies **42 base tables, all 178 prior number rows and all 148 prior fact rows**. Only named import bookkeeping clocks are excluded from base-table semantic comparison; every clock difference is retained. Graph decisions, identity exceptions and existing catalog values are preserved.

TCGdex detail responses can contain incidental aggregate pricing fields; this batch does not import those values as fresh seller offers, sold prices or transaction-ready quotes. Authorized marketplace feed integration remains separate.

## Engineering verification and private delivery

**572 Python tests and twelve Node tests pass** on the final runtime; three new transport guards and five existing card-comparison guards also pass for the rehearsal repair. Intermediate 569- and 571-test runs are retained. Local checks pass **1,018 new-batch checks and 21 existing-fact regressions**. Twelve authored questions exercise absent images, multipart cards, literal-title differences, ownership/mechanics, HP conflicts, OCR tier disclosure, seller-copy and pricing boundaries. These are engineering checks, not blind collector-question accuracy.

The runtime build receives only the two final compiled evidence files from this new batch. Images, native outputs, raw model responses, queues, operational scripts and diagnostics are excluded from the Cloud Run upload/runtime. [Upload scope](catalog/source-facts-thousand-v1/upload-scope-v1.json).

Private Cloud Run revision **`pokemon-commerce-index-00039-n9g`** serves 100% of staging traffic. Final checks pass **1,020/1,020 for the new batch and 23/23 for existing facts**: 1,043 engineering checks, including four repeated unauthenticated 403 denials and six Node caller journeys. Ten transient transport failures recovered within bounded retries; no final logical failure remains. Both reports bind the same unchanged private revision and immutable image. The final cloud check results and immutable image bindings are recorded in [delivery validation](catalog/source-facts-thousand-v1/delivery-validation-v1.json).

The first thousand-subject cloud replay stopped at a rarity correction whose local/container `applied_at` differed; the source values and readings were identical. Its partial report and seven recovered transport errors are retained. The replay now uses the existing card-bound rarity-overlay comparison helper, excluding only `/rarity_correction/applied_at`; both original clock values remain in the report. Five existing guards confirm that corrected rarity, card binding and evidence timestamps remain strict. The second cloud run then encountered an uncaught truncated HTTP body. Its partial report and failure trace are retained. The rehearsal now applies three bounded retries for incomplete bodies and connection resets, preserving transport errors. Three focused tests verify same-request retries, exhaustion and non-retry of validation failures. The runtime and deployed image did not change for either diagnostic repair.

## Next sequence

1. Upgrade the **332 prioritized subjects** using fresh, separately recorded image-model readings with catalog and previous verdicts hidden. The queue contains 306 number holds, 24 unavailable images and two additional title-structure holds; categories overlap. Start with the fifty SV2A number holds and complex Japanese mechanic/symbol titles. Reacquire missing scans from explicitly bound sources; do not fill gaps from expected catalog text. [Frozen escalation queue](catalog/source-facts-thousand-v1/next-escalation-targets-v1.jsonl).
2. Review the already frozen [fourteen artwork-pair hypotheses](catalog/cross-release-source-facts-v1/next-artwork-pair-targets-v1.jsonl) using actual paired images and separate image-model inspections. OCR/title/HP agreement cannot establish same artwork. No review of those fourteen pairs is claimed here.
3. Prioritize remaining HP unknowns as supplementary metadata evidence. Do not lower OCR confidence thresholds merely to improve the reported pass count.
4. Attach authorized marketplace listing/offer APIs once Buy&Ship supplies the feed and data-use scope. Fresh ask prices, accepted sale prices, landed cost, seller-copy condition and transaction handoff retain their own evidence requirements.

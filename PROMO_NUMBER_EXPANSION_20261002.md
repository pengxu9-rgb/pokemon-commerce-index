# Fifty promo-number targets — 2 October 2026

## Completed batch

All fifty targets in the previous frozen research queue have an outcome. The source files were checked against the pinned TCGdex archive. The first fetch obtained 24 images and held 26; existing Japanese publisher coordinate references recovered 25 images. The final set contains **49 actual source images and one image hold**. The original failed attempts, both asset snapshots, source metadata and image/page hashes remain retained. Recovery selects the first sorted existing coordinate reference only; it neither covers every publisher printing nor assigns a physical variant to a stock scan.

The root/OpenAI reviewer inspected ten actual sheets (full images with name/number crops), then saved fifty records before Vertex began. **Gemini 3.8 Flash completed 49 fresh single-image calls**, plus one explicit asset hold without a call. Its prompt received no expected catalog name, number, URL, source filename or first-review verdict. Root sheets had neutral target labels, but the root already had project/queue context; this is not a fully blind independent ground-truth exercise. [Chronology validation](catalog/promo-number-expansion-v1/review-chronology-validation-v1.json).

[Initial adjudication](catalog/promo-number-expansion-v1/adjudication-v1.json):

| Outcome | Targets | Meaning |
|---|---:|---|
| Catalog text observed | 20 | Source-image name/number evidence passes the scoped checks |
| Catalog denominator not observed | 24 | Actual number/code is readable; catalog slash suffix is not established as printed text |
| Number-reading hold | 5 | Number text agrees, but name evidence is unconfirmed or conflicting |
| Image unavailable | 1 | No number observation is manufactured |

The ten English HGSS and four SM promos show single codes such as `HGSS01` and `SM01`; source inventory denominators are not inserted into their image readings. Ten English MEP images show numeric codes such as `001`, with adjacent MEP/EN labels, not a printed slash suffix. Japanese publisher images often visibly show complete codes such as `001/M-P` or `001/S-P`. These observations describe this selected batch, not every promo in a region.

## Retained name holds and correction

Four Japanese basic-energy targets use type symbols between 基本 and エネルギー, with printed furigana such as くさ or ほのお. The source names expand the symbols as 草/炎. Literal title readings and canonical expanded names are different evidence types; the current name guard does not silently replace the former with the latter. Their matching collector numbers therefore remain held as qualified exact-source facts, with raw readings preserved.

For `ja:M-P:005/M-P:normal`, the first root record incorrectly transcribed **あなぬけスコップ**. Gemini read **あなあけスコップ**. Enlarged reinspection of the original source clearly confirms あなあけ. The [post-comparison advisory correction](catalog/promo-number-expansion-v1/name-hold-reinspection-advisory-v1.json) corrects that transcript and explains all five holds; the original review remains immutable. Because that reinspection had seen the Gemini result, it is not imported as a new independent agreement and the initial hold remains. The hold does not mean the card or its catalog name is wrong.

The Ancient Mew target `en:MISCP:001/001:holo_cosmos` has no qualified image in this acquisition pass. Its source coordinate is not treated as observed printed text.

## Architecture changes

Nullable unreadable number/name text can now be recorded as a hold, without injecting catalog values. A number agreement cannot qualify when observed name text is missing or differs from the source name. New source snapshots and prior-inspection provenance remain mandatory; no identity, physical finish, copy, price or offer approval is created.

The batch also exposed a case-preservation issue: the normalized legacy number field uppercases a source coordinate such as `001/mep`. Explicit `catalog_number` now comes from the raw card row, preserving that original case while normalized numbering keys and the legacy field remain compatible. A regression test protects the separation.

The [51-input manifest](catalog-build-manifest-promo-numbers-v1.json) appends **49 immutable number events** (44 qualified observations and five holds), preserving the previous 50 inputs. The catalog now has **79 number-evidence subjects: 74 usable scoped observations, five held, zero stale**; 25 usable observations do not establish the catalog denominator as printed text (24 new plus the earlier Cleffa). Only frozen evidence rows enter the runtime; source images, model responses, review sheets and diagnostics remain excluded.

[Preservation checks](catalog/promo-number-expansion-v1/preservation-v1.json) prove all 42 prior base tables and all thirty earlier number events remain semantically intact. Only specifically identified import application times differ; every before/after difference is retained. Catalog counts remain **70,006 internal source records / 45,438 coordinates / 33,543 structural eligible records**. The graph remains **63 verified same-artwork pairs / eleven reviewed differences / 594 proposals**. Observations do not unlock the ten selected structurally disabled English historical records or any marketplace/display permission.

## Separate source quality finding

Ho-Oh `HGSS01` has a visible HP **100** in the acquired scan, whereas the pinned source and current detail API declare HP **80**. [The incidental discrepancy](catalog/promo-number-expansion-v1/source-hp-discrepancy-advisory-v1.json) is retained as a non-number metadata conflict; no raw field is rewritten. The number/name reviews are not a full audit of HP, effects or artwork assignment and do not establish complete card identity. Wider ingestion should audit such source-to-scan facts separately.

## Verification and next step

**549 Python and twelve Node tests pass.** New guards cover null/unknown readings, matching numbers with mismatched names, symbolic energy-title differences, incomplete/substituted model output and raw-versus-normalized coordinate case.

Local HTTP suites pass **57 promo checks**, **55 prior-number checks**, and **105 artwork checks**. The six new comparison questions are authored after review as engineering regressions; they are not held-out user questions. The prior 54 frozen questions and six actual Node caller journeys remain included in the artwork suite. These totals are not accuracy estimates.

The private cloud now serves revision **`pokemon-commerce-index-00035-bk8`** at 100% traffic. [New promo checks](catalog/promo-number-expansion-v1/private-cloud-replay-v1.json) pass **59/59**, and the [complete artwork regression](catalog/promo-number-expansion-v1/artwork-regression-cloud-v2.json) passes **107/107**: **166 engineering checks**, including four repeated unauthenticated 403 denials. One HTTP connection failure recovered through bounded retry in the final run. Two earlier Node timeout failures remain in the incomplete first-run report; fresh probes succeeded, but their cause is not established. The existing ten-second Node timeout and two-attempt policy were retained. [Failure history](catalog/promo-number-expansion-v1/diagnostic-failures-v1.json).

[Delivery bindings](catalog/promo-number-expansion-v1/delivery-validation-v1.json) verify current runtime/snapshot hashes, private IAM, unchanged cloud revision/image and all 51 inputs. Final logical failures are zero. This establishes staging behavior, not production availability, independent card accuracy or complete collector answers. Fresh marketplace asks, physical-copy assessment, price comparability and Buy&Ship handoff remain pending authorized offer data.

Next: add an explicit representation for literal printed title text, visible type symbols/furigana and a separately evidenced canonical-name normalization. Use fresh separately recorded inspections to resolve the five name holds; the advisory correction alone cannot authorize that upgrade. Then expand number evidence by source/release and audit non-number metadata conflicts before deriving new identity or relationship mappings.

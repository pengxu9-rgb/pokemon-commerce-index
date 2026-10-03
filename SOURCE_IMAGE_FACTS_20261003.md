# Source-image title and HP facts — 3 October 2026

## Implemented

The catalog now has a separate append-only source-image fact layer. Literal title fragments, symbols embedded between those fragments, visible furigana, collector text and header HP are separate fields. `absent`, `unreadable` and a visible HP value remain distinct. Interpretation uses a narrow versioned rule for Japanese basic grass/fire energy names: literal 基本 + a positioned grass/fire symbol + エネルギー, with the matching printed pronunciation. It never fills symbols or pronunciation from the expected catalog name.

`GET /catalog-card` exposes these facts and their review context. `POST /card-comparison` and natural comparison questions expose exact-record facts on each side, plus source metadata warnings. A source HP conflict adds `source_image_metadata_resolution` to required evidence. Requests cannot inject these facts or upgrade their qualification. Sibling variants do not inherit them; endpoint drift hides the interpretation; revised facts supersede older facts without deleting history. The new evidence and implementation participate in conversation revision binding.

## Nine selected source scans

The frozen cohort covers the five earlier name holds, Ho-Oh's HP discrepancy and three named controls. All nine pinned source files and images were byte checked. Root inspected three actual image sheets and saved structured records before **nine fresh Gemini 3.8 Flash image-only calls**. Gemini received no expected catalog name/number/HP, prior verdict or search tool. Root had already seen the earlier batch and advisory conclusions; its context flags explicitly remain true. These are supplementary source correspondence advisories, **not new independent review agreement or an accuracy estimate**.

| Result | Subjects |
|---|---:|
| Literal name correspondence advisory | 5 |
| Symbol/furigana name correspondence advisory | 4 |
| Visible HP agrees with pinned source | 3 |
| Visible HP conflicts with pinned source | 1 |
| No HP visible and no source HP field | 5 |

The four basic energies separate literal 基本エネルギー from the symbol-derived canonical names 基本草エネルギー / 基本炎エネルギー. The shovel scan reads あなあけスコップ; the earlier erroneous root transcript remains intact. Ho-Oh's scan visibly reads **HP 100**, while its pinned source declares **80**. Neither raw names nor HP fields are rewritten. Three other selected Pokemon scans agree with pinned HP; this is not a whole-catalog HP audit.

[Compiled observations](catalog/source-image-facts-v1/compilation-v1.json), [review context and tests](catalog/source-image-facts-v1/chronology-and-tests-v1.json).

## Preservation and qualification

The [52-input build](catalog-build-manifest-source-image-facts-v1.json) preserves all earlier 51 input objects and hashes, appending nine fact events. [Preservation](catalog/source-image-facts-v1/preservation-v1.json) compares all 43 prior tables, including all **79 original number events**. Only specifically identified import application times are excluded; their before/after values remain recorded. Number evidence remains **74 usable / five held / zero stale**, with 25 catalog denominators not established as printed. This layer does not relax that gate or convert an informed reinspection into independent agreement.

The directory remains **70,006 source records / 45,438 coordinates / 33,543 structurally eligible records**. The graph remains **63 same-artwork pairs / eleven reviewed image differences / 594 proposals**. Display, physical-copy, pricing and automatic-offer approval remain zero. Stock-image correspondence does not certify a finish/edition, a seller copy or the full source metadata. Raw source images, model responses, queues and diagnostic reports are excluded from the runtime image; only the compiled fact events are imported.

## Verification

**559 Python and twelve Node tests pass**, including ten new tests for symbol/furigana requirements, literal-versus-interpreted distinction, HP conflicts/nulls, context disclosure, exact-source scope, revision binding, atomic import and invalid claims. Local suites pass **21 new checks**, **57 prior promo checks**, and **105 artwork regressions**. Six new questions were authored after review as engineering diagnostics; they are not held-out collector questions. Actual Node caller journeys use the existing ten-second timeout and two-attempt policy.

The private Cloud Run service now serves **`pokemon-commerce-index-00036-6gh`** at 100% traffic. [New cloud checks](catalog/source-image-facts-v1/private-cloud-replay-v1.json) pass **23/23**, and the [promo regression](catalog/source-image-facts-v1/promo-regression-cloud-v1.json) passes **59/59**. These **82 engineering checks include four repeated unauthenticated 403 denials**. No transport errors or final logical failures are recorded. [Delivery bindings](catalog/source-image-facts-v1/delivery-validation-v1.json) verify runtime/snapshot/review/input hashes, private IAM and unchanged revision/image. This does not establish real-user accuracy or production availability.

## Next sequence

A [frozen next queue](catalog/source-image-facts-v1/next-source-fact-targets-v1.jsonl) contains **40 remaining previously acquired source scans**, with byte-checked assets and pinned endpoints. They have not received structured fact reviews or been imported into this layer. Expand across that queue, prioritizing cross-field source-to-image conflicts. Keep fresh reviewer context separate and resolve literal/symbol names without silently replacing printed text. Then obtain fresh separately recorded inspections for any independent number qualification upgrade. Authorized marketplace listings, actual-copy condition and live offers remain the later gate for price/merchant recommendations.

# Official source recovery and Prism Star binding — 3 October 2026

## Fixed batch result

All **51 frozen source priorities** have recorded outcomes:

| Outcome | Subjects |
|---|---:|
| Recovered publisher scans; two separately recorded image readings correspond to catalog name/number | 17 |
| Exact official coordinate supports the observed Prism Star mechanic | 16 |
| Explicit remaining evidence holds | 18 |

This batch qualifies source evidence for existing records. It adds **zero catalog identities and zero graph assertions**.

## Recovering missing M6A images

The official [30th CELEBRATION product page](https://www.30th.pokemon-card.com/product/m6a) loads a card-list bundle containing 167 structured records. Its static JSON was parsed as data; no publisher JavaScript was executed. The saved product page, bundle, extracted rows and hashes bind the discovery path.

Exact release/number/name candidates recovered **M6A 104–118, 120 and 124**, seventeen scans. Each PNG was fetched from the exact listed official path, decoded for inspection and byte-hashed. Their source TS files were independently checked against the pinned archive before compilation.

The bundle's card-publication dates are retained as raw source fields and are not imported as product launch or physical-copy dates.

- **OpenAI root agent:** directly inspected native-resolution header/footer crops of all seventeen images, plus full-scan context for the first four. Catalog/product-list context was visible. No Gemini image verdict was read before recording these observations. The runtime does not expose the root model's exact version, so its model-version field is null.
- **Vertex Gemini 3.8 Flash:** received original PNG bytes and the image-only fact prompt. Expected catalog text, previous verdicts and search were absent from these requests.

Both readings correspond for complete numbers, names and HP. Raw adjacent AR/SAR tokens, literal name spacing and reviewer context remain intact. Inspection artifacts record actual source images/crop hashes. These are selected source-scan correspondences, not blind marketplace matching precision or physical finish/condition certification.

Seven missing subjects remain: the three separately numbered S8B 057–059/184 parts; M6A 119/103 and 121/103; and M6A G/R records. The observed official product list did not supply exact candidates for the latter four. This is a scoped acquisition gap, not a claim that these cards do not exist.

## Sixteen source mechanic bindings

Sixteen existing independently read Prism Star scans now have an exact official page binding. For example, the official [SM8B Lunala 047/150 page](https://www.pokemon-card.com/card-search/details.php/card/35507) and [SM12A Shaymin 011/173 page](https://www.pokemon-card.com/card-search/details.php/card/37215) expose the mechanic in their title markup and special rule, alongside the correct set/number.

A separate append-only `source_mechanic_binding` table preserves the original image-fact and number events. Imports require:

- The exact current endpoint and its hash.
- The unchanged latest source-fact event and hash.
- Agreement on symbol anchors/base title in the two existing image readings.
- One exact catalog reference and matching single-number official page.
- Explicit title-symbol and special-rule declarations; no copy, display or commerce approval.

The API returns `source_image_facts.source_mechanic_binding`. A newer image-fact head, changed endpoint or changed reference invalidates the binding. Sibling variants do not inherit it. Original title interpretation warnings and number qualification remain visible; a mechanic binding does **not** rewrite a literal title or retroactively clear all number holds.

Collector journey revisions now hash both the new runtime module and its evidence table. A focused test verifies that importing mechanic evidence changes the revision and an idempotent import does not.

## Gemini search findings checked against actual primary sources

The research lane made two grounded search attempts. The first timed out; the second completed with grounding metadata. These calls are source-discovery assistance, separate from the seventeen image-only inspections.

The completed search answer claimed that official standalone AR/SAR assets were unavailable. The publisher's own loaded card list and the seventeen acquired scans contradict that claim for these targets. It was rejected.

The product feature section supports a group of **thirty distinct Pikachu illustration designs**. It does not by itself establish the exact observed secondary-number namespace for each scan or a thirty-copy print run. Nine such namespace interpretations remain held. Gemini's G/R explanation was not accepted as official identity evidence without an exact primary scan or coordinate declaration.

[Research adjudication](catalog/source-binding-v1/grounded-research-audit-v1.json) preserves these distinctions.

## Cumulative data quality and preservation

| Measure | Current |
|---|---:|
| Source-declared catalog records / language-release-number coordinates | 70,006 / 45,438 |
| Structurally eligible records | 33,543 |
| Number-evidence events / distinct subjects | 1,486 / 1,171 |
| Two image-model number subjects / OCR screening subjects | 503 / 668 |
| Complete catalog-number correspondences | 1,113 |
| Denominator unobserved / number holds / agreed coordinate conflicts | 25 / 32 / 1 |
| Source-fact events / subjects / title advisories | 1,449 / 1,141 / 1,124 |
| Current official mechanic bindings / stale bindings | 16 / 0 |
| Latest artwork agreements / qualified differences / proposals | 72 / 14 / 593 |

The **65-input** manifest preserves all 62 prior ordered inputs and appends three evidence files. The clean rebuild preserves all **1,469 prior number events**, **1,432 prior source-fact events**, **743 graph history rows**, and semantic values in all **42 other prior tables**. A new table holds the sixteen mechanic bindings. Import bookkeeping timestamp changes are separately recorded. Catalog coordinates and physical/display/offer permissions are unchanged.

The priority queue decreased from 51 to 18 by resolving seventeen acquisition gaps and sixteen mechanic-source gaps. The **32 historical number holds** remain a different measure: original literal-title-based number verdicts were not changed by the mechanic overlay.

## Delivery verification

Private Cloud Run revision **`pokemon-commerce-index-00043-2x6`** serves 100% of traffic. Final checks passed:

- **601 Python tests** and **12 Node tests**.
- **111 local** and **115 private-cloud engineering checks**, including four unauthenticated denials.
- Current snapshot, all ordered input hashes, runtime, replay scripts, final deployed image and private IAM checks.
- No final logical failures; transport outcomes are recorded in the delivery evidence.

The test reference fixture and local replay invocation required small corrections. During final review, the mechanic table/module was added to journey revision binding, with a new test. The first cloud deployment was stopped to include this guard; final local/cloud reports bind the corrected runtime. Earlier successful-but-superseded local reports and diagnostic notes are retained.

[Delivery record](catalog/source-binding-v1/delivery-validation-v1.json), [preservation audit](catalog/source-binding-v1/preservation-v1.json), [51 subject outcomes](catalog/source-binding-v1/batch-outcomes-v1.jsonl), [compiled provenance](catalog/source-binding-v1/compilation-v1.json).

## Next sequence

The remaining **18 source priorities** comprise seven missing assets, nine multi-number namespace interpretations, one multipart source scan and one agreed 143a-versus-143 coordinate conflict. Two prior artwork-pair holds remain separate.

Next, apply explicit versioned title interpretations to exact official mechanic bindings, so literal names and numbering can be qualified without dropping symbols. Investigate secondary-number semantics against actual publisher images and declarations; retain multiple numbers when namespace assignment is unsupported. Resolve source-coordinate conflicts before adding any new artwork approval for affected records.

After those checks, broaden the frozen independently reviewed artwork cohort. Live API offers, real marketplace matching precision, condition evidence, freshness and Buy&Ship transaction integration remain the commerce gates.

# Source notation and versioned number interpretation — 3 October 2026

## Delivered

Seven Japanese source-number holds are resolved by a **versioned interpretation of existing independent Astra/Gemini readings**. No fresh model inspections or new card identities are counted. The rule separates a literal adjacent `S` or `K` token only from an already complete numeric fraction. It never fills a missing denominator, strips an arbitrary suffix, or merges two printed numbers.

The seven subjects are SV4A 191–193/190 and S12A 015, 033, 039 and 055/172. Their raw readings, reviewers, model contexts, image hashes and source bindings are unchanged. Each new v2 event binds the exact prior latest event and its hash; the importer rejects changed inspections, stale prior heads and backdated interpretation timestamps. The legacy rule and all prior held verdicts remain available.

The official [Oddish page 44977](https://www.pokemon-card.com/card-search/details.php/card/44977) and [Radiant Charizard page 42276](https://www.pokemon-card.com/card-search/details.php/card/42276) provide the format examples. Publisher HTML snapshots and hashes are retained. The root agent inspected these examples with known catalog context; this is a format-rule check, **not another independent reviewer**.

## Structured notation without identity promotion

The API now exposes `source_image_facts.source_notation` from unchanged source-fact readings. The selected audit covers:

| Source notation | Subjects | Current treatment |
|---|---:|---|
| Prism Star symbol/title | 16 | Preserve symbol anchors and base-name correspondence; canonical mechanic binding remains unresolved |
| M6A multiple numbering | 9 | Preserve each reader's literal fractions separately; neither namespace is chosen |
| Four-part combined source scan | 1 | Preserve four observed numbers; no individual seller-copy or condition conclusion |

Title and number holds remain visible. One reader observing two fractions while another reads one is not a two-reader namespace agreement. `01/30` does not establish that only thirty copies were printed. Neither the notation layer nor the number-format interpretation approves physical finish, regional price equivalence, seller-copy matching or an offer.

## Agent question correction

A comparison naming two exact card IDs can now retain an explicitly labeled additional number, for example:

> Compare ja:M6A:017/103:normal and ja:M6A:018/103:normal: does secondary number 01/30 mean only thirty copies were printed?

The two comparison targets remain the explicit IDs. The additional number is returned as an **unverified user question**, with no card assignment, namespace confirmation or print-run conclusion; namespace confirmation is added to the outstanding evidence requirements. Chinese labels such as “第二套编号” are supported. An unlabeled third card number still requires clarification.

Nine authored development questions cover this behavior, adjacent rarity tokens, Prism Star, combined scans, the retained 143a-versus-143 conflict, prior English artwork relations and missing M6A assets. They are engineering regression cases, not a blind real-user accuracy benchmark.

## Cumulative status and preservation

| Measure | Current |
|---|---:|
| Internal source-declared records / language-release-number coordinates | 70,006 / 45,438 |
| Structurally eligible records | 33,543 |
| Number-evidence events / distinct subjects | 1,469 / 1,154 |
| Complete catalog-number correspondences | 1,096 |
| Denominator not observed / number interpretation holds | 25 / 32 |
| Agreed source-to-catalog number conflicts | 1 |
| Source-fact events / subjects / title advisories | 1,432 / 1,124 / 1,107 |
| Latest artwork agreements / qualified differences / proposals | 72 / 14 / 593 |
| New image inspections / graph events / catalog identities this batch | 0 / 0 / 0 |

The 62-input manifest preserves all 61 prior ordered inputs and appends one seven-event interpretation file. The rebuilt snapshot retains all 1,462 prior number events, 1,432 source-fact events, 743 graph history rows and semantic values in all 43 other tables. Import bookkeeping timestamp differences are separately recorded. Catalog coordinates are unchanged.

Number agreement totals include 1,096 complete catalog matches, 25 readings with an unobserved catalog denominator and one agreed conflicting source number. The latter remains blocked; interpretation rules do not hide it.

## Delivery verification

Private Cloud Run revision **`pokemon-commerce-index-00041-qbl`** serves 100% of traffic. Verification passed:

- **593 Python tests** and **12 Node tests**.
- **108 local** and **112 private-cloud engineering checks**, including four unauthenticated denial checks.
- Complete snapshot, input, runtime, replay-script, manifest and deployed-image hash bindings.
- No transport retries and no final logical failures.

One delivery-report aggregation error assumed artwork checks used the same result key as source-fact checks. Its diagnostic is retained; the collector was corrected without changing runtime, evidence or the successful replay reports.

[Delivery record](catalog/source-notation-v1/delivery-validation-v1.json), [preservation audit](catalog/source-notation-v1/preservation-v1.json), [interpretation provenance](catalog/source-notation-v1/reinterpretation-audit-v1.json), [notation audit](catalog/source-notation-v1/notation-audit-v1.json).

## Next fixed batch

The frozen source-priority queue now contains **51 subjects**: 24 missing assets, sixteen title-symbol bindings, nine multiple-number namespace interpretations, one combined scan and one agreed coordinate conflict. Two prior artwork-pair holds remain separate. Six older number holds outside this priority cohort are also retained.

Process these with exact primary-source bindings and separately disclosed AI inspections where needed. Each subject must end with source-backed evidence or an explicit unresolved outcome. Missing M6A G/R sources cannot use an MF Mew scan, and a same-name numbered card cannot stand in for a different release coordinate.

After this queue, broaden independently reviewed artwork coverage in a frozen batch. Authorized API listing/offer ingestion, real marketplace matching precision, live prices and condition evidence remain the next commerce gates. Current catalog evidence does not supply them.


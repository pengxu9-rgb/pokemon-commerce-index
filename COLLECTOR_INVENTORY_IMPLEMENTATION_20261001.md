# Inventory comparison and second collector diagnostic — 1 October 2026

## Delivered

An internal collector can now submit an inventory and compare it with a stated catalog scope. This step adds no card identities or verified artwork relationships: the catalog remains at 55,167 internal identities, 100 source-bound supported metadata targets and zero automatic live-offer approvals. It gives the agent an executable answer to the catalog portion of “what am I missing?” while preserving uncertainty about physical copies and catalog completeness.

The second fresh diagnostic contains 30 unique public originals: 18 English and 12 Japanese questions, from 12 Reddit, 12 Yahoo Japan Q&A and six Efour posts. The unchanged discovery executor initially passed 7/30. Its corrected development and clean-manifest replays each produce **eight scoped catalog partials and 22 specific evidence blockers**. Complete collector answers established: zero.

All 377 regression tests pass. An offline inventory rehearsal recognizes 100 synthetic ownership assertions against the 100 source-bound target IDs and passes eight checks, including unchanged catalog bytes. These are engineering checks, not real inventory or marketplace precision measurements.

## Inventory contract

CLI:

```bash
python3 -m pokemon_index --db catalog-index-discovery-v1.sqlite3 collector-inventory sandbox/collector_questions/v2/inventory-example.synthetic.json
```

Private HTTP: `POST /collector-inventory`, enabled only with `--internal-catalog-api`. Send `Content-Type: application/json`. The example file contains synthetic ownership, not a real collection.

```json
{
  "question": "Japanese SV4A 347/190",
  "owned_items": [
    {"item_id": "example-1", "card_id": "ja:SV4A:347/190:holo", "quantity": 1}
  ],
  "limit": 50,
  "offset": 0
}
```

Each entry supplies either `card_id`, or `language`, `set_code`, `collector_number` and an optional `variant`. Up to 1,000 entries and a 262,144-byte HTTP body are accepted. Item IDs must be unique; integer quantity is 1–10,000. Missing-result pages accept limits 1–100. The catalog scope must contain at most 10,000 records.

| Output | Meaning |
|---|---|
| `owned_in_scope` | Existing catalog IDs explicitly declared by the caller; quantities are aggregated |
| `possible_owned` | Catalog candidates for entries whose exact version is unresolved |
| `missing_catalog_records` | Scoped catalog records absent from resolved or possible submitted ownership; unknown entries may still cover them |
| `outside_scope` | Declared existing IDs outside the current query |
| `duplicates` | Multiple submitted entries for one catalog ID; duplicate quantity does not close another identity gap |
| `unresolved_items` | Unknown IDs, unknown versions/coordinates or unsupported languages, preserved for clarification |

Coordinates without a declared version remain uncertain even when the catalog has only one candidate. A catalog ID is a caller assertion, not evidence of physical ownership, finish, condition, grade or authenticity. The inventory schema does not accept those unsupported claims as identity evidence.

`comparison_complete_for_submitted_catalog_scope` means every submitted entry resolves to a declared catalog record within an executable query. It does not establish an exhaustive physical-printing checklist. `complete_missing_list_established`, `ownership_assertions_verified`, `physical_copy_verification`, `public_display_allowed` and `inventory_persisted` remain false; prices and live offers remain empty. Market, cameo and other evidence-blocked queries produce no gap list.

The service reads the catalog snapshot and does not persist inventory or log request bodies. There is no account inventory store, image analysis, public collector chat or live purchase recommendation in this endpoint.

## Source qualification and failure preservation

The [frozen cohort](sandbox/collector_questions/v2/source_questions.jsonl), source contexts, reference expectations and initial runtime hashes were recorded before discovery changes. The first [unchanged-runtime report](sandbox/collector_questions/v2/initial-codex-qualified-report.json) remains intact.

Original-post inspection and Codex source review accepted all 30 contexts; Vertex `gemini-3.8-flash` initially accepted 27 and challenged three. Those summaries had omitted source details. Recovery supplied the missing original-post excerpts for the same three questions; question rows and reference expectations were unchanged. The three then passed both source checks. The [first source gate](sandbox/collector_questions/v2/source_gate/report.json), all model decisions and [context-only recovery](sandbox/collector_questions/v2/evidence_recovery/) are retained. These are 30 unique originals, not 33 questions.

The [combined release replay](sandbox/collector_questions/v2/combined-release-replay-report.json) records both gate lineages on a clean manifest build. Earlier development and manifest replays are retained. The combiner checks unchanged question/expectation rows, disjoint accepted IDs, current executor hashes and identical original first-result rows for the recovered subset. Source IDs do not overlap the first collector cohort or the 11 earlier public-question cohorts.

This is a purposive development diagnostic. The researcher knew the implementation and selected the questions. Gemini reviewed supplied original-post context; it did not independently fetch pages, inspect artwork or establish physical printing truth. Passing source review is not a measurement of independent answer accuracy. Eight partials and 22 blockers must not be presented as 30 complete answers or a 100% user success rate.

## Failures corrected

- Keep shiny-Pokémon depiction separate from foil finish; black/white rarity-star differences require a printed release, number and variant evidence.
- Preserve raw-card availability requests even when a question rejects graded slabs; market questions still require authorized fresh evidence.
- Preserve Japanese questions about cameos, grader forms, sealed product contents, historical card backs and official search UI as specific evidence requests.
- Require the referenced list for a video-based identification request; avoid returning every card of a mentioned species.
- Keep figures outside card identity matching and preserve future Korean, all-language, stamp, jumbo, external-list, binder and owned-inventory constraints.
- Preserve the ordinary phrase “figure out” as a card request rather than merchandise; final inspection added that regression case before release.
- Avoid treating a Japanese example within a general checklist request as an instruction to exclude English records.

The first source cohort still passes its 16 cases with partials/blockers separate; the authored development suite remains 30/30. A clean catalog rebuild reproduces the second cohort using the six-table semantic fingerprint, independent of SQLite layout and support-review timestamps.

## Reproduce

Use new output paths; evaluators do not overwrite historical evidence.

```bash
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-discovery-v1.json --db /tmp/collector-inventory-catalog.sqlite3
python3 -m scripts.evaluate_collector_sources --db /tmp/collector-inventory-catalog.sqlite3 --directory sandbox/collector_questions/v2 --eligible sandbox/collector_questions/v2/source_gate/eligible_source_questions.jsonl --output /tmp/collector-v2-base.json
python3 -m scripts.evaluate_collector_sources --db /tmp/collector-inventory-catalog.sqlite3 --directory sandbox/collector_questions/v2/evidence_recovery --eligible sandbox/collector_questions/v2/evidence_recovery/source_gate/eligible_source_questions.jsonl --output /tmp/collector-v2-recovered.json
python3 -m scripts.combine_collector_reviews --directory sandbox/collector_questions/v2 --base-report /tmp/collector-v2-base.json --recovery-report /tmp/collector-v2-recovered.json --output /tmp/collector-v2-combined.json
python3 -m scripts.rehearse_collector_inventory --db /tmp/collector-inventory-catalog.sqlite3 --output /tmp/collector-inventory-rehearsal.json
python3 -m unittest discover -s tests -q
```

## Next implementation

1. Build source-bound artwork/depicted-character and printing-version evidence for specific observed collector tasks. Keep proposed annotations separate from verified graph edges, and regional leads separate from printing/price equivalence.
2. Connect the stateless comparison contract to the controlled agent journey: provide inventory, inspect unresolved records, then choose a catalog target. Persisted account inventory needs its own authentication, ownership and retention design.
3. Expand supported metadata into additional modern releases when that serves those tasks. Physical finish and real-listing precision remain separate gates.
4. Continue the authorized-feed and Buy&Ship quote/transaction work when its contract arrives. The catalog, synthetic assertions and diagnostic blockers do not substitute for live asks, condition evidence or fulfillment outcomes.

Private staging revision `pokemon-commerce-index-00016-f7q` serves all traffic. Its [verification](cloud-deployment-20261001-inventory-v2.json) records 55 authenticated logical HTTP requests, 30 complete source-case replays and eight synthetic inventory comparisons. Unauthenticated health and inventory requests return 403; malformed/invalid inventory returns 400. No market feed is enabled. Earlier rollout and the correction to an ambiguous newly authored language control are retained in [CLOUD_RUN.md](CLOUD_RUN.md).

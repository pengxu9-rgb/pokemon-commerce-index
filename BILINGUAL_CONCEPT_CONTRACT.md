# Bilingual concept retrieval contract

The exact card printing remains `language + set + collector number + variant`. A bilingual concept is a translation of a card **name** for candidate retrieval. It does not say that Japanese and English printings share artwork, finish, edition, release, price, or merchant availability.

## Current data and source

`catalog/card-classifications.jsonl.gz` contains category and subtype extracted from the pinned TCGdex text metadata at revision `a211f11f3ba57d56c65c5ac33be35b77d3280757`. Each row carries the card's source-file SHA-256 provenance and rights reference. The build reads only local pinned files; it does not copy images, effects, prices, or marketplace listings. The audit is in `catalog/card-classifications-audit.json`. Four variants from two inconsistent source files remain unclassified. The database table is `card_classification`, separate from character/artist facets and reviewed relation assertions.

The `bilingual_concept_revision` table now contains 54 internal aliases approved through user-authorized dual-AI consensus across v2 and v3, with both model identities and rationales retained in each linked review event. This is distinct from human certification. Import records are append-only by `concept_id, revision`. The latest `approved` revision enables retrieval; a newer `withdrawn` revision disables it. A repeated identical revision is idempotent; a stale or conflicting revision is rejected. The production import command now accepts a compiled review bundle and atomically stores every non-pending decision in `concept_review_event`; each approved alias references its review event. The low-level `core.import_bilingual_concepts` function remains for fixtures and migrations.

Each approved concept revision inside a compiled review bundle has these fields:

| Field | Meaning |
| --- | --- |
| `concept_id`, `revision` | Stable concept key and increasing integer revision |
| `category` | `Pokemon`, `Trainer`, or `Energy` |
| `name_ja`, `name_en` | Exact printed names checked by the reviewer |
| `source_ja`, `source_en` | Distinct, card-specific evidence references where available; retain source version or access date in the reference |
| `rights_reference` | Permission and attribution record for internal use |
| `reviewer`, `reviewed_at` | Attributed reviewer identity and timestamp with UTC offset; current AI consensus rows use `ai-consensus:gpt-6-astra+gpt-6-sol` |
| `status` | `approved` or `withdrawn` |
| `review_event_id` | Digest of the retained review decision and full source snapshot |

A sample shape, **not an approved mapping**, is:

```json
{"concept_id":"example-translation","revision":1,"category":"Trainer","name_ja":"<checked Japanese name>","name_en":"<checked English name>","source_ja":"<card-specific Japanese evidence>","source_en":"<card-specific English evidence>","rights_reference":"<reviewed rights record>","reviewer":"<human reviewer ID>","reviewed_at":"2026-09-24T00:00:00Z","status":"approved","review_event_id":"<compiled review digest>"}
```

The candidate generator looks up the anchor's exact name in the latest approved concept, then requires the other card's category and, when both are known, subtype to agree. Matching illustrator is the strong channel; without it, the full same-name candidate set must fit the per-anchor cap. Multiple concepts for one anchor or too many candidates cause an explicit abstention. The review queue carries concept source references and a digest of both card classifications and the concept revision. A withdrawn or replaced concept blocks compilation of an older positive review queue. A reviewer still needs card-specific identity, artwork, and finish evidence; two agreeing human reviews are required for a verified graph edge.

## Rebuild and probe

```bash
python3 -m scripts.build_card_classifications \
  --repo ../../work/tcgdex-public \
  --revision a211f11f3ba57d56c65c5ac33be35b77d3280757 \
  --cards catalog/ja-all-available.jsonl --cards catalog/en-physical-cards.jsonl \
  --output classifications-rebuilt.jsonl.gz --report classifications-rebuilt-audit.json
python3 -m pokemon_index --db catalog-index.sqlite3 init
python3 -m pokemon_index --db catalog-index.sqlite3 import-card-classifications catalog/card-classifications.jsonl.gz
python3 -m scripts.concept_review_packet compile-reviewed \
  --queue catalog/concept-review-v2-queue.jsonl \
  --sheet reviewed-concepts-v2.csv --output reviewed-concepts-v2.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-concept-review-bundle reviewed-concepts-v2.bundle.json
python3 -m scripts.relationship_pilot generate --db catalog-index.sqlite3 \
  --anchors catalog/relationship-coverage-anchors.jsonl \
  --output concept-queue.jsonl --audit concept-audit.json --sheet concept-review.csv
```

The selected v2 anchors yield 49 candidate pairs across 21/21 anchors. The additional v3 anchors yield 68 candidates across 33/33 anchors. Across both batches, 54 source pairs have explicitly `proposed` collecting-alternative edges. The older 30-anchor diagnostic remains separate and should not be treated as a measured recall result. This is a diagnostic challenge set, not a recall measurement. The three blind Trainer anchors have source classifications but lack reviewed translations; the three Energy anchors are unverified supplemental identities without source classifications. Independent adjudicated answers are needed before measuring recall@K. Do not add aliases from candidate output itself: that would contaminate the blind evaluation. See [CONCEPT_REVIEW_V2.md](CONCEPT_REVIEW_V2.md) and [CONCEPT_REVIEW_V3.md](CONCEPT_REVIEW_V3.md) for the still-pending human-review packets.

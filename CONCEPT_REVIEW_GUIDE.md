# First bilingual concept review packet

The [review template](catalog/concept-review-template.csv) contains **36 pending proposals** across 16 Trainer names and 6 Energy names. The immutable [queue](catalog/concept-review-queue.jsonl) and [selection audit](catalog/concept-review-audit.json) record each source card and how it was chosen. The 30-anchor blind relationship challenge and the earlier 19-anchor pilot are excluded by Japanese card **name**, not merely card ID. This packet is a deterministic early review sample, not a market-demand ranking.

Trainer proposals use the same illustrator, category and compatible subtype to bound a list of up to five English names. This often produces wrong alternatives: for example, a common illustrator may have drawn unrelated Supporter cards. Energy proposals use a small, explicit Japanese-to-English name hint list and require both names to exist on pinned, classified TCGdex card records. A hint is a search aid, not a checked translation. Cards available only as unverified API-family identities are excluded. [TCGdex's language API documentation](https://tcgdex.dev/tcg-live) describes localized IDs, but a localized ID alone is not evidence that two distinct regional physical printings correspond; the live Japanese endpoint for one English-set example returned 404 during this check.

## What the reviewer does

1. Open the CSV. Follow `source_ja` and `source_en` for each row and confirm the exact names, source card identities, and category. The links point to pinned source files; their hashes are preserved in the queue. Use additional official card pages if the source files leave doubt, and record that in `evidence_note`.
2. Set `decision` to `approve`, `reject`, or `uncertain`. An approval means only that these two **names refer to the same card concept**. It does not approve a same-artwork or regional-printing edge. When no proposed English name is right, reject all rows for that Japanese name.
3. For every non-pending decision, fill `reviewer`, `reviewed_at` (timestamp with UTC offset), and `evidence_note`. For approval, also set `ja_identity_checked`, `en_identity_checked`, and `translation_checked` to `yes`. The template records a claimed reviewer ID; it does not authenticate the person.
4. Keep the proposal ID, source digest, names, card IDs, and links unchanged. The compiler rejects changed frozen fields, duplicate rows, omitted rows, and conflicting approvals for the same Japanese or English name.

Run the compiler on a **copy** of the edited sheet:

```bash
python3 -m scripts.concept_review_packet compile-reviewed \
  --queue catalog/concept-review-queue.jsonl \
  --sheet reviewed-concepts.csv \
  --output reviewed-concepts-import.jsonl
```

The compiler writes import-ready alias revisions but does not modify the database. Inspect that file, then use `python3 -m pokemon_index --db catalog-index.sqlite3 import-bilingual-concepts reviewed-concepts-import.jsonl`. Regenerate the relationship candidate queue after importing. Any approved alias can retrieve candidates; it still cannot create a verified graph edge without separate card-specific review of artwork and finish by two reviewers.

The untouched template compiles to **zero approved aliases**. It is intentionally left pending for a real reviewer. Do not use candidate generation output to fill the independent blind gold answers. Once both tasks are reviewed independently, report recall@K and review workload by retrieval signal rather than treating the number of catalog cards or proposals as quality.

## Rebuild this packet

```bash
python3 -m scripts.concept_review_packet build --db catalog-index.sqlite3 \
  --exclude-anchors catalog/relationship-coverage-anchors.jsonl \
  --exclude-anchors catalog/relationship-pilot-anchors.jsonl \
  --queue concept-review-queue.jsonl --sheet concept-review-template.csv \
  --audit concept-review-audit.json
```

The command refuses to overwrite existing output. The packet depends on the pinned catalog, category, and illustrator data in `catalog-index.sqlite3` and records the selection strategy and source digest for reproducibility.

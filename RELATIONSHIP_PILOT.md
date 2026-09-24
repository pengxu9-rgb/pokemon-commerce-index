# Japanese–English card relationship pilot

This pilot starts the card-level relationship graph without waiting for a marketplace feed. It contains **19 selected Japanese identities** and **40 retrieval candidates** across 18 of those identities. The remaining S6a supplemental identity has no character or artist facet and is recorded as a catalog gap in [`catalog/relationship-pilot-audit.json`](catalog/relationship-pilot-audit.json). Eight candidate pairs include an English printing disabled for automatic offer matching, primarily because its collector-number format is not handled by the matcher. That restriction does not prevent a human from reviewing the card relationship. These are selected review cases, not a representative sample of the entire catalog or a measure of matching accuracy.

The candidate generator first requires the complete Pokémon character-ID set and illustrator on both sides. When that returns nothing, it permits an exact character-ID-set match only if the whole result fits the review limit; the sheet names the signal used. This is a way to find pairs to inspect, **not evidence that the art, printing, finish, or price is equivalent**. For example, the Pikachu row finds multiple English printings and promos; the Charizard special illustration rare points to a different English collector number. The reviewer must resolve each pair using card-specific visual evidence. No relationship in the pilot is currently verified.

## Reviewer handoff

Open [`catalog/relationship-pilot-review-template.csv`](catalog/relationship-pilot-review-template.csv) in a spreadsheet and save a working copy in `../../work/relationship-pilot/`. Each row links to the pinned TCGdex metadata file for both identities. Those links identify the source metadata; they are **not visual proof**. Open official card galleries or another image source approved for internal review, compare the full card images and record separate evidence references for the Japanese and English cards. The source snapshot SHA-256 column binds a decision to this exact queue version.

Fill these columns on the working copy:

| Column | Requirement |
| --- | --- |
| `decision` | `localization_counterpart`, `same_artwork`, `collecting_alternative`, `no_relation`, `identity_gap`, or `uncertain` |
| `review_revision` | Start at `1`; increment whenever a submitted decision or evidence changes. Reusing an old revision cannot restore a withdrawn edge |
| `reviewer`, `reviewed_at` | First real reviewer ID and timestamp with UTC offset; the script does not authenticate the person |
| `anchor_evidence_ref`, `candidate_evidence_ref` | Distinct card-specific links or internal evidence references for both sides |
| `anchor_evidence_kind`, `candidate_evidence_kind` | Source kind such as `official_catalog` or `authorized_scan` |
| `anchor_identity_checked`, `candidate_identity_checked` | Set both to `yes` after checking set, number and physical printing identity |
| `artwork_outcome`, `artwork_note` | `same` or `different`, with a card-specific comparison note |
| `finish_outcome`, `finish_note` | `same`, `different` or `not_comparable`, with the foil/reverse/stamp finding |
| `second_reviewer`, `second_decision`, `second_reviewed_at` | A distinct person's independent second decision and timestamp. Matching positive decisions are required for a verified edge |

Use `localization_counterpart` only when the same card design and artwork are confirmed as corresponding regional releases; record finish compatibility separately. Use `same_artwork` for an artwork link without claiming the regional releases are counterparts. These are independent factual claims in the graph, although one review-sheet row records only its primary decision. Use `collecting_alternative` for a useful but different card and explain the collecting rationale; this remains a proposed editorial link. Use `no_relation` for a confirmed false candidate. Choose `identity_gap` if either catalog identity is wrong or too coarse; choose `uncertain` when visual evidence is unavailable. Never infer a positive relationship from a shared artist, Pokédex ID, card number, or rarity alone. Even a verified counterpart keeps its own priceable identity.

This sheet is an internal review artifact. Do not add downloaded card images or unlicensed marketplace data to the repository. The completed sheet may contain nonpublic review links; keep it in the controlled `../../work/` directory.

## Generate and import

The checked-in queue and sheet were generated from the local `catalog-index.sqlite3` snapshot. To reproduce with a fresh catalog database, use new output paths:

```bash
python3 -m scripts.relationship_pilot generate \
  --db catalog-index.sqlite3 \
  --anchors catalog/relationship-pilot-anchors.jsonl \
  --output ../../work/relationship-pilot/queue.jsonl \
  --audit ../../work/relationship-pilot/audit.json \
  --sheet ../../work/relationship-pilot/review.csv
```

After humans have reviewed the spreadsheet, compile it against the unchanged generated queue **and the current catalog database**. A first positive review becomes `proposed`; a second agreeing reviewer can make a counterpart or artwork link `verified`. A negative re-review rejects the previous active claim, and changing the primary positive decision withdraws earlier pilot claims of another type. Each submitted revision produces stable assertion IDs for safe retries. The compiler rejects changed card IDs or source snapshot hashes, incomplete positive evidence and stale revisions. The importer checks the review fingerprint and current pair head again in a write transaction, so an old compiled file cannot replace a newer claim. If the graph changes between compilation and import, increment the review revision and recompile against the current database. A reviewed relationship may connect a card still disabled for automatic offer matching; the relationship does not change that restriction. Compilation writes an import file; it does **not** change the catalog database.

```bash
python3 -m scripts.relationship_pilot compile-reviewed \
  --db catalog-index.sqlite3 \
  --queue catalog/relationship-pilot-queue.jsonl \
  --reviews ../../work/relationship-pilot/review.csv \
  --output ../../work/relationship-pilot/verified-assertions.jsonl

python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-relationships ../../work/relationship-pilot/verified-assertions.jsonl
```

Keep the completed sheet alongside the import file. Negative and uncertain decisions remain in the sheet and are included in the compiler's audit counts; they also generate rejection events when a prior pair claim must be withdrawn. The existing ledger records all claim changes as append-only events. Verified imports require a versioned evidence object with both endpoint IDs, sources, identity checks, review times and two distinct agreeing reviewers, including through direct `import-relationships`. This checks traceability and completeness, not whether a human actually looked at the card. Disagreements remain proposed until adjudicated. Public display still needs an approved data and image rights basis.

## Next measurement

Once this pilot is actually reviewed, report the number of verified, rejected, identity-gap, and uncertain pairs; false candidates by failure mode; and the share of anchor cards with at least one verified counterpart. Then add identities only for documented `identity_gap` cases or unmatched authorized listings. Live regional prices and merchant recommendations remain gated on a permitted API feed and source-specific use rights.

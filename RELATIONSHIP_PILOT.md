# Japanese–English card relationship pilot

This pilot starts the card-level relationship graph without waiting for a marketplace feed. It contains **19 selected Japanese identities** and **40 retrieval candidates** across 18 of those identities. The remaining S6a supplemental identity has no character or artist facet and is recorded as a catalog gap in [`catalog/relationship-pilot-audit.json`](catalog/relationship-pilot-audit.json). Eight candidate pairs include an English printing disabled for automatic offer matching, primarily because its collector-number format is not handled by the matcher. That restriction does not prevent a human from reviewing the card relationship. These are selected review cases, not a representative sample of the entire catalog or a measure of matching accuracy.

The candidate generator uses the same single Pokémon character ID and illustrator on both sides. This is a way to find pairs to inspect, **not evidence that the art, printing, finish, or price is equivalent**. For example, the Pikachu row finds multiple English printings and promos; the Charizard special illustration rare points to a different English collector number. The reviewer must resolve each pair using card-specific visual evidence. No relationship in the pilot is currently verified.

## Reviewer handoff

Open [`catalog/relationship-pilot-review-template.csv`](catalog/relationship-pilot-review-template.csv) in a spreadsheet and save a working copy in `../../work/relationship-pilot/`. Each row links to the pinned TCGdex metadata file for both identities. Those links identify the source metadata; they are **not visual proof**. Open official card galleries or another image source approved for internal review, compare the full card images and record separate evidence references for the Japanese and English cards.

Fill these columns on the working copy:

| Column | Requirement |
| --- | --- |
| `decision` | `localization_counterpart`, `same_artwork`, `collecting_alternative`, `no_relation`, `identity_gap`, or `uncertain` |
| `reviewer` | The real person's reviewer ID; the script does not authenticate this identity |
| `anchor_evidence_ref`, `candidate_evidence_ref` | Distinct card-specific links or internal evidence references for both sides |
| `artwork_note` | What was compared, or why the relationship cannot be determined |
| `finish_note` | Foil/reverse treatment and other printing differences; required for a positive relation |

Use `localization_counterpart` only when the same card design and artwork are confirmed as corresponding regional releases and the finish is comparable. Use `same_artwork` if the art matches but the finish, framing, or card treatment differs. Use `collecting_alternative` for a useful but different card and explain the collecting rationale. Use `no_relation` for a confirmed false candidate. Choose `identity_gap` if either catalog identity is wrong or too coarse; choose `uncertain` when visual evidence is unavailable. Never infer a positive relationship from a shared artist, Pokédex ID, card number, or rarity alone. Even a verified counterpart keeps its own priceable identity.

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

After a human has reviewed the spreadsheet, compile it against the unchanged generated queue. The compiler rejects changed card IDs and positive decisions missing a reviewer, two-sided evidence, artwork notes, or finish notes. A reviewed relationship may connect a card still disabled for automatic offer matching; the relationship does not change that restriction. Compilation writes an import file; it does **not** change the catalog database.

```bash
python3 -m scripts.relationship_pilot compile-reviewed \
  --queue catalog/relationship-pilot-queue.jsonl \
  --reviews ../../work/relationship-pilot/review.csv \
  --output ../../work/relationship-pilot/verified-assertions.jsonl

python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-relationships ../../work/relationship-pilot/verified-assertions.jsonl
```

Keep the completed sheet alongside the import file. Negative and uncertain decisions remain in the sheet and are included in the compiler's audit counts; only positive reviewed decisions become relationship assertions. The existing ledger records them as append-only events and allows later reversal. A second reviewer should spot-check positive decisions and all disputed cases before the assertions are used in buyer-facing discovery. Public display still needs an approved data and image rights basis.

## Next measurement

Once this pilot is actually reviewed, report the number of verified, rejected, identity-gap, and uncertain pairs; false candidates by failure mode; and the share of anchor cards with at least one verified counterpart. Then add identities only for documented `identity_gap` cases or unmatched authorized listings. Live regional prices and merchant recommendations remain gated on a permitted API feed and source-specific use rights.

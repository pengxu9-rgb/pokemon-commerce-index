# Bilingual concept review, v2

Use the [v2 review CSV](catalog/concept-review-v2-template.csv) with the immutable [proposal queue](catalog/concept-review-v2-queue.jsonl) and [selection audit](catalog/concept-review-v2-audit.json). The v1 packet remains in the repository as an audit of the original shortlist; do not fill it with new decisions.

This packet retains all 36 v1 name pairs and adds three source-backed Trainer proposals: ルリナ → Nessa, ツツジ → Roxanne, and マスタード れんげきのかた → Rapid Strike Style Mustard. Its **human review template has 39 pending rows** covering the same 22 Japanese names. The fourth identified gap, マグマ団のしたっぱ → Team Magma Grunt, has no English pinned TCGdex card record in this catalog; only an unverified API-family identity is present. It remains a documented source gap rather than an invented source-backed proposal. None of the hints is a human-approved translation.

Japanese and English card names, categories and pinned source-file hashes were rechecked for all 39 rows (65 distinct source cards). The packet excludes the earlier blind and pilot Japanese names. Eleven Trainer name pools had additional artist-based options beyond the curated v2 subset; the `omitted_name_count` column exposes that incompleteness. The packet is not a recall sample or a complete bilingual dictionary.

## Review and evidence retention

1. Follow both pinned source links. Confirm the names describe the same card concept, using card-specific official evidence where the source metadata is incomplete. TCGdex source text sometimes omits type symbols, so effect text alone is not always decisive. Record extra official evidence in `extra_source_ja` and `extra_source_en`, plus a concise `evidence_note`.
2. Set `decision` to `approve`, `reject`, or `uncertain`; leave `pending` until reviewed. Every decision requires a reviewer ID, timestamp with UTC offset, and rationale. An approval also requires `ja_identity_checked`, `en_identity_checked`, and `translation_checked` set to `yes`. These fields record the reviewer's assertion; the CSV does not authenticate the person.
3. Keep proposal IDs, source digest, card IDs, names and links unchanged. `ja_match_eligible` and `en_match_eligible` describe **offer matching**, not whether the pinned source can be inspected for a name concept. One proposal uses an English gallery record with `en_match_eligible=0`; reviewing its name does not lift that restriction.
4. Preserve the edited CSV as a review artifact. The compiler emits a JSON bundle containing all non-pending decisions, their rationale and extra evidence, the complete source snapshot, and any approved concept revisions. Rejections and uncertainty are retained too. The bundle import is atomic and idempotent: it requires a referenced review event for each approved alias, and a changed alias rolls back the batch. The low-level concept import helper remains available only for fixtures and migrations.

```bash
python3 -m scripts.concept_review_packet compile-reviewed \
  --queue catalog/concept-review-v2-queue.jsonl \
  --sheet reviewed-concepts-v2.csv \
  --output reviewed-concepts-v2.bundle.json
python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-concept-review-bundle reviewed-concepts-v2.bundle.json
```

The untouched template compiles to zero review events and zero aliases. **The human template remains entirely pending.** Following explicit user authorization, two independent AI reviews agreed on all 39 proposals and an AI-attributed bundle approved 21 internal name aliases; 18 rejections are retained as review events. These AI approvals retrieve relationship *candidates* and do not represent human certification. A factual printing relationship still needs its separate two-reviewer artwork, finish and identity review. See [AI_CONSENSUS_IMPORT.md](AI_CONSENSUS_IMPORT.md).

## Remaining build gates

- Obtain pinned or official card-specific English evidence for Team Magma Grunt, or leave that Japanese name unsupported.
- Run real human concept review on the still-pending human template, then use a superseding-revision workflow for any correction (not yet implemented). Keep the 30-anchor blind gold exercise separate from this selected packet.
- Measure proposal precision, names with a correct candidate, missed-name reasons, and reviewer effort by signal. The v2 packet is intentionally selected for review and cannot establish population recall.
- Expand the concept model to allow multiple reviewed language-specific aliases before broad Basic Energy or historical-name coverage. Exact printing identities and their price eligibility remain separate.

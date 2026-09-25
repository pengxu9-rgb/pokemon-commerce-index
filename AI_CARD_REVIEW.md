# AI-first card and cross-region review

The first 25 v6 pairs now have source-bound, hashed images on both sides and a
Gemini artwork decision. All 25 were judged `same`; this is a selected pilot,
not a measured accuracy rate. We imported 25 `proposed` `same_artwork` edges
into the local relationship graph. The graph exposes them separately as
`ai_artwork_candidates` with `price_comparable=false`.

## What AI handles now

1. Match Japanese and English card identity to pinned set, number and name
   metadata. For 13 missing Japanese TCGdex images, use exact matching records
   from the pinned PTCG-database checkout (`bc5a2698eb9af858feb0280d579fd5fd0f0273e2`)
   and fetch the linked official Pokémon Japan image transiently. Store URL,
   metadata hash and image hash, never image bytes. The image source's rights
   remain with its owner; this is internal review, not image redistribution.
2. Reuse English TCGdex images only if an earlier source-bound audit recorded
   the same image hash. Two additional assets are pinned in
   `catalog/concept-review-v6-en-asset-rescue.jsonl`; the model must confirm
   the visible English card name and collector number or abstain.
3. Ask Gemini to compare artwork. The generated decision is evidence for
   discovery, not a claim of identical physical printing.
4. Compare catalog variant and rarity labels as *coarse* metadata. Of the 25
   pairs, 13 have aligned labels (`nominal_variant_peer`); 12 are
   `artwork_peer_only`. Neither class permits merging price series or publishing
   a numerical cross-region spread from card metadata alone.

## Remaining automated gates

When Buy&Ship or another authorized feed supplies listing photos and prices,
evaluate each offer against its exact printing first. An AI vision pass should
read collector number, language, set symbol, foil pattern and any edition stamp
from listing photos. A separate pass should assess front/back condition and
visible defects. Low-resolution images, glare, missing back photos and
disagreement must yield `need_more_photos` or `unresolved`; do not impute a
grade. Cross-region recommendation may compare landed costs only after the
listing identity, grade or raw condition bucket, and fee/FX timestamps are
explicitly available. Japanese and English prices remain separate market
series even when their artwork matches.

Human review is an exception lane for conflicting evidence, high-value
transactions, disputed condition, and validation sampling. To replace human
certification for physical variants, collect an independently adjudicated
evaluation set and require agreement from independent AI models plus source
metadata. Repeated calls to the same model do not count as independent votes.

## Reproduce the scoped graph evidence

`catalog/concept-review-v6-ai-comparability.jsonl` is the card-level output;
`catalog/concept-review-v6-ai-comparability-audit.json` gives the counts.
`catalog/concept-review-v6-ai-artwork-assertions.jsonl` contains the 25
append-only graph proposals. No card image is committed. The source-specific
image audit is in the four artwork audit files referenced by the compiler.

```bash
python3 -m scripts.compile_ai_card_comparability \
  --queue catalog/concept-review-v6-expanded-first-pass-queue.jsonl \
  --pass catalog/concept-review-v6-first-pass-artwork-gemini.csv catalog/concept-review-v6-first-pass-artwork-gemini-audit.json \
  --pass catalog/concept-review-v6-buddy-poffin-gold-artwork-gemini.csv catalog/concept-review-v6-buddy-poffin-gold-artwork-gemini-audit.json \
  --pass catalog/concept-review-v6-official-jp-artwork-triage-v2.csv catalog/concept-review-v6-official-jp-artwork-audit-v2.json \
  --pass catalog/concept-review-v6-final-two-artwork-triage.csv catalog/concept-review-v6-final-two-artwork-audit.json \
  --ignore-superseded-candidate 1b0d383b02404911d5f8 \
  --output /tmp/ai-comparability.jsonl --report /tmp/ai-comparability-audit.json
python3 -m scripts.build_ai_artwork_assertions \
  --input /tmp/ai-comparability.jsonl --output /tmp/ai-artwork-assertions.jsonl
python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-relationships /tmp/ai-artwork-assertions.jsonl
```

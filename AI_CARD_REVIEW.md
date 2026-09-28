# AI-first card and cross-region review

The expanded v6 review covers all 88 candidate pairs: 48 `same`, 39
`different`, and one `insufficient_images`. Eighty-seven have hashed images on
both sides. The one gap has two official Japanese records for the same set,
number and name, so the resolver deliberately abstained. This is a selected
retrieval pool, not a measured accuracy rate. We imported 48 `proposed`
`same_artwork` edges into the local relationship graph. The graph exposes them
separately as `ai_artwork_candidates` with `price_comparable=false`.

## What AI handles now

1. Match Japanese and English card identity to pinned set, number and name
   metadata. For missing Japanese TCGdex images, use exact matching records
   from the pinned PTCG-database checkout (`bc5a2698eb9af858feb0280d579fd5fd0f0273e2`)
   and fetch the linked official Pokémon Japan image transiently. Store URL,
   metadata hash and image hash, never image bytes. The image source's rights
   remain with its owner; this is internal review, not image redistribution.
2. Reuse English TCGdex images if an earlier source-bound audit recorded the
   same image hash. Otherwise discover the card-specific CDN asset and require
   the model to confirm the visible name and collector number. Two early assets
   are explicitly pinned in
   `catalog/concept-review-v6-en-asset-rescue.jsonl`; the model must confirm
   the visible English card name and collector number or abstain.
3. Ask Gemini to compare artwork. The generated decision is evidence for
   discovery, not a claim of identical physical printing.
4. Compare catalog variant and rarity labels as *coarse* metadata. Of the 88
   pairs, 15 have aligned labels (`nominal_variant_peer`), 33 are
   `artwork_peer_only`, 39 have different artwork and one lacks conclusive
   image evidence. None permits merging price series or publishing
   a numerical cross-region spread from card metadata alone.

## 商品级自动门槛已建，等待授权真实数据

The offer pipeline is now implemented. An authorized gateway photo array is
retained without assuming its order. Gemini can route transient images to
front/back, then inspect exact printing, visible finish and raw condition. A
second independent model family must agree before a listing becomes eligible.
Missing backs, uncertain identity/finish and model conflicts block comparison.
Fresh listing-bound landed quotes must include FX, fee and tax evidence refs.
Japanese and English prices remain separate market series even when their
artwork matches. A proposed artwork edge now blocks the numeric comparator;
only a verified edge can return a contextual landed **ask** spread,
not a verified sale or same-SKU price index. All current offer tests use
synthetic data; no live Buy&Ship feed or user-facing price is claimed.

Human review is an exception lane for conflicting evidence, high-value
transactions, disputed condition, and validation sampling. To replace human
certification for physical variants, collect an independently adjudicated
evaluation set and require agreement from independent AI models plus source
metadata. Repeated calls to the same model do not count as independent votes.

## Reproduce the scoped graph evidence

`catalog/concept-review-v6-expanded-ai-comparability.jsonl` is the card-level
output; the adjacent audit JSON gives the counts. The expanded AI artwork
assertions file contains 48 append-only graph proposals. No card image is
committed. The source-specific image audit is in the artwork audit files below.

```bash
python3 -m scripts.compile_ai_card_comparability \
  --queue catalog/concept-review-v6-expanded-relationship-queue.jsonl \
  --pass catalog/concept-review-v6-first-pass-artwork-gemini.csv catalog/concept-review-v6-first-pass-artwork-gemini-audit.json \
  --pass catalog/concept-review-v6-buddy-poffin-gold-artwork-gemini.csv catalog/concept-review-v6-buddy-poffin-gold-artwork-gemini-audit.json \
  --pass catalog/concept-review-v6-official-jp-artwork-triage-v2.csv catalog/concept-review-v6-official-jp-artwork-audit-v2.json \
  --pass catalog/concept-review-v6-final-two-artwork-triage.csv catalog/concept-review-v6-final-two-artwork-audit.json \
  --pass catalog/concept-review-v6-expanded-remaining-artwork.csv catalog/concept-review-v6-expanded-remaining-artwork-audit.json \
  --output /tmp/ai-comparability.jsonl --report /tmp/ai-comparability-audit.json
python3 -m scripts.build_ai_artwork_assertions \
  --input /tmp/ai-comparability.jsonl --output /tmp/ai-artwork-assertions.jsonl
python3 -m pokemon_index --db catalog-index.sqlite3 \
  import-relationships /tmp/ai-artwork-assertions.jsonl
```

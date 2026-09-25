# Astra independent concept review — v6 stage 1

Reviewed all 25 proposals in queue order. Decisions: **15 approve, 10 reject, 0 uncertain**. Decisions apply only to bilingual name concepts.

## Evidence and integrity

- Independently inspected both source card names, Trainer category/subtype and distinctive English/Japanese effect text for every proposal. No Sol output was read.
- Pinned checkout HEAD: `a211f11f3ba57d56c65c5ac33be35b77d3280757`.
- All 25 snapshot SHA-256 values verified using sorted-key, UTF-8 JSON with `ensure_ascii=False` and default separators, the producer’s serialization. All frozen fields agree with their queue fields.
- All 50 referenced source-card SHA-256 checks passed; each local file also matched its Git blob at the pinned commit. No missing English/Japanese names, subtypes or effects were found.
- Local evidence only. This review makes no physical-printing, artwork, variant, legality, price or market-equivalence claim and does not independently authenticate official card images.

## Source anomalies and decision limits

- Row 16, Metal Goggles / メタルゴーグル: Japanese effect omits the English Metal-Pokémon restriction. Approve the unambiguous transliterated name concept, supported by the distinctive paired 30-damage reduction and damage-counter prevention; do not treat the source text as exact rules equivalence.
- Row 19, Professor Turo’s Scenario / フトゥー博士のシナリオ: Japanese source file contains an unrelated Korean effect. English and Japanese effects support the proposed concept; Korean text was not used.
- Row 23, Lumiose Galette / ミアレガレット: English regulation mark J differs from Japanese I. Name and distinctive 20-heal/one-status-removal effect support the concept; printing or legality equivalence is outside scope.
- Ten rejected proposals share a subtype/artist or superficial numeric signal while their named objects/characters and distinctive effects differ. These are substantive concept mismatches, not merely different printings.

## Deliverable

`catalog/concept-review-v6-stage1-astra.csv` contains one independent decision for each proposal, in original queue order, with the original snapshot SHA, rationale and evidence limits. Queue and template were not modified; no import was performed.

# Path from relationship candidates to a production discovery graph

## What the current number means

The 30-anchor set is deliberately concentrated on hard cases and has no adjudicated cross-region answers. Its 17/30 candidate reach is a diagnostic, not population recall. The latest generator produces 67 review candidates: 42 from exact character-set and illustrator agreement, 25 from a bounded exact character-set fallback. It has no trainer, energy, missing-character-facet or unverified supplemental path yet. Increasing candidate count without independently labelled positives can make the number look better while making review cost worse.

The 55,165 indexed card identities are useful as an internal catalog. They are not 55,165 verified relationship nodes. The priceable identity remains the exact printing; a graph edge cannot transfer a price, condition or availability claim to a different printing.

## Build the missing retrieval signals

| Signal | Work | Claim allowed before review |
| --- | --- | --- |
| Complete Pokémon character set + artist | Implemented. Match all character IDs, not one overlapping character. Keep an exact-signature fallback only when its whole candidate set fits the review limit. | Candidate for inspection only. |
| Bilingual card concept | Create a versioned, source-backed Japanese–English name/concept table for Pokémon, trainers and energy. Keep concept identity separate from printings. Extract card category and trainer/energy type from pinned source fields; record the source file or licensed API response for each name. Curate conflicting translations. | Same concept/name candidate; never same artwork or regional printing. |
| Regional release context | Maintain an evidence-backed set/release crosswalk, including promos and reprints. Use release window, category, artist and set family to rank candidates, with explicit missing-data handling. | Ranking signal only. Equal card numbers across regions are not identity proof. |
| Artwork | If card-image use is authorized, derive internal artwork fingerprints or embeddings from approved sources, retain source rights and model version, and verify how crops, stamps and holo patterns affect matching. Do not ship or redistribute source images without display rights. | Same-artwork proposal only; human confirmation still precedes a factual graph edge. |
| Reviewed edge | Keep the existing append-only, two-reviewer evidence and retraction workflow. Use typed links for counterpart, same artwork and collecting alternative. | Only verified, display-authorized edges may support factual buyer-facing claims. |

TCGdex language localization can supply name text where the *same source card ID* exists in multiple languages. It does not by itself identify the Japanese physical release corresponding to a separate English set and number. Treat it as a concept alias source, not an automatic JP–EN printing edge.

## Make retrieval measurable

1. Lock independent, card-specific gold answers before looking at generator output. Expand the 30-anchor canary into a larger stratified set with sufficient positive pairs in each intended launch category. Include negatives, unresolved identities, reused art, finish differences, promos, trainers and energy.
2. Report **recall@K** separately for counterpart and artwork answers, by category and by source completeness. Report review workload as candidates per true positive and precision@K. Missing or ambiguous identities remain outside the positive denominator and are counted separately.
3. Give each retrieval channel its own audit and cap. A broad artist-only search that returns hundreds of cards is an abstention or a request for more information, not an apparent recall success.
4. Audit verified-edge precision independently. A candidate can be false without being buyer-facing; a verified false counterpart is a product defect. Require a confidence interval and an explicit error budget before publishing a supported category.
5. Once an authorized listing feed arrives, measure coverage by observed listing volume and value. Catalog-wide card count alone is not the right prioritization metric.

## Ship a supported slice

Production should first expose a **known-good, reviewed subset** of high-demand exact printings. For an unsupported card or relation type, show the exact catalog identity and ask a clarifying question or state that a counterpart is unverified. Keep recommendations and live prices tied to exact card, condition, source and observation time. Do not use the relationship graph as a price aggregation shortcut.

The bilingual concept/alias contract, pinned-source category extraction, and bounded Trainer/Energy candidate channel are now implemented; see [BILINGUAL_CONCEPT_CONTRACT.md](BILINGUAL_CONCEPT_CONTRACT.md). The source snapshot classifies 35,073 cards. A [first source-backed human review packet](CONCEPT_REVIEW_GUIDE.md) now contains 36 pending JA–EN name proposals across 22 non-blind Japanese names. No bilingual alias has yet been approved, so the independent 30-anchor probe remains at 17 anchors and 67 review candidates. The next data task is human review of that packet and independent adjudication of the blind gold answers before computing recall@K. Buy&Ship is not needed to build this graph layer; its feed is needed later to prioritize by actual market demand and to attach live offers.

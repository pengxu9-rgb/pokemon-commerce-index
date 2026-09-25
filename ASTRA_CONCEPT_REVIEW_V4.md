# Independent Astra concept review v4

Reviewed all 125 proposals across 25 Japanese names. Decisions: **20 approve, 104 reject, 1 uncertain**. This is an AI review, not a human review. No aliases or graph edges were imported by this reviewer. No Sol v4 verdicts or other v4 agent verdicts were read.

## Evidence checks

For every queue row, both pinned TCGdex TypeScript card files were opened locally at `../../work/tcgdex-public`. All 250 card-file SHA-256 comparisons passed. The source snapshot hash was independently recomputed with sorted-key, Unicode-preserving JSON; all 125 passed. All frozen queue fields matched the corresponding queue values. The localized names, Trainer category, and Supporter/Item/Tool subtype extracted from both files matched the proposal. All 250 referenced set-file SHA-256 comparisons also passed. Every Japanese and English localized effect was read and compared semantically. Ranking score, release proximity and shared illustrator were treated solely as retrieval hints.

The CSV records proposal IDs and snapshot hashes, so these verdicts are bound to the reviewed packet. Approval covers a bilingual name concept, not a physical printing relationship, artwork equivalence, market price comparability, or a rules certification.

## Exceptions

- `0ec2b6105a38cd25fb34`, のろいのおふだ / Spell Tag: **uncertain**. Names and the four-counter distribution after an attack KO align, but pinned English says Psychic Pokémon and the extracted Japanese effect has no type qualifier. The [official Japanese card page](https://www.pokemon-card.com/card-search/details.php/card/35281) was opened; its text extraction likewise omits the type symbol. Fetching its card image failed with cache miss. This review therefore does not assume the missing symbol. A visual check of the official card is needed to resolve the condition.
- `74708c2ced11cc576a2b`, アカギ / Cyrus ◇: **approve for the specific concept**, with a material source limitation. Pinned English requires Water/Metal in play, while Japanese requires it in the Active Spot. [Official Cyrus Prism Star errata](https://play.pokemon.com/en-ca/resources/documents/tcg-errata/) explicitly corrects the positional requirement to Active. The distinctive Bench reduction matches. The Japanese source name omits the Prism Star marker, so this is not a blanket approval for every card named Cyrus.
- `95486fafd1c667032f26`, グラジオ / Gladion: both sources implement the characteristic self-exchange with a face-down Prize. English additionally states that playing from somewhere other than hand does nothing; Japanese describes exchanging this card. This wording limit is retained in the CSV.

The rejected pairs have concrete differences in effect, cost, target, or character/item concept, recorded separately for each proposal. Examples include Looker versus Hau (bottom of deck versus usual draw), Spell Tag versus Vengeful Punch (distributing counters versus attacker only), and Exp. Share versus Wishful Baton (receiving one Energy versus moving up to three away from the bearer).

## Output validation

The review CSV has exactly 125 unique proposal IDs, one for every queue row, and preserves every queue snapshot hash. Counts were checked from the written CSV. Official web corroboration above was consulted only for the two pinned-source discrepancies; the remaining decisions rely on the fixed local source files.

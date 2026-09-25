# Independent Astra concept review v5

Reviewed all 125 proposals covering 25 Japanese names: **24 approve, 100 reject, 1 uncertain**. This is an independent AI review, not human review. No Sol v5 output was read. This reviewer did not edit the human template or import aliases or graph edges.

## Evidence checks

Both pinned TypeScript card sources were opened locally under `../../work/tcgdex-public` for every proposal. All 250 card SHA-256 comparisons and all 250 referenced set SHA-256 comparisons passed. All 125 source snapshot hashes were recomputed from sorted-key, Unicode-preserving JSON and passed; every frozen field matched its queue value. All 250 localized names, categories and Trainer subtypes matched their queue values. The first extraction attempt stopped on braces inside English type tokens; a corrected quoted-string extractor completed the checks and preserved those tokens.

Every localized effect was read and compared for the bilingual name concept. Variations across Japanese printings were checked: two rejected Bug Catching Set candidates have Japanese source files missing Grass symbols, and the approved Great Ball source uses a slightly different optional-selection wording. Ranking, date proximity and shared illustrators were treated only as retrieval hints. No live web corroboration was needed to make the recorded decisions; the unresolved missing-effect case stays uncertain.

## Exceptions and limits

- **大地の封印石 / Earthen Seal Stone: uncertain.** The Japanese file contains generic Tool attachment boilerplate only. The English file grants access to a VSTAR Power but omits its defining attack. Names plausibly correspond, but there is no distinctive effect to compare. Card-specific corroboration is required before approval. The other four candidates in this group are rejected on their different object names; the CSV explicitly does not claim a complete Japanese power comparison.
- **カビゴンドール / Snorlax Doll: approve for name concept.** Both sources agree on setup-only play, 120 HP, optional discard, no retreat, no Special Conditions and no Prize on KO. The Japanese extraction omits the Pokémon type symbol; English says Colorless. The strong distinctive concept evidence supports approval, while the omitted type remains unverified.
- **ミツルの思いやり / Wally's Compassion: approve for name concept.** Both heal a Mega Evolution Pokémon ex completely and return the healed Pokémon's Energy to hand. English explicitly conditions return on healing damage. The review does not independently certify zero-damage play rulings.
- **ボスの指令（ゲーチス） / Boss's Orders: approve for name concept.** The switching effect matches, but the Ghetsis parenthetical is present only in Japanese. This does not establish a depicted-character or printing relationship.
- Two rejected むしとりセット candidates omit Grass symbols in Japanese. Their top-seven selection mechanic still differs from the respective English candidates. The approved Bug Catching Set pair has explicit Grass tokens on both sides.

Approvals cover bilingual name concepts only. They do not establish artwork identity, printing equivalence, price comparability, exhaustive rules equivalence or human authorization. Each CSV verdict is tied to its exact proposal ID and source snapshot hash.

## Output validation

`catalog/concept-review-v5-astra.csv` contains exactly 125 unique proposal IDs in queue order, with every snapshot hash unchanged. Counts were checked from the written CSV: 24 approve, 100 reject, 1 uncertain.

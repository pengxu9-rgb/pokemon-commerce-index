# Astra independent concept review v3

Reviewed all 115 proposals independently from Sol. Result: **33 approve, 81 reject, 1 uncertain**. The scope is bilingual Trainer name concepts only.

All 230 referenced local TS file reads matched their pinned SHA-256; all 115 canonical source-snapshot hashes matched. Every Japanese/English source name and Trainer category matched its queue row. Subtype and effect text were inspected on both sides. The files are pinned to TCGdex commit `a211f11f3ba57d56c65c5ac33be35b77d3280757`. Each CSV verdict carries `source_snapshot_sha256` to bind it to that evidence.

The CSV contains a source-specific rationale for every row. Same illustrator and class were treated as retrieval signals; approvals required compatible names and distinctive effect semantics. No Sol v3 output was read. Human templates, aliases and graph edges were not edited.

## Exceptions

- `625083540e9b1435d8ca` — Pokémon Center: **uncertain**. JA PMCG1/083 omits effect and subtype. The literal name translation and Trainer category align, but EN Wizards Black Star Promo 40's healing/Energy-discard effect cannot be verified against the pinned Japanese source. No official card-specific corroboration was located. Keep deferred.
- `8d6b045065dc0fa3c21c` — Stormy Mountains: **approve**. JA S12a/164 omits the Basic Pokémon restriction. The [official S12a 164 card page](https://www.pokemon-card.com/card-search/details.php/card/42425/regu/all) explicitly includes たね and corroborates the EN restriction. The pinned source was not altered.
- Challenge! has no trainerType in its pinned TS file, although these queue pairs are classified Stadium. This is a source/queue subtype discrepancy (rows 14 and 18). Both proposed matches (Player’s Ceremony and Celebratory Fanfare) are rejected by name and effect. Classification agreement alone does not establish a concept.
- `cf9d4a00256bfcf55126` — Flyinium Z: Air Slash: **approve** after checking the Japanese `attacks[]` data as well as the primary effect: four Colorless, 180 damage, next-turn damage/effect prevention. EN includes that attack inside effect text.
- Lance Prism Star's ♢/◇ glyph variation is accepted only for this matching name/effect pair.
- Stealthy Hood's English explicit removal of existing Ability effects is compatible with the Japanese ongoing prevention text for a name-concept verdict; exact rulings were not certified.

These are AI judgments over a shared third-party source, not independent primary-source certification. They do not establish same printing, artwork, rarity, regulation legality, price comparability, or human approval.

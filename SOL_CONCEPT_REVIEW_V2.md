# SOL independent concept review, v2

This is an AI-only second opinion, recorded before reading Astra’s triage. It is not human certification and does not set any `decision` in the human template.

## Source and version check

- Queue: `catalog/concept-review-v2-queue.jsonl`, 39 distinct proposal IDs and 39 verified `source_snapshot_sha256` digests.
- Pinned TCGdex checkout: `a211f11f3ba57d56c65c5ac33be35b77d3280757`; the local checkout HEAD matches the provenance commit.
- Verified SHA-256 bytes for all Japanese and English provenance references: 65 distinct source files, 78 references.
- The local source files are the exact pinned third-party transcriptions. No official print or artwork identity is inferred from this check.

## Comparison

- Agreements: **39/39** (21 approve, 18 reject).
- Disagreements: **none**.
- These are suggested concept equivalences only. No human reviewer has approved them, and they are not factual printing relationships.

| # | Japanese → English | SOL | Astra | Evidence cue |
|---:|---|---|---|---|
| 1 | フレンドボール → Friend Ball | approve | approve | Same Friend Ball name; both effects search a Pokémon matching an opponent Pokémon type. |
| 2 | フレンドボール → Lure Ball | reject | reject | Lure Ball recovers Evolution Pokémon from discard with coin flips; Japanese card searches deck by opponent type. |
| 3 | フレンドボール → PokéNav | reject | reject | PokéNav checks top three deck cards; Japanese card searches deck by opponent type. |
| 4 | オーキド博士のセッティング → Professor Oak’s Setup | approve | approve | Same Professor Oak setup name and up to three differently typed Basic Pokémon to Bench. |
| 5 | ポケモンブリーダー → Pokémon Breeder | approve | approve | Same Pokémon Breeder name and draw two plus heal 20 from Active Pokémon. |
| 6 | ポケモンブリーダー → Lana | reject | reject | Lana heals Water Energy Pokémon by 50; Japanese Breeder draws two and heals Active by 20. |
| 7 | ロケット団のアテナ → Team Rocket's Ariana | approve | approve | Ariana name and draw to five, or eight with all Team Rocket Pokémon, match. |
| 8 | ホミカの演奏 → Roxie's Performance | approve | approve | Roxie Performance name and next-turn Poisoned Pokémon retreat lock match. |
| 9 | ホミカの演奏 → Lisia's Appeal | reject | reject | Lisia Appeal switches a Benched Basic and Confuses it; Japanese Roxie locks Poisoned retreat. |
| 10 | オーリム博士の気迫 → Professor Sada's Vitality | approve | approve | Professor Sada name and attach Basic Energy from discard to up to two Ancient Pokémon, then draw three, match. |
| 11 | オーリム博士の気迫 → Poppy | reject | reject | Poppy moves two Energy between Pokémon; Japanese Sada accelerates from discard and draws. |
| 12 | マグマ団のしたっぱ → Phoebe | reject | reject | Phoebe bypasses effects for VMAX attack damage; Japanese Team Magma Grunt discards hand card and draws. |
| 13 | グズマ&ハラ → Guzma & Hala | approve | approve | Guzma & Hala name and Stadium search with optional discard-two Tool/Special Energy search match. |
| 14 | ミカンのまなざし → Jasmine's Gaze | approve | approve | Jasmine Gaze name and 30 damage reduction for all own Pokémon next turn match. |
| 15 | キクコ → Agatha | approve | approve | Agatha name and moving up to three damage counters from own Active to opponent Active match. |
| 16 | キクコ → Boss's Orders | reject | reject | Boss Orders switches opponent Benched Pokémon; Japanese Agatha transfers damage counters. |
| 17 | ピーニャ → Giacomo | approve | approve | Giacomo name and discard one Special Energy from each opponent Pokémon match. |
| 18 | ピーニャ → Professor's Research (Professor Oak) | reject | reject | Professor Research discards hand and draws seven; Japanese Giacomo removes opponent Special Energy. |
| 19 | ツツジ → Roxanne | approve | approve | Roxanne name and three-or-fewer opposing Prizes condition, hand shuffle, six/two draws match. |
| 20 | ツツジ → Lana's Aid | reject | reject | Lana Aid retrieves non-rule-box Pokémon or Basic Energy; Japanese Roxanne shuffles both hands and draws six/two. |
| 21 | マスタード れんげきのかた → Rapid Strike Style Mustard | approve | approve | Rapid Strike Style Mustard name and official English card rule match Japanese last-card hand, Rapid Strike recovery, draw five. |
| 22 | マスタード れんげきのかた → Giacomo | reject | reject | Giacomo removes opponent Special Energy; Japanese Mustard benches Rapid Strike Pokémon from discard and draws. |
| 23 | マスタード れんげきのかた → Professor's Research (Professor Oak) | reject | reject | Professor Research discards hand/draws seven; Japanese Mustard benches Rapid Strike Pokémon and draws five. |
| 24 | 危ない廃墟 → Lively Stadium | reject | reject | Lively Stadium raises Basic Pokémon HP by 30; Japanese ruins puts two damage counters on Benched non-Darkness Basics. |
| 25 | 危ない廃墟 → Neutralization Zone | reject | reject | Neutralization Zone blocks attack damage to rule-box-free Pokémon; Japanese ruins places damage counters on Benching. |
| 26 | 危ない廃墟 → Risky Ruins | approve | approve | Risky Ruins and Japanese ruins both put two damage counters on newly Benched non-Darkness Basic Pokémon. |
| 27 | 危ない廃墟 → Team Rocket's Factory | reject | reject | Team Rocket Factory draws two after a Team Rocket Supporter; Japanese ruins damages newly Benched Basics. |
| 28 | ルリナ → Nessa | approve | approve | Nessa name and retrieving up to four Water Pokémon/Energy from discard match. |
| 29 | ルリナ → Marnie's Pride | reject | reject | Marnie Pride attaches one Basic Energy to Bench; Japanese Nessa retrieves up to four Water cards into hand. |
| 30 | ルリナ → Erika's Invitation | reject | reject | Erika Invitation moves a Pokémon from opponent hand to Bench/Active; Japanese Nessa retrieves Water cards. |
| 31 | ルリナ → Furisode Girl | reject | reject | Furisode Girl searches Basic Pokémon from deck and may switch; Japanese Nessa retrieves Water cards from discard. |
| 32 | ルリナ → Lady | reject | reject | Lady searches up to four Basic Energy from deck; Japanese Nessa retrieves Water Pokémon/Energy from discard. |
| 33 | エネルギー循環装置 → Energy Recycle System | approve | approve | Energy Recycle System name and choice of one Basic Energy to hand or three to deck from discard match. |
| 34 | メディカルエネルギー → Medical Energy | approve | approve | Medical Energy name and Colorless provision plus heal 30 when attached from hand match. |
| 35 | ルミナスエネルギー → Luminous Energy | approve | approve | Luminous Energy name and all-type one Energy except Colorless if another Special Energy attached match. |
| 36 | ブーメランエネルギー → Boomerang Energy | approve | approve | Boomerang Energy name and Colorless provision plus reattach after discarded by attached Pokémon attack match. |
| 37 | ミストエネルギー → Mist Energy | approve | approve | Mist Energy name and Colorless provision plus protection from opponent attack effects match. |
| 38 | レガシーエネルギー → Legacy Energy | approve | approve | Legacy Energy name and all-type one Energy plus once-per-game one fewer Prize on attack KO match. |
| 39 | トリプル加速エネルギー → Triple Acceleration Energy | approve | approve | Triple Acceleration Energy name and three Colorless for Evolution Pokémon with end-turn discard match. |

## Evidence limitations that matter

- **Rapid Strike Style Mustard, proposal `2efe5f5d8acd884f18d1`:** The pinned English TG27 source has a missing-token effect. The [official English Battle Styles card](https://www.pokemon.com/us/pokemon-tcg/pokemon-cards/series/swsh5/132) confirms the concept rules, but is a different printing. The TG27 printing identity still needs direct inspection.
- **Risky Ruins, proposal `3e04f41206441d85ead2`:** The pinned Japanese transcription drops the Darkness symbol in its exclusion. The [official Japanese FAQ](https://www.pokemon-card.com/rules/faq/search.php?freeword=%E5%8D%B1%E3%81%AA%E3%81%84%E5%BB%83%E5%A2%9F&regulation_faq_main_item1=all) identifies non-Darkness Basic Pokémon and resolves the concept comparison.
- **Pokémon Breeder and Professor Sada’s Vitality:** The English text includes an empty-deck play restriction and a conditional draw, respectively, that are not explicit in the Japanese extracts. The names and core effects match; a human should check the wording context.
- **Medical Energy and Luminous Energy:** The Japanese transcription omits Energy type symbols. The names and distinctive effect clauses match, but the missing symbols should be checked on card images.
- **Legacy Energy:** The Japanese source lacks the ACE SPEC marker found in English. This review covers name concepts, not deck-rule or printing attributes.
- **Team Magma Grunt:** The queue only contains an incorrect Phoebe candidate; no supported English pinned candidate is reviewed here.
- All remaining decisions rely on pinned third-party card text and metadata. They have not been independently checked against official artwork or exact printing identity.

## Artifacts

- Independent row verdicts: `catalog/concept-review-v2-sol-review.csv`.
- Astra comparison source: `catalog/concept-review-v2-ai-triage.csv` (read only after the independent CSV was written).

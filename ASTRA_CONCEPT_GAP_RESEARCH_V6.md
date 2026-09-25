# Astra evidence research for five exhausted v6 concepts

Five promising English candidates were found beyond the rejected top-five sets. These are research candidates only: no decisions, approvals, aliases, edges or imports were written. No Sol/Gemini outputs were read.

Pinned revision: `a211f11f3ba57d56c65c5ac33be35b77d3280757`. Local catalog queried read-only: `work/concept-consensus/catalog-index-v6-validation.sqlite3`, `card` table. All five English candidates exist there with `match_eligible=1`; all five Japanese anchors also exist in that catalog.

## ポケパッド → Poké Pad

Both Items search for a Pokémon without a Rule Box, reveal it and put it into hand, then shuffle. Japanese ポケパッド and English Poké Pad identify the same named object.

- JA card ID: `ja:MC:662/742:normal`; subtype: Item.
- Source: `data-asia/M/MC/662.ts`
- Verified SHA-256: `dbbac414d5997dbdd4fa4f16ee172d8eda0a68e1bf0dd1055f0d186a646dcdcb`
- Rule text: 自分の山札からポケモン（「ルールを持つポケモン」をのぞく）を1枚選び、相手に見せて、手札に加える。そして山札を切る。

- EN card ID: `en:ME02.5:198/217:normal`; subtype: Item.
- Source: `data/Mega Evolution/Ascended Heroes/198.ts`
- Verified SHA-256: `c7001eff03acf79abad118ef27a5bc3bad1bbddcfb770df81e11c94d21c612b7`
- Rule text: Search your deck for a Pokémon that doesn't have a Rule Box, reveal it, and put it into your hand. Then, shuffle your deck. (Pokémon ex, Pokémon V, etc. have Rule Boxes.)

Uncertainty/limits: A separate 30th Celebration Poké Pad source has no effect field and was not used as rules evidence. No official card image was inspected; candidate status does not assert physical printing, variant, legality or price equivalence.

## みずの塔 → Tower of Waters

Both Stadiums reduce the retreat cost of all Rapid Strike Pokémon, on both sides, by two Energy. The Japanese water-tower name corresponds to Tower of Waters.

- JA card ID: `ja:S8B:170/184:normal`; subtype: Stadium.
- Source: `data-asia/S/S8b/170.ts`
- Verified SHA-256: `20074d974b0c1bda42f35977015122b45cc3c76035f1fc9073a69a4fd0149ea9`
- Rule text: おたがいの「れんげき」のポケモン全員のにげるためのエネルギーは、それぞれ2個ぶん少なくなる。

- EN card ID: `en:SWSH5:138/163:normal`; subtype: Stadium.
- Source: `data/Sword & Shield/Battle Styles/138.ts`
- Verified SHA-256: `3335b949f5de7e26683b6a8bb7538be7993d042db3f32b2ae2703d779682be91`
- Rule text: The Retreat Cost of each Rapid Strike Pokémon in play (both yours and your opponent's) is ColorlessColorless less.

Uncertainty/limits: English renders two Colorless symbols as ColorlessColorless; this is a text-encoding limitation, not missing numeric meaning. No official card image was inspected; candidate status does not assert physical printing, variant, legality or price equivalence.

## サカキのカリスマ → Giovanni's Charisma

Both Supporters return an Energy attached to the opposing Active Pokémon to the opponent’s hand, then attach an Energy from the user’s hand to the user’s Active Pokémon. Giovanni / サカキ and Charisma / カリスマ agree.

- JA card ID: `ja:SV2A:162/165:normal`; subtype: Supporter.
- Source: `data-asia/SV/SV2a/162.ts`
- Verified SHA-256: `81152b02ce7fae0699737a9fbdc2943d2095696fea651af1b7135306051363eb`
- Rule text: 相手のバトルポケモンについているエネルギーを1個選び、相手の手札にもどす。その後、自分の手札からエネルギーを1枚選び、バトルポケモンにつける。

- EN card ID: `en:SV03.5:161/165:normal`; subtype: Supporter.
- Source: `data/Scarlet & Violet/151/161.ts`
- Verified SHA-256: `2887c5354e58b450758ee05aee92136753165011dc23fd7cfcee10f7204214ef`
- Rule text: Put an Energy attached to your opponent's Active Pokémon into their hand. If you do, attach an Energy card from your hand to your Active Pokémon.

Uncertainty/limits: English explicitly says If you do before attachment; Japanese says afterward. This research supports the name concept, without certifying rules wording equivalence. No official card image was inspected; candidate status does not assert physical printing, variant, legality or price equivalence.

## 霧の水晶 → Fog Crystal

Both Items search for a Psychic Energy or Basic Psychic Pokémon, reveal it, add it to hand and shuffle. The Japanese mist/fog crystal name agrees.

- JA card ID: `ja:S6K:060/070:normal`; subtype: Item.
- Source: `data-asia/S/S6K/060.ts`
- Verified SHA-256: `72197794e930c8ddd1f7edc3f4cbdf06dece8cc22760082b3f6c74eb41867b62`
- Rule text: 自分の山札から[超]タイプのたねポケモンまたは[超]エネルギーを1枚選び、相手に見せて、手札に加える。そして山札を切る。

- EN card ID: `en:SWSH6:140/198:normal`; subtype: Item.
- Source: `data/Sword & Shield/Chilling Reign/140.ts`
- Verified SHA-256: `c5333b8d4c5b1c07c005571fa83fd9a93c1251af29ba24985524cc65b9ae2fe2`
- Rule text: Search your deck for a Psychic Energy card or a Basic Psychic Pokémon, reveal it, and put it into your hand. Then, shuffle your deck.

Uncertainty/limits: No missing relevant Japanese or English rule text found. No official card image was inspected; candidate status does not assert physical printing, variant, legality or price equivalence.

## キャンプセット → Camping Gear

Both Items search the deck for any one card, put it into hand, shuffle and end the user’s turn. Camp set / Camping Gear are consistent object names.

- JA card ID: `ja:S5I:063/070:normal`; subtype: Item.
- Source: `data-asia/S/S5I/063.ts`
- Verified SHA-256: `6460d08a954cf1395b09ad01ba1a57bacdf9f8e35477697d12df5fd5ba602d0e`
- Rule text: このカードを使ったら、自分の番は終わる。自分の山札から好きなカードを1枚選び、手札に加える。そして山札を切る。

- EN card ID: `en:SWSH5:122/163:normal`; subtype: Item.
- Source: `data/Sword & Shield/Battle Styles/122.ts`
- Verified SHA-256: `eb59798316b3ba28e8ea951612f05fe23c4f5b7c8b4c8b5ad04a7734dd435325`
- Rule text: Search your deck for a card and put it into your hand. Then, shuffle your deck. Your turn ends.

Uncertainty/limits: No missing relevant Japanese or English rule text found. No official card image was inspected; candidate status does not assert physical printing, variant, legality or price equivalence.

## Verification summary

All 10 representative source hashes match catalog/queue provenance and the exact pinned Git blobs. Their names, subtypes and distinctive rules were inspected independently. The exhausted ranking reflects a retrieval limitation: viable English evidence remains in the same pinned data. A new review packet can use these source-backed candidates; this report itself grants no approval.

# Fresh v9 question diagnostic

The [v9 source set](sandbox/public_questions/v9/) started with eight new public
posts whose URLs did not overlap v1–v8. Codex opened the posts and transcribed
their original questions. Gemini 3.8 Flash checked only those transcriptions
against the proposed short questions. Six passed both source checks; two were
excluded as unverifiable because the supplied context was too thin. The
[preflight report](sandbox/public_questions/v9/preflight/report.json) retains
the exclusions. This source gate does not certify card facts or market prices.

The six accepted questions, the v5 extractor and planner, the catalog resolver,
and the [official M6 rarity-corrected catalog](CATALOG_M6_RARITY_AUDIT.md) were
hash-pinned in the [manifest](sandbox/public_questions/v9/manifest.json)
before the v5 calls. One question is assigned to a holdout split; the cohort is
far too small to use that split as an accuracy estimate. The unchanged v5
extractor returned 6/6 schema-valid records. The [route report](sandbox/public_questions/v9/route_report.json)
shows no live-offer, paid-sale or buyback action marked ready without an
authorized capability. No current price or buy/sell decision was generated.

Source inspection after the run found these useful gaps:

| Question | Observed route | Review |
| --- | --- | --- |
| 003: Which normal cards can sell individually? | `other` → general explanation | Seller saleability across a class needs its own intent and comparable cohort evidence. |
| 004: Sell SV4a Mew ex SAR 347/190 to a nearby shop | `channel_choice`; buyback terms blocked | Exact catalog coordinates are present, but pinned rarity is missing, so the resolver correctly withholds unique printing status. Official rarity evidence is the next catalog repair. |
| 002 and 006: Sell or hold named SAR cards | `seller_timing`; no exact catalog match | The posts omit the full printed names and card numbers. Request card-face evidence; do not silently map “レックウザ” to “メガレックウザex” or “メガダークライ” to “メガダークライex”. |
| 008: Restart collecting in Japanese or English | `collecting_preference`; asks for preferences and budget | It does not offer a winner or cross-language price comparison without a resolved target. |

These are qualitative decisions by the researcher who prepared the source
questions, not blind human labels or a measured accuracy percentage. A next
planner version should add seller segment saleability, and a next catalog pass
should verify SV4a 347/190 and similar exact-number rarity gaps against official
pages. Any revised planner needs another fresh cohort. Live price and transaction
claims remain gated on authorized marketplace feeds and measured coverage.

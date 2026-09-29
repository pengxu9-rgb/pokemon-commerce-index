# V7 source-checked question diagnostic

This is the first new question batch collected after the v3 planner, Gemini
extractor and catalog resolver were implemented. It is an engineering diagnostic,
not a user-question accuracy estimate. The eight posts are a search convenience
sample: seven English and one Japanese. No current marketplace feed, sale series,
listing photos or seller outcomes were used.

## Collection and source gate

The [candidate questions](sandbox/public_questions/v7/candidates.jsonl) bind eight
new post URLs to short source-condensed questions. The [source evidence](sandbox/public_questions/v7/source_evidence.jsonl)
records the original-post locator, a short anchor and a description of the
opening post. All URLs were checked against v1–v6. Codex inspected the opened
posts and authored the source descriptions; Gemini reviewed those descriptions
and candidate questions without fetching the pages independently. This is two
review paths, but the second inherits any error in the transcribed source.

The first Gemini pass found that question 003 turned an observation about the
cheaper English version into an extra question. The second found that question
006 shifted from why two packaging styles exist to a narrower insert comparison.
Both attempts remain archived in the v7 directory. After the two text corrections,
the [preflight report](sandbox/public_questions/v7/preflight_report.json) accepted
8/8. This is source-fidelity agreement, not card or market truth. The final
[manifest](sandbox/public_questions/v7/manifest.json) pins the questions,
source gate, v3 code and local catalog snapshot before fact extraction.

## Frozen replay

The unchanged Gemini v3.3 extractor produced **8/8 schema-valid fact records**.
The [catalog route report](sandbox/public_questions/v7/catalog_route_report.json)
then ran these facts against the pinned local catalog. It returned zero unique
printings, two multiple-candidate results, two `no_match` results and four
not-attempted results. This says nothing about overall catalog recall or route
accuracy. Live-offer and verified-sale actions were never marked ready.

Three diagnostic gaps are now visible:

1. **Cross-language names.** Question 003 uses English “Double Colourless Energy”
   for a Japanese card, while the catalog has `ダブル無色エネルギー`. Question 005 uses
   “Lillie” for a Japanese promo, while the catalog has `リーリエ`. The current
   resolver's exact-name search labels both as `no_match`; that is too strong
   for a translation or spelling gap. A reviewed bilingual concept can widen
   retrieval, but it cannot establish a physical printing or price equivalence.
2. **Unverified promo identity.** The local catalog contains `397/SM-P リーリエ`
   as `match_eligible=0`. Even after a reviewed name alias finds it, the
   resolver must keep it unverified and request more card evidence. It must not
   use the row to unlock a live price comparison.
3. **Market-trend intent.** Gemini chose `other` for questions 003 and 005,
   both of which ask about a historical price movement or whether to wait to
   buy. V3 has no explicit trend goal or historical-series evidence action.
   It also cannot treat a 2018 or 2020 forum ask as a current quote.

The report records all eight per-question actions and candidate IDs. Reviewing
these rows now makes v7 a diagnostic cohort for future changes; any adjusted
resolver or extractor needs new source posts for a fresh quality estimate.

## Follow-up implementation and next gate

The separate [v2 resolver](pokemon_index/catalog_question_resolver_v2.py) now
uses latest approved bilingual name concepts as retrieval aliases while
preserving the language, set, number, variant and match-eligibility gates.
On v7 question 003 it returns `unresolved_cross_language_name`; on question
005 it finds the reviewed Lillie name alias but returns
`translated_name_scope_unresolved` because “Battle Day” does not establish a
catalog set and number. This is a development replay of v7, not a new score.
The unverified 397/SM-P catalog row remains ineligible for automatic matching.

Next, introduce a price-trend intent and historical-evidence action in a new
planner/extractor version. Run v7 only as regression checks, followed by a
newly sourced cohort. No price trend or purchase-timing recommendation should
be emitted until an authorized time series with coverage and freshness exists.

# Agentic Pokémon card index: graph and recommendation architecture

Prepared after the 1,000-pair Japanese/English visual batch and independent
Astra architecture review, 26 September 2026. The current local catalog has
no marketplace observations or live prices. Every new image-based graph edge
from this batch is `proposed`, not `verified`.

## What the numbering audit says

Of 1,000 deliberately retrieved Japanese/English candidate pairs, Gemini
classified 587 as having the same artwork. In that **selected cohort**, only
8/587 have the same complete printed number, 50/587 the same numerator, and
9/587 the same denominator. Of the 587, 536 differ in both number fields.
This is a property of the review cohort, not a population estimate or a
measurement of visual accuracy. The full [number audit](catalog/relationship-scale-v1-numbering-audit.json)
binds these counts to the [visual results](catalog/relationship-scale-v1-gemini.csv).

The card number is scoped to a release and its numbering system. It is useful
for **finding a card within that release**, not joining Japanese and English
cards by itself. Even the eight same-number/same-artwork candidates can differ
in finish: the Japanese `SV2A 078/165` Master Ball reverse and English
`SV03.5 078/165` normal candidate are separate priceable identities.
Conversely, a Japanese promo and English set card can share artwork while both
number fields differ. A matching denominator is not a print-run count or
proof of scarcity.

## Identity levels

| Level | Required data | What it can answer |
| --- | --- | --- |
| Subject/concept | character, trainer, energy or named theme | “Show me Raichu cards” |
| Game-card concept | rules/text revision, name, mechanics, provenance | “Same playable card?” |
| Artwork | source-bound images and exact/derived/similar status | “Same picture in English?” |
| Release | region, language, set/product/promo campaign, release date | “Where was this printed?” |
| Exact printing | release number plus finish, stamp, edition and printing revision | “Which version do I own or want?” |
| Physical copy/listing | photos, grade, condition, seller, source item ID | “Is this offer the right card and condition?” |
| Price observation | timestamp, ask/list-at-sale/verified-paid evidence, currency, quote | “What does it cost now or what has sold?” |

Preserve existing `card_id`s while adding a structured `release_id`,
`number_namespace`, raw printed number, parsed prefix/numerator/denominator,
region, finish, stamp, edition, and source-native aliases. The current unique
key of language, set, number and variant is a useful internal key, but these
additional fields are needed to avoid hiding physical differences in a free
text variant or attributes blob. Supplementary and multi-record identities
remain match-disabled until their exact printing can be distinguished.

The first implementation step now materializes `card_number_context` for all
55,167 local card identities. Its `number_scope_id` is the **provisional**
language/set-code namespace, not an asserted official release or region. It
parses number components and retains the catalog variant label while leaving
physical finish, stamp and edition unverified. The internal number-explanation
query combines these facts with current review-status edges; equal numbers
alone cannot create a counterpart or a price comparison. The later release,
region and physical-variant evidence model remains to be built.

## Typed relation graph

Do not merge nodes through `same_artwork`, `same_character`, or a matching
number. Store independently evidenced edges such as:

- `uses_artwork(printing, artwork)` with `exact`, `derived`, or `similar` scope.
- `printed_in(printing, release)` and `number_in_release(printing, number)`.
- `variant_of(printing, printing)` for finish/stamp/edition siblings.
- `localization_counterpart(printing, printing)` where the relationship has
  explicit regional and artwork evidence; it may be many-to-many.
- `gameplay_equivalent(game_card_concept, game_card_concept)` for rules-level
  equivalents. The current counterpart guard requires shared artwork, so
  gameplay equivalence needs its own edge type.
- `reprint_of(printing, printing)` with date and changed dimensions.
- `offer_for_printing(listing, printing)` with a versioned resolution and
  observation-level provenance.

Each asserted edge carries `candidate/proposed/verified/rejected` status,
source hashes, model or reviewer identity, timestamp, and what was actually
checked. Negative and uncertain findings remain searchable; they do not
silently disappear. `collecting_alternative` is generated from user intent
and factual edges rather than treated as a permanent equivalence relation.
`price_comparable` is a **query result with conditions**, not a graph edge
that can be transitively followed.

The batch has 587 AI `same_artwork` proposals, 50 different-artwork findings,
351 missing-image cases, three uncertain results and nine model failures.
The proposals are importable into the internal graph and remain explicitly
labelled `proposed`. The 462 Japanese multi-record groups all have distinct
official image bytes, but image-byte differences alone do not identify foil,
stamp, edition or distinct physical printings.

The [blind calibration](RELATIONSHIP_CALIBRATION.md) exposed a distinct
`derived_recolor` lineage: five of the initial 50 `different` findings in a
palette-keyword challenge share composition or linework but differ materially
in color treatment. These five are unverified candidates, not newly verified
`same_artwork` edges. `uses_artwork` must distinguish exact from derived
visual reuse before the agent answers “same picture?”

## Agent questions and minimum evidence

| User question | Graph traversal and evidence | Response boundary |
| --- | --- | --- |
| “Why is the English number different?” | Exact printing → release/number; cross-region artwork or counterpart edge | Explain each numbering scope and edge status |
| “I like this picture; which language is cheapest?” | Artwork → candidate printings → exact current offers → destination quotes | Compare separate current landed asks with condition/finish fixed |
| “Same 025/165, why three prices?” | Release number → variant family → finish/stamp/edition → unit prices | Never pool variant prices |
| “Is the JP–EN gap widening?” | Fixed exact-printing pair → daily series → FX/fees/sample mix | Require enough dated observations; report coverage |
| “Which seller can complete my set?” | Collection goal → missing printings → live seller inventory → basket quote | Do not sum standalone shipping as a basket quote |
| “Does a reprint lower my old card’s value?” | Reprint edge and dates → old/new series and supply | Report observed association and alternatives, not causation |
| “Is this listing in good condition?” | Listing front/back photos → exact identity/finish → independent condition reviews | State the visual bucket and uncertainty, not a grader score |

The agent should distinguish recognition, exploration, comparison, collection
planning and purchase. It asks only for missing constraints that change the
answer. A user may want same artwork, same game card, same exact printing, or
simply a cheaper collecting alternative; those are different traversals.

## Recommendation and price computation

1. Filter hard constraints: exact target or permitted alternative, live offer,
   source rights, condition/grade, destination, and complete fee/FX evidence.
2. Keep ask, list-at-sale and verified-paid series separate by exact printing,
   finish, condition/grade and marketplace. Store observation-level identity
   resolution revisions so corrected card matches can be recomputed visibly.
3. Report coverage: observations, distinct sellers, duplicate physical-copy
   risk, freshness and censored transitions. Avoid calling disappearance a
   sale. Fixed cohorts prevent apparent price trends caused only by changing
   condition or seller mix.
4. Rank eligible offers by the user's goal: lowest landed cost, strongest
   condition evidence, fewer packages, faster arrival, or completion of a
   collection goal. Show a small set of explainable alternatives, with the
   evidence and unknowns behind each.
5. Preserve the relation status in every cross-region comparison. The current
   comparison response now exposes `relationship_status`,
   `relationship_basis`, `artwork_review_count`, `identity_certainty`,
   `comparison_scope` and `excluded_dimensions`. A proposed artwork edge
   cannot produce a numeric cross-region gap; a verified artwork edge is
   required, and even then the result is a contextual ask comparison rather
   than a same-SKU price index.

## Build sequence

1. **Now:** finish image/number audits, retry missing images and model errors,
   inspect a stratified sample of positives and negatives, and keep all
   587 batch artwork claims at proposed status. The provisional number
   context and explanation query are implemented. Treat trainer, energy and
   supplemental-source gaps as a separate recall lane.
2. **Identity layer:** add release and scoped-number tables/fields, structured
   finish/stamp/edition, artwork and gameplay concepts, and source alias
   mappings without changing existing card IDs.
3. **Agent layer:** turn the table of user questions into scenario tests with
   expected evidence and abstention. Make stored budget, destination and grade
   constraints affect actual candidate filtering and explanation.
4. **Market layer:** after an authorized feed arrives, version listing-to-card
   resolution, detect duplicate physical copies across listings, build fresh
   per-unit ask and paid-evidence series, and compare destination-specific
   landed costs. Do not infer a trend from the current zero-observation catalog.
5. **Basket layer:** collection planning, seller overlap, consolidated shipping
   quotes and permissioned fulfilment quality. Use observed outcomes before
   learning a merchant score.

The existing relational database and append-only relationship assertions can
support this sequence. A dedicated graph database should be considered only
after actual multi-hop query volume or latency demonstrates a need.

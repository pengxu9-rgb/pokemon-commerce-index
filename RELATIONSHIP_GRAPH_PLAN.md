# Relationship graph implementation plan

Prepared after an independent Astra review of the 19-anchor, 40-pair Japanese–English pilot on 24 September 2026. The sample is a challenge set for the workflow; all 40 decisions are still pending, so it measures neither matching precision nor retrieval recall.

## Decision

Build the graph around **exact printing identities** and typed, evidence-bearing links. Keep three concepts separate:

1. **Artwork/design** — whether two cards share the image and relevant card design.
2. **Regional release** — language, set, number, release or promo context.
3. **Physical printing** — finish, stamp, edition and other physical differences.

The current `card_id` remains the exact discovery target. A relationship never merges priceable units or carries a price from one printing to another. `same_artwork` and `localization_counterpart` can both be true, but each needs its own reviewed claim. `collecting_alternative` is an editorial suggestion that depends on buyer intent and does not become an equivalence relation. Character and illustrator facets are retrieval signals, not reviewed printing edges.

## Sequence and acceptance gates

| Stage | Build | Acceptance |
| --- | --- | --- |
| 0. Graph integrity — implemented in this change | Apply every explicit identity/facet constraint to direct, reviewed and alias retrieval. Bind reviews to source snapshots and explicit revisions; first positive review stays proposed, second agreement can verify. Generate rejection events on re-review. Validate verified evidence and pair-head freshness at the shared import boundary. Deduplicate reverse candidates. | Conflicting `dex_id` or illustrator returns no counterpart; verify → reject → verify works with three distinct revisions; changing counterpart to artwork withdraws the earlier pilot claim; stale compiled imports fail; retries are idempotent; incomplete direct verified imports fail. All 40 real pilot rows remain pending. |
| 1. Human pilot | Two independent people inspect both card images and physical printing details, fill the private review sheet, and resolve disagreements. Keep negative, identity-gap and uncertain labels. | Report decisions by type and failure mode, 18-anchor coverage after review, and unresolved count. Do not present sample agreement as catalog-wide precision. No buyer-facing edge without two agreeing reviews and display rights. |
| 2. Retrieval coverage | Keep this ambiguity set, then select an **independent** anchor set with reused art in another set or promo, regional finish differences, stamped promos, reprints, multi-character cards, trainers, energy, absent facets and correct counterparts omitted by retrieval. Record all truncated candidate IDs. | Pair precision uses reviewed pairs; retrieval recall uses independently established anchor answers, with pair-level and design-level results separately. Neither metric uses the same candidates as both proposals and ground truth. |
| 3. Identity quality | Add structured finish, stamp, edition and release-context fields and a `match_disabled_reason`; distinguish a known printing from unsupported offer-matcher syntax such as English TG numbering. Keep old IDs stable until source-backed migration tests exist. | A TG card can be a reviewed graph node while `match_eligible=false`; its reason is explicit, and graph import cannot change match eligibility. No automatic price matching is unlocked by a relationship review. |
| 4. Agentic discovery | Use exact reviewed edges, structural same-number variants, and separately labelled character/artist candidates to ask what artwork, language and finish the user wants. Save an exact `card_id` only after selection. | Scenario checks cover “same picture in English,” “same artist, different picture,” Master Ball finish, TG matcher restriction, rejection, changed artist constraint and paused exploration. Every graph answer exposes relation type, evidence, review state and display/matching restrictions; it makes no price or availability claim. |
| 5. Market activation | After an authorized Buy&Ship or other feed arrives, resolve offers to exact card and condition, then compute fresh ask and landed cost. Keep graph links out of price aggregation. | No cross-printing price merge; every offer and recommendation cites source, identity, condition and observation time. Paid-sale claims still require the separate Gate 1 and payment evidence. |

## Sample review findings

- Two Pikachu finish anchors contribute **18 of 40 pairs**. They are useful negative and finish tests but overweight one character/artist cluster.
- **Eight pairs** involve match-disabled English nodes: six Trainer Gallery cards and a Museum promo reached from two anchors. That flag concerns offer matching and must not be treated as proof the card identity is false.
- Charizard base/full-art/promo alternatives and the two-by-two Mega Manectric possibilities are good ambiguity cases. Their labels must remain open until card-specific human review.
- The S6a supplemental identity has no character or artist facet and is a documented retrieval gap.
- The current single-character plus artist method cannot cover trainers, energy, multi-character cards, or counterparts lacking either facet. Equality of collector number, rarity or variant is weak across regional releases.

## Data and rights boundary

No card images or marketplace prices are added to this graph. The internal metadata links in the sheet point to pinned source files and are not artwork evidence. Reviewers supply approved card-specific references in a controlled working copy. The local compiler and importer validate evidence structure and reviewer separation, but cannot authenticate a person or establish image rights. Public display approval remains a separate gate. Buy&Ship feeds are still on hold.

# Astra concept triage for human review

Auditor: gpt-6-astra. Audit date: 2026-09-24. Status: AI recommendations requiring human review.

The separate [AI triage CSV](catalog/concept-review-v2-ai-triage.csv) contains **21 suggested approvals, 18 suggested rejections and 0 uncertain recommendations** across all 39 proposals. Each recommendation includes a rationale, both pinned source URLs, the original source snapshot digest and explicit AI-only status. Suggested approval means the evidence supports a name-concept correspondence; it does not assert human verification or a matching physical printing.

There is one suggested approval for each of 21 Japanese names. The remaining name, マグマ団のしたっぱ, has only the incompatible Phoebe proposal in this queue. This audit independently inspected the Japanese and English name, category, subtype, artist and effect text for every pair. All 65 distinct pinned TypeScript files matched their recorded SHA-256 hashes. Matching artist was supporting evidence only: the 18 rejected proposals show why that signal cannot establish translation.

## Exceptions requiring attention

- **Rapid Strike Style Mustard, `2efe5f5d8acd884f18d1`:** the pinned English TG27 effect is `$$$CARD.RULES.MISSING.TOKEN$$$`. Name, subtype and artist agree. The [official Battle Styles 132 page](https://www.pokemon.com/us/pokemon-tcg/pokemon-cards/series/swsh5/132) search extract confirms the last-card condition, Rapid Strike discard-to-Bench effect and draw five, consistent with Japanese. Direct opening returned an iframe-only page. This corroboration concerns a different printing and artist, so a human should inspect the TG27 card identity before recording approval. The name recommendation remains approve; the missing pinned effect remains a source defect.
- **Risky Ruins, `3e04f41206441d85ead2`:** Japanese extracted text omits the Darkness symbol in its exclusion clause. The [official card page](https://www.pokemon-card.com/card-search/details.php/card/47796/regu/XY) has the same text extraction problem. The [official Japanese FAQ](https://www.pokemon-card.com/rules/faq/search.php?sc_group_id=871) explicitly describes non-Darkness Basic Pokémon and confirms that placing them on the Bench triggers damage counters. This resolves the apparent mismatch with English for concept triage.
- **Medical Energy and Luminous Energy:** Japanese extracted text omits a Colorless symbol. Their names, Special Energy subtype and distinctive healing/fallback effects support approval. [Medical Energy official text](https://www.pokemon-card.com/card-search/details.php/card/44134/regu/all) and [Luminous Energy official text](https://www.pokemon-card.com/card-search/details.php/card/44837) retain the same extraction omission; they do not independently resolve the missing symbol. Medical Energy's official image fetch failed with a cache miss. No visual symbol verification is claimed. The Luminous official page is another printing, SV4a 190. Have the human check card images if complete effect equivalence is required.
- **Pokémon Breeder and Professor Sada's Vitality:** English makes play/draw conditions explicit that Japanese extracted wording leaves implicit. Their names and distinctive effects agree. Preserve these wording differences in the human rationale rather than claiming byte-for-byte rule equivalence.
- **Legacy Energy:** names and effect agree, including the once-per-game Prize reduction. Japanese metadata says rarity `None` and lacks an explicit ACE SPEC label; English says `ACE SPEC Rare`. Name approval should not imply verified deck-rule or printing attributes.
- **Missing artists:** several Energy files have no artist or an empty artist. Absence is not evidence of matching artwork. All other paired artists were inspected as recorded.

## Proposed disposition and next steps

Recommend rejecting all 18 rows marked `reject` in the AI CSV. Their names and effects describe different concepts. If a shortlist is presented to reviewers, these can be withdrawn from its positive suggestions after a human confirms the rationale, while retaining the immutable proposal IDs and rejection history. No suggested-approval row needs withdrawal solely because of the documented metadata gaps. Keep Mustard's source defect prominently visible.

The Phoebe proposal `d1f12988b2ceafab2a67` does not fill the Team Magma Grunt gap. A correct English candidate still needs card-specific evidence and a separately pinned proposal. This audit did not create that candidate.

The human should review the 39 recommendations, inspect the cited evidence and exceptions, then record their own decisions and attribution in [the human template](catalog/concept-review-v2-template.csv). All 39 template rows remain pending. This audit did not write reviewer fields, import aliases or create graph edges. Approved concepts can proceed through the existing review-bundle workflow after human review. Artwork, finish and printing relationships retain their separate review requirements.

These selected proposals cannot measure population recall or production accuracy. The 21/39 recommendation count describes only this curated queue.

## Verification

Verified 39 unique proposal IDs in queue order; exact preservation of Japanese/English names, source URLs and source snapshot digests in the AI CSV; 78 paired source reads covering 65 distinct files with matching SHA-256 hashes; matching source names, category and subtype; nonempty rationales and AI-only status on every row; and human-template decision counts of 39 pending.

Audited queue SHA-256: `fdc2b745cad316b30380b5b3fcd5a9ddc777374cdee0189c2c44ef482d06a52c`.

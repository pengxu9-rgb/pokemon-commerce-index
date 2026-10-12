# Collector usefulness follow-through — 4 October 2026

## Why a green build was not the end

Commit `ec7104e0dc849aef519de647a53217c01958e3aa` passed [CI 37173068035](https://github.com/pengxu9-rgb/pokemon-commerce-index/actions/runs/37173068035): 793 Python passes and two skips, 19 Node passes, 42 original HTTP prefixes, 39 legacy prefixes, 34 pilot diagnostics, 21 source-gap checks, 24 evaluation-harness tests, actual-HTTP runtime checks and Docker build/container smoke. All 30 frozen collector scenarios executed without execution errors or unsupported authority, but only 26 met their mechanical constraints.

Two agent reviewers then assessed the actual responses, separately from mechanical checks. Their historical judgments were 13–14 completed tasks and 17–21 useful-progress cases out of 30. They agree on completion in 29 cases; one judged the comparison's sparse explanation insufficient despite correct compare/focus/select mechanics. Other differences concern variant-heavy pages and the usefulness of partial budget/grade responses. Both score sets and disagreements are preserved rather than averaged.

These are judgments on an **exposed development cohort**, not blinded acceptance, a human collector study or recommendation accuracy. The second reviewer disclosed receiving aggregate peer results after forming judgments but before serializing them. Source consistency is also narrower than truth: 145 candidate occurrences and 250 facet claims matched stored evidence, but publisher images and physical copies were not independently reverified.

## Four concrete gaps addressed

The same source snapshot already contains enough records for these requests. No extra catalog ingestion was required.

1. **Japanese character names.** A lone `リザードン` was interpreted as both dex 5 and 6 because the shorter `リザード` occurred inside it. Character interpretation now considers maximal overlapping name occurrences, preserving separately stated names and conflicting evidence instead of globally dropping every shorter name. Correct species affiliation does not independently certify each source's spelling.
2. **Explicit exclusions.** The narrow, recognized `exclude Mew` instruction maps to the existing hard species-exclusion field. Unsupported negation, unknown/ambiguous names and contradictory same-turn intent remain held. A later explicit exclusion can replace a conflicting older soft preference; it must invalidate prior selection/comparison authority, not become a temporary warning that another action clears. Accepted aliases require current source qualification.
3. **Ownership continuation.** The recognized ownership-only phrase in “cards I don't already own” no longer becomes a negative-taste preference. Missing inventory remains a visible requirement. Once the user supplies inventory, the result excludes the submitted exact records and retains uncertainty/identity gates. It does not claim complete knowledge of everything the user owns.
4. **Set-browse diversity.** A five-card Japanese 151 page previously used five source-version slots for two coordinates. Stable coordinate round-robin now shows five coordinates before revisiting alternate versions. All 516 source-version IDs remain available exactly once through pagination; no versions or physical printings are merged. The same ordering is reapplied after ownership filtering. Exact-coordinate/variant inspection and identity holds remain intact.

The empty Pikachu/Yuka Morii intersection remains empty because the catalog provides no supported match. Its explanation now offers an explicit relaxation rather than claiming an unspecified “exact coordinate” failed. No match is invented to make a task pass.

The frozen question, rubric and binding-contract hashes are unchanged. These cases are now regression diagnostics; they cannot be reused as a fresh independent acceptance cohort.

## Local integration check

After the final source-currentness and overlap-dominance corrections, all 30 unchanged scenarios meet their mechanical checks on the verified full snapshot. The actual Python HTTP → Node replay executes all 49 prefixes: 47 accepted responses and two expected authority rejections, with exact response/session equivalence and no execution, safety, path or transport failures. Runtime, caller, fixtures, catalog and original report bytes remain unchanged during execution. Compressed raw receipts and hashes are under `sandbox/collector_journeys/independent-collector-eval-v1/local-postfix-verified-snapshot-v3/`.

This is local verified-snapshot validation, not fresh CI, a new manifest build or a rescored usefulness estimate. The historical two-reviewer scores above must not be relabelled as scores of this corrected implementation. Exact-commit full CI remains required.

## Evidence and remaining boundaries

The full read-only snapshot recovered from the private CI artifact has SHA-256 `d1118b9241e014b56455ff93228bb52d208a5856aac49eaa6489d6f7e045b4f9`. It contains 70,006 source records, not 70,006 verified physical SKUs. The supported 100-record pilot has 63 explicit character facets, 27 labelled derived affiliations, zero unresolved Pokemon membership and 10 non-Pokemon records. Physical approvals and live market tables remain zero.

Set-browse receipts are in `sandbox/collector_journeys/set-browse-diversity-v1/`. Historical response scores, source checks, disagreements and title-review items are under `sandbox/collector_journeys/independent-collector-eval-v1/reviews/ci-37173068035/`. Exact-commit CI receipts remain authoritative for final integrated engineering validation; local replay of a verified snapshot is not a fresh catalog build.

Three top-page Charizard records retain the upstream name `カリザード`: `ja:E1:071/128:normal_1st_edition`, `ja:E1:103/128:normal_1st_edition`, and `ja:E5:089/088:normal_1st_edition`. They have current dex-6 facets. This is a task-driven source-title review queue, not an asserted correction or new identity approval. Preserve original source evidence and inspect qualified primary evidence before changing it.

## Next executable discovery work

1. **Make comparisons informative.** In `card_comparison.py`, expose available source-declared rarity and exact current illustrator credits for each side, with provenance. For SV4A 327/190 versus 347/190, the stored distinctions include SSR/aky CG Works versus SAR/USGMEN. Do not turn these into artwork, grade, price or investment conclusions. Add response/caller tests and a collector-facing explanation.
2. **Explain held identities.** For ICU-30, expose the stored original-name/corrected-name and finish-review reasons from `card_identity_exception`, plus the specific next evidence needed. A generic exclusion/checklist prompt is not an adequate explanation of an identity hold.
3. **Ask the missing question.** Distinguish an era such as Scarlet & Violet from one release (ICU-12); for an invalid collector number, ask to correct that number instead of asking again for an already supplied language (ICU-15). Keep uncertain inventory prompts specific to the unresolved version (ICU-27).
4. **Acknowledge buyer constraints without inventing commerce.** Preserve and plainly surface supplied budget, grade and destination even when they cannot rank catalog records. '$50', EUR100/PSA10/DE, and £40/UK need consistent clarification. No affordable, in-stock, deliverable or graded-copy claim is possible from catalog-only evidence.
5. **Prioritize evidence from actual displayed cards.** Review the three source-title anomalies and other first-page identity/copy blockers before increasing the supported pilot. Consider source-support-aware presentation, with inspectable research records clearly distinguished; support status is not physical verification.
6. **Build and test the private caller experience.** Add authenticated task persistence, readable candidate explanations, explicit refinement/feedback controls, comparison then separate selection, and restart/reconfirmation on revision change. Test mobile/desktop behavior and observe actual collectors. API diagnostics do not validate a deployed UI or human usefulness.

## Operations and Buy&Ship separation

The verified ec7104e real-catalog HTTP page/note-update workloads took about 2.17 seconds, with about 61 MiB peak process memory. The 16-client burst completed one request and rejected 15 as busy; that is controlled overload, not production capacity. Cold start, sustained completion rate, caller recovery, private IAM, immutable image provenance and actual Cloud Run load remain required before traffic promotion. The existing user-session deployment handoff and `PRIVATE_STAGING_ROLLOUT.md` still apply.

Fresh listing/search rights, exact offered-copy evidence, offer freshness, destination-specific landed costs, merchant reliability and confirmed Buy&Ship handoff remain separate commerce work. A known-URL quotation capability does not replace the missing listing feed. Live ingestion, public display, automatic offer joins, purchasing and payment remain disabled.

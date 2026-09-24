# Independent review and revised next steps — 24 September 2026

Astra reviewed the repository, schema, matching and discovery code, deployment notes, and tests. This document records the review findings and the build sequence while Buy&Ship's API feed is on hold.

## What exists

- 55,165 internal Japanese and English card identities. These are not 55,165 confirmed market SKUs: 21,208 identities are disabled for automatic matching, and none is approved for public display.
- Separate card, priceable unit, listing observation, verified sale and landed quote models. The local index contains no real marketplace offers or paid sales.
- An internal relationship ledger and exploration sessions. Structural same-set/number variant neighbors work; there are zero curated JP↔EN printing links. Sessions are local only. Cloud Run serves a private, read-only catalog snapshot.
- Source rights switches, a conservative listing matcher, a review workbench, a Buy&Ship gateway response adapter and Gate 0 probes. The existing 68 old-demo labels are AI-assisted drafts, not a blind human accuracy measurement.

## Findings and response

| Finding | Why it matters | Response |
| --- | --- | --- |
| Relationship verify → reject → verify could silently leave the edge rejected | A hash of claim content was treated as an event ID, so a legitimate later reversal collided with the old verification | Each new transition now appends an event; a retry of the current claim is idempotent. Callers may supply a stable `assertion_id` for retry-safe imports. Submitter and reviewer are stored separately. |
| Paused sessions still reported offer-tracking readiness and ordinary edits resumed them | An agent could act on a target the user had paused | A paused session stays paused until explicitly resumed; readiness requires `status=targeted`. |
| A change from Japanese to English could leave a Japanese target selected | Search constraints and tracked card could contradict each other | Language, set, collector number and variant must match the selected target. Conflicting updates fail and preserve the prior revision; callers clear or replace the target explicitly. |
| The clarification list asked for missing fields regardless of actual candidates | It could ask for a set number when the user's shortlist already narrows the choice | `exploration-decision` uses candidate count and differing facets to return one next question. It identifies no match, multiple printings, one candidate needing confirmation, an unverified target, a selected target and a paused session. |

`ready_for_offer_tracking` means **the selected printing is structurally eligible for a future listing search**. It does not mean a marketplace is connected, an exact grade or condition has been chosen, or a purchase is recommended. Budget, grade and destination remain saved preferences until an authorized offer feed exists.

## Revised sequence

1. **Now — offline discovery integrity.** Keep the above invariants covered by tests and run a small set of representative exploration questions through the decision contract. Do not expose local session writes to users.
2. **Next — useful catalog facets.** Extract provenance-bearing character IDs, multilingual aliases and artist metadata from the pinned source. Measure whether they improve candidate recall while keeping “same character” separate from “same printing.” Expand only against real questions and recorded catalog gaps.
3. **Next — curated relationship quality.** Propose candidate JP↔EN printing links for selected cards, then verify exact artwork, set, number and finish with independent evidence and human review. A shared name, Pokédex ID or set-level mapping is insufficient to mark a printing counterpart verified.
4. **Before session launch — durable state.** Move exploration sessions to recoverable storage with authenticated owner isolation, deletion and retention, revision access and restart tests. The current Cloud Run image is a read-only SQLite snapshot and cannot retain user state across deployments.
5. **When Buy&Ship is ready — commerce pilot.** Confirm gateway contracts, quotas and permitted data uses; run Gate 0 probes and an authorized 50-card offer pilot. Build the ask index and landed-cost comparison from fresh observations. Run the sweep-fidelity Gate 1 before any clear-price or sell-through claim. Grade/condition-aware merchant recommendations require listing evidence and fulfillment outcomes.

This sequence preserves Claude's separation of ask from verified paid prices and the Gate 1 decision. It brings guided discovery forward because users often need several questions before choosing a printing, while keeping market claims behind their evidence gates.

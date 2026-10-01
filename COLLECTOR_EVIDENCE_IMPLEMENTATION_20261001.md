# Source-bound artwork and printing context — 1 October 2026

This document records the first packet. The [100-target expansion and calibration](COLLECTOR_EVIDENCE_EXPANSION_20261001.md) is the current implementation; original results below are retained.

## Delivered

The catalog now has a separate collector-evidence ledger, with immutable events, identity fingerprints, explicit revision heads and withdrawal support. It contains **44 findings: nine official source declarations and 35 proposed AI visual findings**. The new [34-input deployment manifest](catalog-build-manifest-evidence-v1.json) pins this packet and asserts its counts.

The official findings comprise eight depicted-character facts on two Japanese 151 illustrations (two subjects and six cameos), plus one release-level Poké Ball mirror declaration. They are marked `source_supported`, meaning support from the inspected official description. This status does not mean independent physical-print verification. AI findings stay `proposed` and cannot be imported as source-supported findings.

Card identities remain 55,167, supported metadata targets remain 100, public display approvals remain zero, and verified card-pair relationships remain zero. This adds **card → depicted Pokémon** research and source declarations; it does not add verified Japanese/English counterpart or same-artwork pairs. Automatic live-offer approval remains zero.

## Collector behavior

- “Japanese Gengar cameos in card art” returns the source-bound Pikachu AR record `ja:SV2A:173/165:holo`, as a partial official-description result. The same illustration supports Growlithe, Jigglypuff and Butterfree queries.
- Kabuto and Omastar cameo queries return `ja:SV2A:180/165:holo`, the Omanyte AR illustration described on the official 151 page.
- “Japanese Mew cameos in card art,” including the diagnostic's Japanese wording, returns a clearly separated **AI review lead** for Pikachu `ja:SV-P:197/SV-P:normal`. It does not add that lead to confirmed result cards or a missing-inventory list.
- The inventory comparator can compare declared ownership with the six source-supported cameo scopes. Its output remains relative to a partial catalog scope, not a complete collection checklist.
- Cameo results and proposals honor the requested release, printed number, language, explicit catalog ID and source-declared finish. Evidence from one illustration cannot answer a request for a different printing. Final inspection added these scope guards before the final release.
- Exact card results carry relevant artwork findings and release-level printing context. The Poké Ball declaration explains that the treatment exists in the release; it cannot certify a particular card/copy, enumerate every eligible card, or establish all finishes.

Two Pikachu promos share the attack `げきとうスパーク`: `120/SV-P` visibly depicts Charizard, while `197/SV-P` visibly depicts Mew. The pipeline binds each observation to its own official card page, printed coordinates, image hash and catalog fingerprint. Shared attack text does not transfer an appearance or printing identity between them.

## Visual review and its limits

The [frozen image queue](catalog/collector-evidence-v1/visual-queue.jsonl) has 20 records: 18 Japanese 151 AR coordinates and the two Pikachu promos. Each official image was matched through the pinned Japanese source checkout and an exact live official name/set/number page. Vertex `gemini-3.8-flash` received the image and identity context. It read the printed name/number and listed visible Pokémon, excluding text mentions, symbols, logos and stamps.

The [Gemini checkpoint](catalog/collector-evidence-v1/gemini-visual-review.jsonl) retains 18 valid reviews and two failed reviews (`172/165`, `178/165`), which contribute no findings. There were no silent retries that rewrote those failures. The [compiler audit](catalog/collector-evidence-v1/build-audit.json) also retains two Pokémon explicitly named by official captions but not returned by Gemini: Jigglypuff on Pikachu 173 and Omastar on Omanyte 180. Model omission is not evidence of absence.

Codex inspected the two promo images before the Gemini result; [the two visual spot checks](catalog/collector-evidence-v1/codex-visual-spot-check.json) agree on the conspicuous Mew/Charizard cameos. This is a selected AI spot check, not random auditing, human labels or a precision measurement. All AI findings remain proposals. Source captions are themselves a narrow, non-exhaustive source slice.

Only factual findings, URLs, hashes and model decisions are committed. Image bytes are fetched for internal analysis and are not redistributed, served by the API or copied into the container.

## API and lifecycle

Private routes:

- `GET /collector-evidence-status`
- `GET /catalog-evidence?card_id=ja:SV2A:173/165:holo`
- Existing `GET /collector-discovery` and `POST /collector-inventory`

The new routes require the internal catalog flag and Cloud Run authentication. CLI equivalents are `collector-evidence-status` and `catalog-evidence CARD_ID`, both opening a read-only snapshot. `import-collector-evidence FILE` is an operator import used by the manifest builder, with no HTTP write route.

Evidence fingerprints bind a card's pinned name, coordinates, variant, rarity and provenance, or a release's name/date/provenance. Changed identities make prior findings stale and remove them from active discovery. Revisions must name the current event head. Replaying an old event cannot reactivate a withdrawn finding. A conflicting event ID, stale head, unknown card, unbound identity or fabricated physical-approval field rejects the import; a bad batch commits no partial writes.

Complete printing coverage, physical finish, condition, authenticity, grading, price comparability and pair-edge verification remain separate evidence claims. None is approved by this packet.

## Verification and reproduction

All **389 tests** pass. Twelve offline checks cover six official cameo scopes, AI-only abstention, inventory behavior, release/number/language/finish constraints, a shared-attack counterexample, immutable catalog bytes and the absence of verified pair edges. The [release rehearsal](catalog/collector-evidence-v1/release-scope-replay/rehearsal.json) records actual results; the earlier rehearsal remains intact.

The [enriched release replay](catalog/collector-evidence-v1/release-scope-replay/collector-source-replay.json) checks all 30 frozen source questions against their original returned card IDs and task types. All memberships remain unchanged; Mew gains a proposed review lead. This is a declared evidence enrichment of the same development cohort, not a new held-out score or catalog equivalence. The base six-table identity fingerprint is unchanged; the full fingerprint now includes the populated evidence ledger and is different. Historical equivalence locks cannot silently ignore this enrichment.

```bash
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-evidence-v1.json --db /tmp/collector-evidence-catalog.sqlite3
python3 -m pokemon_index --db /tmp/collector-evidence-catalog.sqlite3 catalog-evidence ja:SV2A:173/165:holo
python3 -m pokemon_index --db /tmp/collector-evidence-catalog.sqlite3 collector-discovery 'Japanese Gengar cameos in card art'
python3 -m unittest discover -s tests -q
```

Research scripts `review_collector_artwork`, `build_collector_evidence` and `rehearse_collector_evidence` preserve checkpoints and refuse to overwrite final evidence. Re-running model research can produce different proposals; the deployed snapshot is reproduced from the pinned evidence file, not fresh model calls.

## Next sequence

1. Expand source-backed depictions and release/variant declarations from these typed records, prioritizing collector requests and the supported modern slice. Independently audit visual proposals before any trusted depiction promotion; keep uncertain figures, omitted Pokémon and conflicting sources visible.
2. Add exact card-level finish/edition tables and permitted physical-copy evidence before solving version uncertainty or approving live joins. A generic release description is insufficient.
3. Connect the scoped evidence and inventory comparison to the controlled agent journey, with the provenance tier visible to the caller.
4. Attach an authorized real listing feed, fresh asks, condition evidence and Buy&Ship offer-bound quotes when access arrives. No live prices, fulfillment ranking or new purchase recommendation is established here.

Private staging revision `pokemon-commerce-index-00018-hsw` serves all traffic. [Final cloud verification](cloud-deployment-20261001-evidence-v2.json) passed 72 authenticated logical requests, including the 30 source cases, eight inventory cases, six official cameo queries and explicit scope guards. Unauthenticated requests remain 403. The earlier revision's results are preserved in [CLOUD_RUN.md](CLOUD_RUN.md).

# International coverage — exact-anchor field evidence supplement

Four additional qualification evidence records now bind the existing SMH/DS/SC/LL anchors to literal field checks against their pinned PTCG metadata and already cached publisher pages. The new records make illustrator, Pokédex-number and rarity-identifier checks explicit, with full source hashes and unresolved conflicts. All four product-release and physical-printing bindings remain held. No new publisher product document, card identity, release date, alias, relationship or permission is admitted.

## Evidence added

| Exact existing anchor | Matching illustrator credit | Matching Pokédex number | Literal rarity identifier / interpretation |
|---|---|---:|---|
| `ja:SMH:001/131:unverified` / publisher35030 | DemizuPosuka | 127 | Neither source reports a rarity identifier; unknown |
| `ja:DS:001/020:unverified` / publisher27836 | Masakazu Fukuda | 147 | Neither source reports a rarity identifier; unknown |
| `ja:SC:001/020:unverified` / publisher28616 | Eske Yoshinob | 495 | `rare_c_c` matches the icon identifier; existing parser mapping C |
| `ja:LL:001/040:unverified` / publisher26001 | Hideaki Hakozaki | 48 | `rare_c` matches literally; icon meaning remains unqualified |

The four records contain 22 literal matches: names, coordinates, illustrator credits, Pokédex numbers and product captions for each anchor, plus two rarity identifiers. Names, coordinates and captions repeat previously checked facts for context; the supplement adds explicit checks for four credits, four character numbers and two literal rarity identifiers. This does not increase catalogue coverage or create ten new physical facts. LL's legacy `ic_rare_c.gif` is outside the current recognized icon mapping, so its normalized rarity remains null and `rarity_icon_semantics_unqualified` is recorded. Rarity identifiers never prove foil, stamp, edition, condition, grading or price comparability.

`catalog/international-anchor-field-evidence-v1/evidence.jsonl` records exact card/candidate IDs, prior qualification and caption evidence IDs, provider/native ID, pinned revision and Git blob, SHA-256, licence hash/reference, publisher receipt/hash/retrieval time, inspection time, comparison values/statuses, confidence and unresolved conflicts. The original stage5 evidence remains immutable. The new inspection is `2026-10-11T13:18:32Z` (21:18:32 Asia/Shanghai). Historical PTCG retrieval time remains explicitly unknown.

PTCG anchor bytes and LICENSE match revision `bc5a2698eb9af858feb0280d579fd5fd0f0273e2` and the existing reviewed MIT licence. Publisher HTML matches the four existing receipt-bound hashes and historical retrieval times. Only bounded factual fields and the licence notice are packaged. Raw HTML, raw card JSON, artwork, image URLs, purchase links and marketplace prices are excluded from the supplement artifact.

PTCG metadata derives from the publisher. Their concordance is dependent-source evidence, not an independent physical or semantic review. Confidence 1.0 applies to checked bytes and literal comparison only; independent semantic accuracy, product-release binding and physical variant remain null. Every display, image-display, automatic-offer, purchase, physical-printing and price-comparison claim is false. Matching artists, Pokédex numbers, product names or collector numbers cannot establish SKU equivalence.

## Before and after

| Measure | Stage5 | With supplement |
|---|---:|---:|
| Supplement evidence records / subjects | 0 / 0 | 4 / 4 |
| Explicit supplement credit / Pokédex / rarity-identifier matches | 0 / 0 / 0 | 4 / 4 / 2 |
| Qualified publisher product / cross-provider anchor bindings | 0 / 0 | 0 / 0 |
| Internal source records: English / Japanese | 42,911 / 27,095 | 42,911 / 27,095 |
| Language/set/number groups / distinct internal identity tuples | 45,438 / 70,006 | 45,438 / 70,006 |
| Source-declared variants / unresolved coordinate families | 49,916 / 20,090 | 49,916 / 20,090 |
| Independently verified physical-printing total | Unknown | Unknown |
| Structural match eligibility | 33,543 | 33,543 |
| Display / image-display / automatic-offer / purchase approvals | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Packaged image files / inspected image subjects and hashes | 0 / 1,141 and 1,141 | 0 / 1,141 and 1,141 |
| Offers / observations / paid sales | 0 / 0 / 0 | 0 / 0 / 0 |
| Localized bindings / publisher-caption events | 60 / 4 | 60 / 4 |
| Japanese records missing release names / dates | 7,745 / 8,114 | 7,745 / 8,114 |
| Held candidates / quarantine entries / snapshot inputs | 65 / 65 / 68 | 65 / 65 / 68 |

The October2 count remains 70,006 source-version/family records, with no difference from the committed audit. It is not a verified physical-card count. The database is unchanged at SHA-256 `43efee62091ce157ea7d14182262c5c3a68f2e5e86058dbc5287da29b6cc1b82`. All original 65 ordered hash-bound inputs, stage 3's 68-step manifest, IDs and references are preserved. Dockerfile still explicitly selects `catalog-build-manifest-source-binding-v1.json`; the older snapshot-builder default is not used. The supplement is operator evidence outside the manifest, with no runtime importer, table or response-contract addition.

Missing images or offers remain distinct from missing identities; whole-catalogue image availability remains unmeasured. Pocket/digital-only cards stay excluded. The synthetic French fixture stays test-only. Korean header names do not admit Korean printings; real language expansion still requires demand, authorized Buy&Ship supply and complete reviewed sources. Stock, raw condition, grades, sold/asking prices and destination landed cost remain separate. Buy&Ship remains the intended MoR; Pivota does not hold customer funds. No creator frontend edits, cloud permissions, live ingestion, purchases, payments, push or deployment occur.

## Reproduction, validation and rollback

`scripts.build_anchor_qualification_fields` validates and reproduces the immutable stage5 artifacts from the current explicit68-step snapshot, then checks the four fixed PTCG Git blobs and licence. It parses only the already cached pages and compares literal fields at their exact held coordinates. Multiple coordinates, mismatched names/native IDs, foreign sources, missing denominators and variant siblings cannot inherit qualified fields. Missing values remain unreported; disagreements remain explicit held conflicts. Duplicate or unsupported source fields abstain. Git checks require full pinned revisions, disable lazy fetching and override origin with `/dev/null`; there is no network fallback.

The final prior-stage revalidation is followed by another check of every supplement input signature, covering late changes to pinned source bytes, licences and prior artifacts. The three compiled files — evidence, licence and coverage report — reproduce byte-identically. Both recorded output hashes match. The full final Python suite runs 724 cases: 722 pass and two existing skips, in 38.426 seconds. All 39 focused cases (17 new, 22 stage5) pass independently. Compilation and staged/unstaged whitespace checks pass. Stage 3's 15 Node passes carry forward; no new Node/runtime code is introduced. GPT-6.1 Sol high independent review confirms the input-change fix and evidence scope with no remaining actionable code findings; final review and test records accompany the artifact.

```sh
python3 -m scripts.build_anchor_qualification_fields --db /tmp/pokemon-stage3.sqlite3 --cache <existing-authorized-cache> --tcgdex-repo <existing-pinned-tcgdex-checkout> --ptcg-repo <existing-pinned-ptcg-checkout> --output-dir /tmp/pokemon-anchor-fields --inspected-at <actual-inspection-time>
python3 -m unittest tests.test_anchor_qualification_fields tests.test_product_document_qualification -v
python3 -m unittest discover -s tests
```

Use a fresh output directory. Reproduce the frozen artifact with `--inspected-at 2026-10-11T13:18:32Z` and identical authorized bytes. The compiler refuses overwrite. Requalification with identical inputs yields identical evidence IDs; existing import idempotence and unchanged-ID regressions also pass in the full suite.

Rollback this supplement by preserving stage5 artifacts/database and reversing only the stage6 incremental patch in the isolated checkout. There is no database migration, manifest change or cloud rollback. The cumulative patch includes earlier stages; the incremental patch applies to the exact stage5 tree `af01aced22f7f88189597f92dff0cbefe93e10fb`. Preserve prior evidence and other sessions' files.

## Remaining evidence batch

The exact SMH news target and DS/SC/LL publisher-product documents or explicit card-to-product bridges remain absent from the authorized sources. They need language/region and initial-release/copy-date scope. These field checks cannot substitute for that evidence or for physical finish, stamp/edition and distribution-region proof. LL's legacy rarity semantics need an authoritative interpretation before any normalized metadata admission. The four-anchor batch remains bounded; no broad import or deployment is justified.

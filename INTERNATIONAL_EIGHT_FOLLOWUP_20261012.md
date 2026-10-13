# Next-eight offline coverage — 2026-10-12

PR #1 is merged after a fresh GPT-6.1 Sol high adversarial review passed and both exact-head CI checks succeeded. Merge commit `8ed085116651e10a353e81ec967726471558e860` preserves both parents and the reviewed tree `65580e1e0d915bd6fd4998ac5f1adda03a95b772`. Post-merge CI run38259770770 also succeeded. No deployment or cloud permission change occurred. This separate eight-name batch remains local on `codex/international-eight-followup-20261012`, based on the unchanged Johto pilot commit `1fc2322af04c627210a604153ad9b0020b87c5f8`.

The batch closes16 measured translated-name retrieval gaps for existing records: eight Japanese and eight English bindings, tied to eight independently reviewed bare-name/singleton-Dex concepts. Source record count is unchanged. No new card identity, printing counterpart, artwork, marketplace price, offer, display approval or trading eligibility is added.

| Measure | Before | After |
| --- | ---: | ---: |
| Internal source-version/family records |70,006|70,006|
| English / Japanese source records |42,911 /27,095|42,911 /27,095|
| Language/set/number groups |45,438|45,438|
| Distinct internal identity tuples including unresolved labels |70,006|70,006|
| Source-declared normalized variant records |49,916|49,916|
| Unresolved family/label records and coordinate families |20,090|20,090|
| Structurally match-eligible records |33,534|33,534|
| Exact localized bindings / namespaced source mappings |2,396 /2,396|2,412 /2,412|
| Japanese / English localized bindings |2,071 /325|2,079 /333|
| Concept revisions / review events, all categories |310 /648|318 /656|
| Current approved Pokémon full-name concepts |188|196|
| Identity holds / quarantine ledger rows |44 /109|44 /109|
| Held release candidates |65|65|
| Source-image fact events / subjects |1,449 /1,141|1,449 /1,141|
| Current source-scan evidence subjects, including number-only evidence |1,171|1,171|
| Display / image-display / automatic offer / purchase approvals |0 /0 /0 /0|0 /0 /0 /0|
| Offer / observation / paid-sale / landed-quote / priceable-unit rows |0|0|

The October2 audit count is reproduced with no difference. Independently verified physical-printing count remains unknown. Whole-catalogue image-file availability remains unmeasured; this patch adds no images. The exact media partition stays1,171 current scan-evidence records,68,791 missing scan-evidence records and44 identity holds. Missing release metadata also stays unchanged:8,114 records across200 language/set scopes lack a date;7,745 across197 lack a name. A missing promo date is unknown and does not imply one date for the whole promo series. The prior hold migration reduced structural eligibility from33,543 to33,534; this batch changes no existing eligibility flag.

The eight residual Japanese name gaps from the prior pilot were qualified against existing authorized English witnesses. Six Japanese records are in SM12A and two in SM8B. Each Japanese selection is a complete current eligible coordinate group with one literal normal variant. English comparisons have explicit normal/holo declarations and are unbound existing records across SV03(two), SV02(three), SV05(two) and ME01(one).

| Dex | Exact full names | Japanese existing identity | English comparison identity |
| --- | --- | --- | --- |
| 173 | Cleffa / ピィ | `ja:SM12A:096/173:normal` | `en:SV03:080/197:normal` |
| 187 | Hoppip / ハネッコ | `ja:SM12A:004/173:normal` | `en:SV02:001/193:normal` |
| 188 | Skiploom / ポポッコ | `ja:SM12A:005/173:normal` | `en:SV02:002/193:normal` |
| 189 | Jumpluff / ワタッコ | `ja:SM12A:006/173:normal` | `en:SV02:003/193:holo` |
| 213 | Shuckle / ツボツボ | `ja:SM12A:007/173:normal` | `en:SV03:005/197:normal` |
| 218 | Slugma / マグマッグ | `ja:SM8B:010/150:normal` | `en:SV05:028/162:normal` |
| 219 | Magcargo / マグカルゴ | `ja:SM8B:011/150:normal` | `en:SV05:029/162:holo` |
| 236 | Tyrogue / バルキー | `ja:SM12A:068/173:normal` | `en:ME01:071/132:normal` |

Before import all16 native/Unicode catalogue target checks already succeeded, while all16 translated-name target checks missed. After import all16 translated/Unicode checks succeed and each structured translated resolver check returns its unique target. Opposite-language queries exclude that target. The actual localhost API and Node caller verified all16 exact localized queries, including `Cleffa ja SM12A 096/173` and `ハネッコ en SV02 001/193`. Concepts without per-record bindings abstain on all16; unselected English reverse variants do not inherit the new binding. These16 gains are search coverage for existing identities.

Evidence is limited to70 byte-checked entries from the existing TCGdex pin `a211f11f3ba57d56c65c5ac33be35b77d3280757`:50 card files,19 release headers and LICENSE. Fifteen paths reuse prior inventory;55 are newly checked existing cached paths. No source fetch or cache mutation occurred. Qualification packet SHA `54202d23c429681fc879a42d0fea57c4522a268f90583e9f9a0a9afb322e9583` and independent semantic approval SHA `3f94f90a8ea6680c80d78107261b99cfc70a0366829212aeef89b09ecc7c7a8d` are retained byte-exact. Historical retrieval time remains unknown/null. Qualification inspected_at is `2026-10-12T13:54:57.553309+00:00`; actual independently attested semantic-review completion is `2026-10-12T14:00:24Z`; compiler inspection is `2026-10-12T14:22:56Z`. These are separate events. The compiler rejects inspection predating semantic approval. Provider-native paths, Git blobs/SHA, licence hash, exact native names, singleton Dex, category, source rarity, all literal variant dimensions and localized release snapshots are rechecked before exclusive publication. Confidence covers those metadata checks and exact name translations. Physical distribution region remains unknown (`region=ZZ`); language and provider release IDs never infer a physical market.

Of64 eligible unbound English name candidates inspected,52 have strict pinned source witnesses;12 are held at witness qualification because their source lacks a nonempty literal variant declaration. Eight of52 were selected. Those12 receive no new binding and no existing eligibility flag is rewritten. They are separate from the preserved44 installed identity holds and109 quarantine ledger rows. The prior29 new SV4A release-conflict candidates remain held. Shared artwork, collector numbers, translated names and Dex do not certify equivalent printings, counterparts, variants, prices or SKUs. Forms, owner/regional/sex/mechanic prefixes and stamps are not inherited from a bare-name concept. Offers, stock, condition, grading company/grade, sold versus asking prices and destination-specific landed cost remain separate.

The manifest `catalog-build-manifest-international-pokemon-eight-followup-v1.json` has83 ordered hash-bound inputs, preserving the whole81-input Johto prefix and original65 source-binding inputs. Only the new concept-review bundle and locale file are appended; expected concept/review counts become318/656. Manifest SHA `133acada3465f9d864e3514dfea36382e24a33a94772ca9338fe207fbf8e7042`. Docker remains explicitly bound to `catalog-build-manifest-source-binding-v1.json`. Always pass the intended pilot manifest explicitly; the builder default selects an older manifest.

Before database SHA `085dc973724b474852af673305f387387c23400eb571a4dc028414a948e3e2d1`. Incremental SHA `4ea456e8163d7c8b0d562daacdf1f160ac28c469ede2fabac1da2fda578d0790`. Independent rebuild SHA `d99c592eaf1e56aca66a2ba7424c6a2438dd8938c3b36c0b4d38f5d0c762f827`. The incremental snapshot preserves every historical column and row across51 tables, including existing card IDs/references; only four tables gain exactly8 concepts,8 review events,16 locale rows and16 mappings. All51 logical rebuild tables match; only four explicitly named legacy generated timestamps are excluded from rebuild comparisons: card_identity_exception.applied_at(19), card_number_conflict_rule.applied_at(2), card_rarity_correction.applied_at(532) and card_relationship_assertion.asserted_at(657). Incremental history excludes no column. Exact SQL definitions of the hold index and two triggers, all44 held identities/flags/media contexts, integrity and foreign keys pass. Idempotent re-import adds zero rows, reports16 unchanged locales and zero quarantine, and preserves every table.

Validation:1,200 Python tests ran;1,198 passed and two existing tests skipped. All42 Node tests passed with temporary loopback sockets allowed; the initial restricted Node run failed four HTTP tests because the sandbox denied localhost sockets, and its log is retained. The46 focused tests include23 new compiler tests and five new audit guard/provenance tests. Existing suites cover third-language synthetic French, provider collisions, cross-language negatives, shared artwork, promos, foil/stamp differences, repeated collector numbers and quarantine. New negatives cover missing/nonliteral/unknown variant dimensions, source/release drift, ID/history preservation, wrong singleton Dex/category/name scope, concept collisions, forged rehashed semantic/provenance claims, time ordering, no inheritance to unselected variants and refusal to overwrite artifact destinations. Native and accelerated actual-snapshot journeys agree; stale expected revisions reject. All1,171 source evidence contexts and five historical priority responses remain unchanged. Local caller/filter/pagination checks pass; no image bytes are fetched. These are engineering checks with no new usefulness, aesthetic, blind-user accuracy or cloud/frontend acceptance claim. Independent final code/artifact/package review is recorded separately.

The five priority targets remain excluded at full coordinate groups: `en:BASE1:058/102:normal`, `ja:PMCG1:035/102:normal`, `ja:PMCG1:035/102:normal_no_rarity`, `ja:PMCG2:024/048:normal` and `ja:PMCG5:036/096:normal`. The English record stays jumbo-held with no standard-size replacement. None gains artwork, visual-review or display evidence.

Rollback uses the unchanged `johto.sqlite3`, or a new-file rebuild with the prior explicit81-input Johto manifest. To reproduce this batch, build a new file with `python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-international-pokemon-eight-followup-v1.json --db /path/to/new-eight.sqlite3`, then run the batch auditor against immutable before/incremental/rebuilt snapshots. Never overwrite the old database or reset another session's checkout. The delivered reverse patch is checked against the frozen new tree and restores exactly the prior Johto tree; shared CI repair and PR merge history stay intact.

The next bounded candidate scope is the44 remaining source-qualified English IDs in this same inventory, subject to a new exact selection, current-record recheck and separate binding audit. They are not imported by this delivery. The bounded inventory provides no further unbound Japanese group after these eight; the next Japan-first batch needs additional exact witnesses from existing authorized caches or qualification of the five image/rights targets. Set-level demand, Buy&Ship-confirmed authorized commercial supply and live stock remain unmeasured. No broader hundred-level Japanese intake is justified by this packet. Korean remains a conditional real-language evaluation after demand, authorized supply and reviewed source completeness are established; French remains synthetic test-only.

Pocket/digital-only cards remain excluded. Catalogue inclusion grants no artwork/display/purchase rights. Buy&Ship remains intended MoR; Pivota holds no customer funds. No creator frontend edits, deployment, cloud permissions/traffic/expiry changes, live ingestion, new marketplace/artwork import, scraping, subscriptions/API keys, purchases or payments occur.

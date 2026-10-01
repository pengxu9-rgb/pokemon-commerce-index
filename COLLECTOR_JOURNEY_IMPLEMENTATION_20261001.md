# Multi-turn collector journey — 1 October 2026

## Delivered

`POST /collector-journey` connects source-backed discovery, artwork context, inventory comparison, short follow-up replies and explicit catalog selection. It runs behind the internal API flag and Cloud Run authentication, using the same read-only catalog. It is a bounded orchestration primitive for a future Pivota agent; it is not a public chat interface or a deployed Pivota integration.

The caller keeps a transcript of at most 20 actions. Every request replays those actions against the current catalog; the service accepts no precomputed candidates, approvals or selected-state blob. It does not persist conversations, inventory or account records. HTTP bodies remain bounded at 262,144 bytes, inventory at 1,000 entries and candidate pages at 50 records.

Supported actions:

| Action | Purpose |
|---|---|
| `ask` | Set a raw collection question; reset prior scope/target while retaining submitted inventory and market preferences |
| `reply` | Interpret bounded language, release-code/name, collector-number, finish or confirmation replies; unclear prose prompts clarification |
| `refine` | Apply explicit language/set/number/source-variant choices; `null` removes an override and restores the original question's constraint |
| `inventory` | Replace the caller's asserted inventory; preserve unresolved entries and quantities |
| `resolve_owned` | Explicitly identify a version-uncertain item from its declared coordinate candidates; this remains a user assertion |
| `preferences` | Retain requested grade, budget in minor units/currency and destination without inventing matching offers |
| `page` | View another bounded candidate page |
| `select` / `clear_target` | Choose an immediately preceding displayed candidate or withdraw the selection |

Short replies work for Japanese/English, known printed release codes, exact localized release names, collector numbers and a small finish vocabulary. Other replies require clarification or a new `ask`. This does not claim unrestricted conversational understanding.

## Example

```json
{
  "turns": [
    {"type": "ask", "question": "Pikachu cards"},
    {"type": "reply", "text": "Japanese"},
    {"type": "reply", "text": "SV2A"},
    {"type": "reply", "text": "025/165"},
    {"type": "reply", "text": "Master Ball reverse"},
    {"type": "reply", "text": "Yes"},
    {"type": "preferences", "preferences": {"grade_company": "PSA", "grade_value": "10", "budget_minor": 100000, "currency": "JPY", "destination": "HK"}}
  ]
}
```

This selects catalog record `ja:SV2A:025/165:reverse_masterball`. PSA 10 is a requested copy attribute, not a grade of the catalog record. The output has no listing URL, unit ID, quote or purchase approval. Choosing a source-declared variant does not independently certify physical finish.

The response includes candidate cards and their evidence context, a separate AI-lead list, inventory review/missing-record context, selected catalog target, next step and a compact action trace. Unknown inventory blocks selection even if some other missing records are visible. A single catalog version does not resolve an inventory item's unspecified physical version automatically.

## Selection and resume boundaries

- AI artwork leads cannot be selected as confirmed scope cards or counted as inventory gaps. Official cameo scopes can select catalog records, with their partial coverage still explicit.
- Selection requires a candidate shown in the preceding page. Unseen, already-owned, unknown, evidence-blocked or unresolved-inventory selections are rejected.
- Changing goal, effective scope or inventory withdraws the previous selection. An unclear reply stays pending across unrelated preference/page updates, and suppresses the target intent until clarified.
- A release mentioned as an exclusion is not treated as an affirmative collection filter. Unsupported exclusion/checklist semantics block selection pending clarification.
- Explicit follow-up filters override prior language/number/finish wording, while preserving character, artist, family or cameo intent. Natural character/artist release filters now honor a single affirmative release; incidental omitted releases in an external checklist do not narrow that query.
- A portable `catalog_revision` binds relevant catalog/evidence tables and runtime code. The caller can pass `expected_revision` on resume; a changed deployment requires replay and target reconfirmation. Correction application timestamps are excluded: equivalent independently rebuilt snapshots share the revision, while changed correction evidence still invalidates it. This hash is a change detector, not account authorization or a signed proof of prior user consent. The server caches it for its immutable catalog image.

The selected target emits an internal `pokemon.collector-target-intent.v1` contract suitable for Pivota orchestration. It carries exact catalog coordinates/provenance and user preferences, but `priceable_unit_id`, `product_url` and `quote` are null. `transaction_ready`, `automatic_offer_join_allowed`, `physical_printing_verified`, public display, offer tracking and purchase readiness remain false. Existing Pivota public export permissions and legacy local exploration APIs are unchanged; no Pivota runtime/database write is performed.

## Verification and retained failures

The [authored suite](sandbox/collector_journeys/v1/journeys.json) contains **20 journeys and 59 prefix requests**: version narrowing, replacement language, official and proposed cameos, uncertain/unknown inventory, explicit resolution, duplicate quantities, target reset, grade/budget/destination preferences, family and artist scope, release-name replies and evidence blockers.

The initial replay passed **56/59**, with three downstream failures caused by the Japanese release-name reply. The first correction still failed those three steps; a language-map variable had shadowed the language-scope argument. The final correction, release replay and [portable release replay](sandbox/collector_journeys/v1/portable-release-report.json) pass **59/59**. All attempts remain saved, with matching runtime source snapshots. The pre-guard snapshot was reconstructed from the exact patch and checked against the recorded hashes; it is not presented as a pre-run archive.

**407 engineering tests pass.** They cover selection membership, inventory uncertainty, stale revisions, scope replacement, localized aliases, release exclusions, persistent ambiguity, market separation, forged fields, bounded inputs, private routes and unchanged database bytes. The [legacy replay](sandbox/collector_journeys/v1/legacy-replay/collector-source-replay.json) retains all 30 original returned-card memberships/tasks, plus the existing source/AI evidence boundaries.

The first cloud journey check failed with HTTP 400 because the revision bound build-specific correction timestamps. The [failure](sandbox/collector_journeys/v1/cloud-portability-failure.json) remains recorded. The [independent rebuild check](sandbox/collector_journeys/v1/portability-rehearsal.json) confirms that distinct SQLite files now share the same semantic revision.

These are development regressions and synthetic inventory assertions, not held-out user success, listing precision, human depiction accuracy or physical collection completeness. Catalog/evidence counts remain unchanged from the [35-input evidence manifest](catalog-build-manifest-evidence-v2.json).

CLI reproduction:

```bash
python3 -m pokemon_index --db /tmp/catalog.sqlite3 collector-journey request.json
python3 -m scripts.rehearse_collector_journeys --db /tmp/catalog.sqlite3 --suite sandbox/collector_journeys/v1/journeys.json --output /tmp/new-journey-report.json
```

Private staging evidence: [journey deployment verification](cloud-deployment-20261001-journey-v1.json), revision `pokemon-commerce-index-00022-gxz`: **156 authenticated logical requests passed**, including all 59 journey prefixes with full-response hash equivalence, two guard cases and five rejected invalid requests. Three unauthenticated route checks returned HTTP 403; no transport errors were recorded. Next: expose this controlled contract to a permitted Pivota caller and run independently selected collector journeys. Account-backed persistence, exact-copy validation, authorized listing feeds, fresh landed quotes and checkout lifecycle remain separate delivery gates.

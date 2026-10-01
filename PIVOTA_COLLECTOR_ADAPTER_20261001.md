# Pivota collector caller and fresh scenario diagnostic — 1 October 2026

## Delivered

The [CommonJS caller](integrations/pivota/collectorClient.cjs) connects a Node gateway to the private `POST /collector-journey` contract. A [proposed internal operation](integrations/pivota/collectorOperation.cjs) wraps it with a default-disabled pilot flag and caller authorization. The wrapper does not modify Pivota's live registry, assign commerce IDs, write its database or join checkout. Configuration, identity-token integration and invocation examples are in the [caller guide](integrations/pivota/README.md).

The available local Pivota gateway reference was inspected read-only at commit `1b5f698fedbda10aa339f649854b15d64fd33e3b`. Its public `docs/tool-schema.json` does not list `collector.explore` and its direct dependencies do not include `google-auth-library`. This historical checkout was not assumed to be the active integration/deployment target. The owning current repository, agent entry and caller service identity still need confirmation before registration and identity permission changes.

Caller behavior:

- Return the bounded action session unchanged for continuation, with its expected catalog revision and initial page limit. No state is stored by the catalog or connector.
- Catalog changes withdraw target output and require restart/reconfirmation. There is no silent replay of a stale selection without its revision.
- Use a configured server identity, reject redirects, bound JSON size/timeouts and retry at most once for specified transient failures. Caller inputs are snapshotted before asynchronous token acquisition; failures do not advance saved state.
- Reject unexpected commerce approvals, live prices, non-null URLs/quotes/unit IDs, coordinate mismatch and malformed responses. Errors contain fixed codes rather than upstream text or credentials.
- Keep catalog target intent separate from public display, physical copy, priceable-unit mapping, ACP/AP2 and transaction approval.

The adapter is exercised through real local HTTP and the private staging service. Those operator-driven calls are not proof that Pivota's deployed service identity can invoke it.

## New source-led diagnostic

Eight new source posts were opened and condensed into [collection questions](sandbox/collector_journeys/v2/sources.json). The [original suite](sandbox/collector_journeys/v2/suite.json) froze 37 steps before the first execution; [collection lock](sandbox/collector_journeys/v2/collection-lock.json) records the source/suite/runtime hashes and base commit. Follow-ups and inventory assertions are authored scenarios, not genuine source transcripts.

Examples and provenance:

| Situation | Public source | What the caller must preserve |
|---|---|---|
| Artist checklist may omit reprints/promos | [Komiya checklist discussion](https://www.reddit.com/r/PokemonTCG/comments/1p5i9a3/tomokazu_komiya_checklist_spreadsheet/) | The referenced checklist is missing; catalog partials cannot establish its omissions |
| Every language requested | [Yuka Morii grandmaster request, post 14](https://www.elitefourum.com/t/yuka-morii-english-set-collection/60708/14) | Day-one Japanese/English coverage cannot silently satisfy global scope |
| Unknown old/new Japanese cards | [Identification question](https://www.reddit.com/r/PokemonTCG/comments/1uyja3u/japanese_card_identification/) | Ask for useful coordinates rather than inventing a card |
| Different regional number/rarity | [Sawsbuck 074/071 question](https://community.pokemon.com/en-us/discussion/22137/sawsbuck-074-071-ar) | Base identity and cross-language equivalence need different evidence |
| Non-card sleeves/playmats | [Komiya accessories request](https://www.reddit.com/r/PokemonTCG/comments/1ulhwoe/help_finding_souce_list_of_items_made_by_tomokazu/) | Do not replace merchandise intent with artist-card retrieval |
| Last four cards cannot be found for sale | [Psyduck availability question](https://www.reddit.com/r/PokemonTCG/comments/1qt6h3p/help_finding_4_cards_to_complete_my_psyduck/) | Coordinate refinement cannot fabricate current purchase channels |
| Vintage Japanese artist promos | [Komiya collection replies](https://www.reddit.com/r/PokemonTCG/comments/16prks6/tomokazu_komiya_artwork_pokemon_cards_full_set_of/) | Return a catalog partial and preserve unknown inventory/version scope |
| Completed one collection; what next? | [Next-collection question](https://www.reddit.com/r/PokemonTCG/comments/1riu33b/complete_set_276276_of_tomokazu_komiya_artworks/) | Ask about the next goal instead of searching the completed collection again |

Comments and community claims supply question situations only. They do not verify finishes, counterparts, completeness, prices or availability. Forum media and external spreadsheets were not collected. The source selection and expectations were written by the implementer with knowledge of the existing system: **this is a fresh diagnostic, not an independent held-out user-success measurement**.

## Findings and repairs

The [initial replay](sandbox/collector_journeys/v2/initial-report.json) was **26/37**; 36 steps executed because an invalid authored inventory action stopped that journey. It found:

1. “Every language” did not trigger the existing all-language constraint. It now does, and an explicit Japanese/English follow-up deliberately narrows that constraint without claiming completeness.
2. A sleeves/playmats request was treated as an illustrator-card list. Non-card product intent now takes precedence, including a clear exclusion of Pokémon cards.
3. “What should I collect next?” returned the artist's existing cards. It now asks for next-collection preferences.
4. A natural purchase-location request with several numbers entered release clarification instead of the unavailable market lane. It now preserves the purchase task and feed blocker after refinements.
5. A natural English-version question did not identify the relationship task. It now requests exact base identity and verified card-level relationship evidence; adding coordinates cannot turn it into a base-card purchase choice. Plural “English versions of [Japanese ID]” remains a language-constrained catalog request.

The [corrected runtime replay](sandbox/collector_journeys/v2/corrected-runtime-report.json) passed **33/37 against the original frozen suite**. The remaining four failed steps were authored fixture errors, explicitly recorded in [fixture review](sandbox/collector_journeys/v2/fixture-review.json):

- A free-title inventory entry is unsupported by the coordinate/ID API and correctly returned 400, leaving the following step unexecuted. The revised fixture supplies an explicitly unknown synthetic catalog ID.
- The expectations assumed Sawsbuck 074/071 had a normal/non-holo record and a following “Yes” would select it. The catalog only provides a source-declared holo record. The revised fixture expects refusal/clarification for normal and adds two explicit holo/confirmation recovery steps; physical finish remains unverified.

The [reviewed suite](sandbox/collector_journeys/v2/reviewed-suite.json) has **39 steps**, all passing in the [release replay](sandbox/collector_journeys/v2/release-report.json) through the Node caller and real HTTP. Each complete response equals direct local execution and the caller preserves the transcript/revision. Revised expectations and recovery steps are post-exposure development checks; the source questions and original failures remain unchanged.

## Verification and readiness

- **412 Python engineering tests pass**, including new goal-boundary regressions; **11 Node caller/operation tests pass**.
- The original [20 journeys / 59 prefixes](sandbox/collector_journeys/v2/legacy-journey-report.json) still pass; the [30 source-question replay](sandbox/collector_journeys/v2/legacy-replay/collector-source-replay.json) retains all prior card memberships/tasks and the existing official-description versus AI-proposal boundaries.
- The catalog/evidence data is unchanged. Counts remain 55,167 internal identities, 33,543 structurally eligible and zero automatic-live-join/display approvals or market observations. No new card/relationship assertions were added this turn.
- Private staging revision `pokemon-commerce-index-00023-n84` serves all traffic. [Deployment verification](cloud-deployment-20261001-pivota-caller-v1.json) passed 156 authenticated logical requests and three unauthenticated 403 checks, with no transport errors or public invoker binding. The [Node caller cloud replay](sandbox/collector_journeys/v2/cloud-caller-report.json) passed all 39 additional steps; full caller responses match the local release replay. Together these are 195 authenticated logical calls, not a real-user accuracy score or a Pivota service-identity proof. The catalog remains a read-only snapshot; no conversation, inventory or market persistence is introduced.

Next integration work: register the internal operation in the confirmed active Pivota repository, attach its server identity to the private service, and exercise an authenticated agent entry before claiming Pivota integration. An independently selected/labelled multi-turn outcome evaluation remains open. Real authorized offers, copy/condition evidence, fresh landed quotes and confirmed Buy&Ship checkout remain separate gates.

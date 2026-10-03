# Pivota collector caller

Dependency-free CommonJS connector for the private Pokémon catalog API. Native `fetch` is required; the rehearsal runs on Node 24. This folder is an integration deliverable, not registration in Pivota's active gateway or a public card surface.

## Invoke contract

```js
const {createCollectorClient} = require('./collectorClient.cjs');
const {createCollectorOperation} = require('./collectorOperation.cjs');

const client = createCollectorClient({
  baseUrl: process.env.POKEMON_COLLECTOR_SERVICE_URL,
  getIdToken: acquireServerIdentityToken, // server-owned function, not user input
});
const collectorExplore = createCollectorOperation({
  enabled: process.env.POKEMON_COLLECTOR_INTERNAL_PILOT === 'true',
  client,
  authorize: context => permittedInternalCollectorCaller(context),
});

const call = await collectorExplore(authenticatedGatewayContext, {
  operation: 'collector.explore',
  payload: {action: {type: 'ask', question: 'Japanese Pikachu cards'}, limit: 20},
});
const next = await collectorExplore(authenticatedGatewayContext, {
  operation: 'collector.explore',
  payload: {session: call.session, action: {type: 'reply', text: 'SV2A'}},
});
```

The gateway owns authentication, pilot permissions and any user-scoped session storage. `authenticatedGatewayContext`, the identity-token provider and the permission function must be application dependencies. They cannot be copied from the request body. No existing Pivota `operation` enum has been modified. `collector.explore` is a proposed internal registration, absent from the referenced Pivota public schema.

### Google Cloud identity provider

For a GCP service caller, add a direct `google-auth-library` dependency in its owning repository, then inject:

```js
const {GoogleAuth} = require('google-auth-library');
const auth = new GoogleAuth();
async function acquireServerIdentityToken(audience) {
  const tokenClient = await auth.getIdTokenClient(audience);
  return tokenClient.idTokenProvider.fetchIdToken(audience);
}
```

The audience is the configured service origin, without `/collector-journey`. The actual caller service identity needs Cloud Run Invoker on the receiving service. This follows Google's [service-to-service authentication](https://docs.cloud.google.com/run/docs/authenticating/service-to-service) and [ID-token acquisition](https://docs.cloud.google.com/docs/authentication/get-id-token) documentation. No service-account key file or token is bundled; no invoker principal was added by this work. The rehearsal uses an already-authorized operator token in subprocess memory and does **not** establish access from Pivota's deployed service identity.

## Session and target rules

Two-card comparison questions now return a scoped partial under `result.discovery.comparison`. Number namespaces and exact reviewed source-image links are separate from physical printing and market evidence. Comparison results contain no candidate purchase targets, prices, offer URLs or target intents; nested commerce approvals are rejected by the caller. Missing releases remain unconfirmed. See [comparison implementation](../../TWO_CARD_COMPARISON_20261002.md). This uses the existing proposed `collector.explore` operation and does not register another active Pivota operation.

- `session` contains the bounded action transcript, its initial page limit and the expected catalog revision. Pass the returned session unchanged on the next call; do not put it into `acp_state` or `ap2_state`.
- At most 20 actions; no silent transcript trimming. Begin a new explicitly scoped journey if that bound is reached. Session storage/tenant ownership/retention belong to the caller and are not provided here.
- A catalog revision change returns `status=catalog_changed`, with no session, result or target intent. Restart the question and reconfirm the target; the connector does not remove the revision and replay an old selection automatically.
- Timeout or service errors leave the input session unchanged. Retry policy is at most two calls for transport/timeouts or HTTP 429/502/503/504. Ordinary 400, authentication denial, 500 and invalid response bodies are not retried. Default timeout is ten seconds per attempt.
- HTTPS service URL is trusted startup configuration. Redirects are rejected, token/header values never enter results or error text, response JSON is bounded to 8 MiB by default. Loopback HTTP requires explicit test mode.
- Results remain `internal_catalog_only`. Catalog target coordinates and provenance do not assign Pivota `content_key`, identify a graded/physical copy, approve offer joins or enter checkout.
- Unknown inventory, unsupported exclusions, unavailable source-declared finishes and uncertain artwork remain unresolved. Grade/budget/destination are user preferences, not inventory, price or condition facts.

## Collector recommendation loop (local implementation)

The existing private route and proposed `collector.explore` operation now support:

```js
{type: 'preferences', preferences: {collecting: {
  mode: 'discover_next', preferred_dex_ids: [151],
  preferred_illustrators: [], preferred_releases: [], excluded_dex_ids: [],
  subjective_notes: ['quiet scenes'],
}, budget_minor: 5000, currency: 'USD'}}
{type: 'feedback', card_id: 'an-exact-shown-id', reaction: 'like'} // like | dismiss | clear
{type: 'compare', left_card_id: 'shown-left-id', right_card_id: 'shown-right-id'}
{type: 'choose_comparison', side: 'right', card_id: 'exact-right-member-id'}
{type: 'select', card_id: 'exact-focused-id'} // a separate confirmation
```

- Default page size is five; explicit limits of 1–50 remain supported. `refine.scope` language/release/number/variant filters remain hard; collecting preferences are matching signals. Supplied preference arrays replace, empty arrays clear, null removes; unknown fields, duplicate values and preferred/excluded species conflicts are rejected.
- A next-collection question asks for a character, illustrator or release. Language alone is not a positive taste signal. Supported exact replies progress into recommendations without concatenating arbitrary text into the original question. Unrecognized taste text is retained as an unapplied assertion and asks one focused question.
- `result.recommendation` is null outside recommendations. Otherwise its items correspond exactly to the candidate page, with absolute ranks and actual facet/coordinate provenance. Ranking counts explicit matching axes, then axes shared with liked examples; equal-score coordinate groups alternate in stable ID order. Source versions are never merged. A complete candidate pool means only the bounded current catalog query, never catalog or physical-printing completeness.
- Feedback accepts only recommendation IDs shown in the current context, including its visited pages. Dismiss excludes exactly one ID. Latest feedback wins; repeated actions do not compound a score. Feedback changes reset the page and withdraw a selected target. Changing collecting preferences, goal, scope or inventory invalidates old comparison/feedback page membership. A new goal preserves explicit preferences/inventory and starts fresh feedback.
- Comparisons remain evidence-only: no candidates, target, selection, offers or price claims. Explicit `choose_comparison` exits into a freshly hydrated, exact-ID focus. A subsequent `select` still checks identity holds, source-number conflicts, coordinate families, numbered parts, source-only families and unresolved/owned inventory. `result.card_selection_blockers` records blockers per visible ID; a blocked ID cannot be selected even if other page entries are selectable.
- Budget, grade and aesthetic fit remain unknown without qualified sources/offers. Subjective notes such as cute/quiet are unapplied, not inferred labels. No price/rarity/newness/popularity boost is used. Pure cheapest/buy/profit questions retain the existing market blocker.
- The new runtime is included in `catalog_revision`; existing deployed sessions will need restart/reconfirmation when an updated runtime is deployed. This change is locally verified; it does not update the private cloud deployment or register a live Pivota operation.

Reproduce the frozen synthetic loop through actual HTTP and the Node caller:

```bash
python3 -m scripts.rehearse_collector_recommendations --output /tmp/new-recommendation-report.json
```

See [implementation and evidence](../../COLLECTOR_RECOMMENDATION_IMPLEMENTATION_20261003.md). The fixture is an engineering acceptance suite; it does not measure real-user recommendation usefulness.

## Errors

| Result/error | Caller behavior |
|---|---|
| `accepted` | Retain returned session and explain `result` / `next_step` internally |
| `catalog_changed` | Withdraw the current target and restart/reconfirm |
| `collector_operation_disabled` / `collector_caller_denied` | Do not expose catalog results |
| `catalog_access_denied` / `catalog_auth_unavailable` | Check the configured server identity, without asking for user credentials |
| `catalog_rejected_action` | Correct the bounded action; do not infer success |
| `journey_turn_limit` | Start a new explicit collection scope |
| `catalog_timeout` / `catalog_temporarily_unavailable` / `catalog_transport_error` | Explain the temporary failure; input state was not advanced |
| `invalid_catalog_response` / `response_too_large` | Suppress result/target and diagnose the contract |

All live product URLs, quotes and priceable unit IDs remain null, and commerce/public-display approval flags remain false. A selected catalog target is not a purchasable Pivota product.

## Reproduce

```bash
node --test integrations/pivota/collectorClient.test.cjs integrations/pivota/collectorOperation.test.cjs
python3 -m scripts.rehearse_pivota_collector --db /tmp/catalog.sqlite3 \
  --suite sandbox/collector_journeys/v2/reviewed-suite.json --output /tmp/new-caller-report.json
# With an authorized operator and the matching deployed snapshot:
python3 -m scripts.rehearse_pivota_collector --db /tmp/catalog.sqlite3 \
  --suite sandbox/collector_journeys/v2/reviewed-suite.json --cloud --output /tmp/new-cloud-caller-report.json
```

Detailed implementation evidence: [Pivota caller diagnostic](../../PIVOTA_COLLECTOR_ADAPTER_20261001.md).

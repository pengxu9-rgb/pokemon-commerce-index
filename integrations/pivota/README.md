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

- `session` contains the bounded action transcript, its initial page limit and the expected catalog revision. Pass the returned session unchanged on the next call; do not put it into `acp_state` or `ap2_state`.
- At most 20 actions; no silent transcript trimming. Begin a new explicitly scoped journey if that bound is reached. Session storage/tenant ownership/retention belong to the caller and are not provided here.
- A catalog revision change returns `status=catalog_changed`, with no session, result or target intent. Restart the question and reconfirm the target; the connector does not remove the revision and replay an old selection automatically.
- Timeout or service errors leave the input session unchanged. Retry policy is at most two calls for transport/timeouts or HTTP 429/502/503/504. Ordinary 400, authentication denial, 500 and invalid response bodies are not retried. Default timeout is ten seconds per attempt.
- HTTPS service URL is trusted startup configuration. Redirects are rejected, token/header values never enter results or error text, response JSON is bounded to 8 MiB by default. Loopback HTTP requires explicit test mode.
- Results remain `internal_catalog_only`. Catalog target coordinates and provenance do not assign Pivota `content_key`, identify a graded/physical copy, approve offer joins or enter checkout.
- Unknown inventory, unsupported exclusions, unavailable source-declared finishes and uncertain artwork remain unresolved. Grade/budget/destination are user preferences, not inventory, price or condition facts.

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

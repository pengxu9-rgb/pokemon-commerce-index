# Collector chat, live research and private staging

The additive commerce sidecar serves research, explicit listing selection,
fresh URL handoff and optional BNS quote previews from the collector chat.
`POST /commerce/psa` adds the separate PSA database-record lookup documented in
[PSA_CERT_LOOKUP.md](PSA_CERT_LOOKUP.md). Neither a seller grade nor a matching
PSA database record authenticates a physical card or slab.

The frontend starts research after an explicit catalog card choice. Offers show
native asking prices, observation time, seller grade and source failures.
Selections expire and the server rechecks the retained exact URL before handoff.
No order, payment, purchase-request or checkout operation is exposed. Chat
commerce state is transient; a refresh/restart requires fresh research.

## Private deployment boundary

Use the existing `pokemon-creator-ui-test` Cloud Run service in
`pivota-staging/us-west1`, a new zero-normal-traffic tag, its existing runtime
identity, and a fresh private GCS test namespace lasting at most 24 hours.
Preserve all prior tags and resolved root traffic. Keep IAM invocation checks
enabled and verify anonymous requests return 401/403. The frontend identity's
existing temporary catalog-invoker and dedicated test-bucket object-user grants
must cover the same new test window. Renew only those existing identity/resource
relationships with a bounded expiry; retain their other bindings.

The frontend image includes an exact manifested backend source archive and a
locked Playwright/browser runtime. Its private process supervisor generates an
ephemeral per-instance bearer token and starts Python on `127.0.0.1:8766`.
The browser cannot select the sidecar host, supply the owner identity, or read
the token. Only the exact private test scope permits the managed loopback
configuration. Marketplace renderer subprocesses receive a small environment
allowlist excluding provider and sidecar credentials. Browser sandboxing remains
enabled; an unsupported browser runtime is an explicit unavailable source.

The existing catalog image, snapshot, traffic and release pins are not rebuilt
or changed for this deployment. Frontend/backend source commits, per-file build
context hashes, Cloud Build ID and resolved image digest belong in the rollout
receipt. Code changes remain reviewable separately from the staging deployment.

## Provider access and bounded follow-up

See [the current first-live audit and bounded test runbook](FIRST_LIVE_PROVIDER_TESTS.md)
before enabling either provider. In particular, BNS chat still needs the bounded
transport integration described there; credentials and a database alone are not
sufficient to enable that path.

At the user's instruction, BNS and PSA access are not ready. Deploy with
`POKEMON_COMMERCE_BNS_ENABLED=false` and
`POKEMON_COMMERCE_PSA_ENABLED=false`. Missing provider access must be visible,
and must never produce a synthetic quote or a verification badge.

Once configured, enable PSA only with server-owned `PSA_API_TOKEN`; use one
known certificate for the read-only provider smoke, with invalid/mismatch cases
covered offline. Enable BNS only with its approved test endpoint/client secrets
and `POKEMON_COMMERCE_QUOTE_DB` pointing to an existing eligible approved operator
database. The BNS adapter requires a current exact indexed listing/price/grade
binding in addition to credentials; crawled candidates cannot grant themselves
that approval. Use one supported available listing and one country/state
destination for resolve/quote; never submit an order or purchase request.

A source asking price or copied product URL is not a BNS landed quote. eBay
robots/access restrictions and unknown stock remain visible even when provider
credentials are later enabled. Do not retry challenges or bypass source policy.

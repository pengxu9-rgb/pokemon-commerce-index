# Bounded Buy & Ship quotes in agent chat

This document describes the preserved indexed-offer path. A separately opted-in
selected-URL preview and detailed refusal/variant contract are described in
[BNS_URL_PREVIEW.md](BNS_URL_PREVIEW.md). Both paths remain disabled by default.

The authenticated sidecar's existing `--allow-live-buyship` configuration now
installs `BoundedBuyShipForwarder`. The flag stays off by default. This change
does not enable BNS, change credentials, mount a database or deploy a revision.
The browser keeps the same research → select → handoff API and quote DTO.

Each eligible handoff runs the existing indexed-offer gate in a fresh Python
subprocess. It creates a new `PartnerClient` and `OneShotBNSSender`, so tokens,
request counters and provider state cannot cross users or handoffs. One active
BNS worker is allowed per sidecar; a competing request falls back to manual URL
handoff without starting another worker.

The shared sender permits exactly the ordered OAuth → product resolve → quote
routes at the configured HTTPS origin. It validates public DNS, pins the TLS
connection, refuses redirects and rejects non-200 responses without auth
refresh or automatic retry. At most three HTTP requests are possible, with one
item of quantity one and no street address. Each response is limited to 64 KiB;
each request gets at most five seconds within an 18-second sender budget.
The operator smoke harness uses the same transport and retains its own limits.

Chat starts an absolute monotonic 22-second deadline before refreshing the
selected marketplace URL, leaving margin for the existing 25-second proxy and
browser budgets. The BNS worker gets at most 18 seconds and only the remaining
handoff time. Its sender also checks that absolute deadline before dispatch.
If refresh consumes the budget, no BNS worker starts. Timeout kills and reaps
the subprocess, including DNS, slow body reads and SQLite waits, before the
worker slot is released. Provider failures are never retried automatically.

The marketplace refresh itself still uses the crawler's existing limits and
can exceed the browser timeout. This change bounds BNS work and prevents a late
provider call after a slow refresh; it does not claim to make every crawl finish
within 22 seconds.

The child preserves the existing fresh-connection DB checks and also guards
every HTTP dispatch, including resolve after OAuth. Current source permission, exact indexed card/unit/listing,
native price, stock and seller grade/condition/certificate evidence are still
required. Crawled candidates cannot grant themselves approval. No observations,
quotes, source permissions, orders or payments are written.

The parent checks the bounded JSON result, evidence digest, selected card and
listing, exact URL and asking price, destination, five reconciled cost lines,
expiry and explicit false purchase/authentication flags. Worker errors and
stderr are discarded; users get the existing generic manual-handoff fallback.
It then opens a fresh read-only connection to match the indexed snapshot and
seller-quality hash again after IPC. This check uses a short SQLite busy wait,
a progress-handler deadline and a final deadline check.
Credentials travel only in server process environment, never argv or browser
payloads. Provider cost components remain separate from the source asking price.

The frozen adapter labels custom senders `injected_test_transport`, including
this strict sender. That legacy mode is preserved. The worker adds a seller
quality hash to the evidence and recomputes its binding digest;
it is not proof that a live result came from a fixture. No live execution has
been performed as part of this change.

Offline regressions cover fresh clients for repeated handoffs, owner/stock
gates, changed DB evidence, all-stage access/redirect/rate-limit failures, worker
timeout/cleanup, concurrency, exhausted refresh budgets, malformed or tampered
worker results and the service's disabled/default configuration. Release-pinned
sources and the frozen BNS adapter remain unchanged. Actual token, provider
contract, URL support and private browser behavior still need the later bounded
tests in [the first-live runbook](FIRST_LIVE_PROVIDER_TESTS.md).

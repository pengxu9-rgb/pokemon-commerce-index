# First live BNS quote and PSA certificate test

Audit baseline: main `917c70a4d11287da3021d4d3b52014d3cc2fe369` and the
private staging receipt from 21 October 2026. This audit and its preparation
perform no external calls or deployments. Saved cloud configuration is evidence
from that deployment, not a fresh claim about current secrets or service health.

## Remaining requirements

| Path | Still required | Why it matters |
| --- | --- | --- |
| PSA | Server-only `PSA_API_TOKEN`, runtime access to its secret, and an explicit PSA enable flag | The adapter is implemented but staging was deployed disabled. Token validity and provider response compatibility have not been tested live. |
| PSA case | One operator-supplied known certificate, with expected subject, PSA card-number field, year, brand and grade; variety optional | The existing chat comparison checks the stored seller grade. A first provider smoke must also check the expected card identity. Do not guess PSA fields from a verbose seller title or enumerate certificate numbers. |
| BNS access | Confirmed test origin, client credentials, detailed schema/rate limits and supported marketplace URL/variant contract | The current adapter implements the supplied partner overview. Real endpoint behavior remains unverified. There is no API-free BNS browser quote collector in this flow. |
| BNS evidence | A readable existing operator database with the approved source policy and an exact current card/priceable-unit/listing observation | Credentials cannot make an unindexed crawled candidate eligible. No source policies, observations or identity approvals are created by this probe. |
| BNS listing | One fresh, available/on-sale individual listing; exact URL, native ID, price/currency, grade, condition and certificate claim bound to the operator DB | All sampled staging candidates had unknown stock. Current stock and exact indexed evidence must be established before any provider call. |
| BNS variant | A provider-supported single-variant listing, quantity one, destination HK | The chat adapter does not expose explicit variant selection. Multiple returned variants fail before a quote request. US additionally needs a state. No street address is accepted. |
| Staging data | A deliberate read-only delivery/mount of the operator DB at `POKEMON_COMMERCE_QUOTE_DB` | The deployed image excludes databases and operator state, and its saved rollout added no quote DB mount. Neither known release database is suitable. |
| Staging access | Valid private test scope, session and temporary catalog/storage access | The saved window expires **22 October 2026, 15:15:41 KST**. If access arrives later, a new private configuration window is needed. |

The two task databases inspected read-only, `work/quote-scale.sqlite3` and
`work/quote-next3000.sqlite3`, each contain 70,006 catalog cards and zero source
policies, priceable units, listings, observations and landed quotes. This does
not establish that another operator database does not exist elsewhere.

The frozen BNS transport follows redirects, can refresh/retry after 401, and
uses a 20-second timeout per request. The normal token/resolve/quote sequence
uses three HTTP requests; 401 refresh at both endpoints can raise this to seven.
That transport is unsuitable for a first strictly bounded probe and may exceed
the frontend's 25-second handoff budget. The operator harness and current chat
service now share a separate one-shot sender. Chat uses a fresh disposable
worker per handoff, capped at 18 seconds and the remaining 22-second absolute
handoff deadline. See [bounded chat integration](BOUNDED_BNS_CHAT.md).
**This source change does not update or enable the deployed private revision.**
The saved deployment still uses the earlier service. A later reviewed private
revision and full browser validation are required before enabling it there.

## Prepared commands

Copy `examples/provider_smoke_plan.json` into an operator-only workspace and
replace the null fields with actual reviewed inputs. Keep all credentials in
server environment/secret configuration. Never put secrets in this JSON, command
arguments, screenshots or result files. The BNS offer is the server-held research
object, including `source`, `native_id`, `url`, `title`, native `price_minor`,
`currency`, `availability`, `listing_status`, `observed_at`, `fresh_until`,
`grade`, `seller_condition` and `certificate_number_claim` where present. It
must also retain `authenticity_verified:false` and
`grade.certificate_verified:false`.

Default execution is strictly offline, even if credentials exist:

```sh
python3 -m pokemon_index.provider_smoke \
  --plan /operator/one-case.json \
  --output /operator/new-readiness-report.json
```

The report lists missing configuration names and eligibility checks. It reads an
existing operator DB only; it does not crawl, ingest data, grant source rights,
store quotes, renew access or modify deployment configuration. A ready preflight
is an input-readiness check, not proof of provider connectivity or URL support.

After access is configured and live execution is authorized, run one provider
at a time. These commands were **prepared, not executed** during this audit:

```sh
python3 -m pokemon_index.provider_smoke --plan /operator/one-case.json \
  --execute psa --output /operator/new-psa-report.json

python3 -m pokemon_index.provider_smoke --plan /operator/one-case.json \
  --execute bns --output /operator/new-bns-report.json
```

PSA uses one new client with at most one GET and no retry, an eight-second
per-request timeout and a 64 KiB response limit. It validates the exact known
certificate and all expected identity fields, then repeats comparison and checks
a deliberately different grade **locally against the same returned record**.
Actual cache reuse, invalid/not-found/unauthorized/expiry cases stay in offline
tests; there is no second lookup or certificate enumeration.

BNS permits only one OAuth POST, one product-resolve POST and one quantity-one
quote POST to the explicitly approved HTTPS origin. It checks public DNS and
pins the connection, keeps TLS hostname verification enabled, follows no
redirects, retries no 401/429/error, and limits each response to 64 KiB. Requests
are capped at five seconds each and an 18-second sender deadline. The parent
process kills the one-provider worker at 25 seconds, covering DNS, slow headers,
body reads and DB waits; local preflight occurs before that worker deadline.
Failure may leave a completed non-purchase provider request, so do not retry
automatically. No order/payment endpoint exists.

Result files are reserved before optional execution. Reusing an existing result
path fails before a provider request; choose a new receipt only for a deliberately
authorized new attempt.

Both probes return redacted summaries. PSA outputs a certificate hash and
comparison field names. BNS outputs binding hashes, cost components, total and
expiry, with a hashed quote ID. Neither outputs credentials, raw provider
responses, photos, seller records or an address. The existing frozen quote
evidence labels custom senders as injected transport; the probe's own transport
label distinguishes its bounded HTTPS sender from offline injected fixtures.

## Acceptance and browser follow-up

PSA passes only for a fresh `found` record with the exact requested certificate,
all supplied identity fields matched, and all certificate/physical-authenticity
flags still false. A matching record does not prove the slab or listing is
authentic.

BNS passes only for the existing approved indexed binding before and after the
sequence, one available variant, an `OPEN` unexpired quote, matching URL,
reference/variant/quantity/destination, and five cost lines reconciling with the
total. Source asking price and provider price remain separate. Quote storage
stays empty; `purchasable=false`, `order_created=false`, and
`purchase_action=null` remain mandatory.

The direct operator probe does not prove browser usability. For a later private
browser check, bootstrap a fresh valid session, retain the same cookie through
research → select → handoff and contextual PSA, and use the authenticated Cloud
Run proxy. The existing client needs exact Origin, JSON content type and
`X-Collector-Intent: decision`. The server derives the owner and generates the
loopback sidecar token; operators must not supply browser owner IDs or configure
that token manually. Refreshing/restarting discards transient offers/selections.

Keep mismatch, stale-transaction/open-cursor, changed price/stock/grade, owner
swap, timeout, redirect, unauthorized, rate-limit, bad totals and expired quote
cases offline. On failure, stop without widening budgets, promoting unknown
stock, changing release pins, repeating live requests or creating an order.

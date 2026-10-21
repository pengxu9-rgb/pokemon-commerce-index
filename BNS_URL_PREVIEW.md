# Selected-URL Buy & Ship quote previews

A newly researched listing is transient public-page evidence, not an approved
catalog offer. The existing indexed provider requires a matching operator DB,
source policy and current unit observation. That path is unchanged.

The new `URLBuyShipForwarder` is a separate, explicitly configured preview path.
It requires an owner-bound selection and a fresh check of its retained exact
marketplace URL. It lets BNS resolve unknown stock and native price, without
writing or approving catalog/listing/source records. The quote remains a
non-purchasable preview: card identity, seller grade and certificates are
unverified. Product summaries, sold-out listings, synthetic URLs and explicit
collector-number/grade contradictions cannot produce a preview.

## Configuration stays disabled

Nothing in this PR enables BNS/PSA, configures credentials or deploys anything.
The standalone service accepts the future explicit combination
`--allow-live-buyship --buyship-url-preview` with server-owned
`BNS_PARTNER_BASE_URL`, `BNS_PARTNER_CLIENT_ID`, `BNS_PARTNER_CLIENT_SECRET`.
URL preview and `--quote-db` are mutually exclusive. The existing
`--allow-live-buyship --quote-db <operator DB>` retains the frozen indexed gate.
A fixture cannot be combined with either live path. No database is opened by
URL preview.

The frontend companion adds `POKEMON_COMMERCE_BNS_URL_PREVIEW=true`, valid only
with the existing explicit BNS enable flag, credentials and no quote DB.
Its default is false. Existing private staging flags are not changed.

## Selection, variants and quote binding

The browser still uses research → select → handoff. It never sends a product
URL, provider reference, expected provider price or grade to handoff.
Each attempt refreshes the retained marketplace URL and checks the selected
source fingerprint; drift requires new research/selection before provider I/O.
The BNS worker gets only the retained offer/context, destination, optional
server-retained variant expectation and remaining deadline.

A single in-stock resolved variant can quote immediately. Multiple variants
return `variant_selection_required` and bounded choices, without calling quote.
The browser may send only `variant_key` on a later handoff. It must match the
same owner's latest choices and destination, within five minutes and the
selection's expiry. The server does not accept a browser-supplied reference,
options or price. A fresh BNS resolve must reproduce the retained key, options,
native price and stock before quote. Otherwise `variant_changed` returns new
choices and requires explicit selection again. No automatic retry occurs.

Only HK and US/state destinations and one item/quantity one are accepted.
BNS quote fields must bind the exact URL, reference, selected variant/options,
destination and currency; status must be OPEN and expiry current. All five
cost components must reconcile to grand_total using integer minor units.
The native source ask remains separate from BNS resolve and account-currency
quote prices. A comparable changed resolve price is explicitly flagged in UI.
Merchant display names never join catalog identity or merchant domains.

URL previews use evidence mode `url_quote_preview`, an explicit unverified
binding scope and hashes of selected offer/resolve/quote. They have no indexed
unit ID. False purchase, order, certificate and authenticity flags are checked
again across the worker boundary. A URL quote does not authenticate a physical
card or establish catalog matching eligibility.

## Bounded refusals and process lifetime

`provider_result`, when present, uses the closed `pokemon.bns-refusal.v1` DTO.
Only enumerated documented codes/reasons, fixed messages and validated bounded
variant/currency/field hints reach chat. OAuth's distinct error shape is handled
separately. Provider-authored messages, unknown details, headers and raw errors
are discarded. A retryable hint enables no automatic retry. Escaped credentials
and tokens are checked in decoded values and keys, not JSON-escaped text.

The HTTPS sender still allows only three ordered POST routes: OAuth token,
product resolve and quote. No redirect, auth refresh, GET/order/payment or retry
is added. Each request is at most five seconds within the existing eighteen-
second worker budget, and responses are at most64KiB. One active BNS worker is
shared across both URL and indexed modes. The parent caps the worker to the
remaining22-second handoff deadline; timeout kills and reaps the subprocess.
Tokens/credentials never cross into the browser or process arguments.

The parent independently validates quote/refusal shape, selection, money,
false verification/purchase flags and deadlines. Unknown or malformed provider
responses produce a safe unavailable result. The frozen indexed adapter keeps
its previous behavior. No source/quote storage, orders or payments are added.

## Offline verification and frontend companion

`tests/test_bns_url_preview.py` uses an injected wire sender and blocks external
socket/DNS I/O. It covers a new unknown-stock offer without a DB, explicit
variant choice, owner/destination binding, changed options/price/stock,
unsupported products/currencies/destinations, redacted refusal fields, source
changes, quote expiry/totals, hostile IPC, escaped secrets and timeout cleanup.
Existing indexed provider tests continue to run unchanged. The fast offline
CI job includes the new preview and refusal suites.

The frontend repository has no remote. Its reviewable source patch is included
at `integrations/creator/bns-url-preview.patch`, based on frontend commit
`0129b89df522c51735d4669c87a98210f4fc684c`, producing
`79fc06783b226e839ff5534567d8a748dfafaeaf`. Apply it to that clean frontend
base; it adds strict DTO validation, refusal and variant controls, expiry and
price-difference labels, tests and the disabled future sidecar configuration.
It has been tested locally and is not deployed by this PR.

After applying the frontend patch, run its Node tests/TypeScript/build. The
cross-language fixture check can also be run from this backend checkout:

```
node integrations/creator/check-bns-preview-contract.cjs /path/to/frontend
```

`examples/bns_url_preview_contracts.json` contains injected offline handoff and
refusal fixtures, not live provider evidence. Real access, account currency,
merchant support, latency and a supported product still need the separately
authorized bounded provider test. Release pins, all38 protected files and the
frozen `buyship_partner.py` are unchanged.

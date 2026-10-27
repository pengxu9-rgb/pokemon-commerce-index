# Marketplace referral implementation — offline handoff

Date: 2026-10-26. Accounts: not applied / not configured. No live requests run.

The application drafts and outstanding business details are in
[marketplace-partners-20261026.md](marketplace-partners-20261026.md).

## Implemented

- `ebay_official.py`: server-only official Browse token/search/item reads, separate production-use and display authorization gates, optional separately approved EPN campaign, no automatic retries. At most 20 HTTP attempts including the token, within an explicit window of at most 90 minutes. TLS completion is followed by a fresh check before HTTP credentials are dispatched.
- The producer plugs into the existing research/select/handoff loop. Canonical product URLs stay separate from same-item validated affiliate URLs. USD fixed-price asks are not completed sales or delivered quotes. Unsupported auctions, variation summaries, conflicting evidence and ended listings do not become current offers.
- Frontend: labelled eBay sections, affiliate disclosure, canonical handoff binding, unverified seller grade/cert labels, and truthful eBay/Fanatics connection states. eBay aggregate ask statistics and cross-platform pin comparisons remain suppressed.
- Both full and beta runtime copy lists include the new validator. A packaging test validates a Python-produced offline research DTO using only the explicitly copied runtime helpers.
- Fanatics has no working data adapter or fabricated offers. Its next step is a Collect-specific approved partnership/feed, using the prepared introduction.

## Configuration seam and remaining work

The Python sidecar CLI supports explicit `--allow-live-ebay-browse`, `--ebay-read-until` and `--ebay-request-budget`. Merely supplying credentials or enabling public crawling does not enable official Browse.

Server configuration names are `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_PRODUCTION_APPROVED`, `EBAY_DISPLAY_APPROVED`; optional EPN names are `EBAY_EPN_CAMPAIGN_ID`, `EBAY_EPN_APPROVED`, `EBAY_EPN_REFERENCE_ID`. Approval booleans require the literal `true`. They record operator-confirmed authorization for the proposed use; they do not assert that Browse universally requires a separate restricted-API approval. See the application packet's official-document discrepancy.

**2026-10-27 update:** the isolated frontend now wires explicit, default-off managed settings `POKEMON_COMMERCE_EBAY_BROWSE_ENABLED`, `POKEMON_COMMERCE_EBAY_READ_UNTIL` and `POKEMON_COMMERCE_EBAY_REQUEST_BUDGET` to these CLI flags. The initial managed pilot requires crawling, fixtures, BNS and PSA explicitly off, a valid private scope, production/display authorization, an expiry within that scope and a finite request budget. EPN remains optional. Marketplace credentials/configuration are removed from the Next child environment and remain with the Python producer.

Managed chat stores eBay-derived summaries and hashes in GCS. It is **not memory-only** and cannot use a no-data-persistence declaration as its retention authorization. `EBAY_PERSISTENT_DATA_APPROVED=true` is a separate operator gate requiring actual retention/deletion-notification compliance review; it does not implement or verify the platform's deletion subscription by itself. The first standalone five-offer pilot bypasses chat storage and retains its report in process memory only. See [ebay-first-live-price-pilot.md](ebay-first-live-price-pilot.md).

None of these settings have been activated. No cloud environment variables, secrets, grants, images or services were changed for this feature.

Live acceptance remains outstanding: production keyset access, EPN attribution and eligible regions, real item availability/price/URL agreement, refresh/cache rights, and permitted agent/comparison/history use. Fanatics access also remains outstanding. The implementation supplies no live-access authorization. BNS/PSA, orders and payments remain off.

## Historical local validation

- Backend: 104 tests passed across official eBay, commerce loop/service/PSA/catalog and connection-state suites. The runner blocked external sockets; loopback fixture HTTP only.
- Frontend: 89 tests passed across affiliate validation, shopper/classic rendering, zero-offer status, seller/grade/listing evidence, canonical BNS binding and runtime packaging. External networking blocked by the test preload.
- TypeScript `--noEmit --incremental false` and both Git whitespace checks passed.
- Independent adversarial review passed after resolving a missing `purchaseLink.cjs` runtime-copy blocker. No remaining confirmed code blockers; live and managed activation are untested.
- All 38 protected backend files match the existing release baseline, including unchanged scale and next-3000 pins; the frozen BNS transport is unchanged.

Those local feature branches started at backend `f99fc02263a9fad93e588fd006e412f95475279c` and frontend `577aa53b36411b9936916f0693ae685d7667618b`. Their local validation counts above do not certify the separately prepared public-main port.

## Clean public-main port — 2026-10-27

The backend candidate starts at public main `fa0d07306fe4674db221fa862b0d8fe45f959a0f`. It includes the seller, grade-negation and listing-identity evidence dependencies required by the current research DTO, plus the existing BNS preview's compatibility with that DTO. It excludes sandbox orders, PSA diagnostics and private catalog artifact deployment code. The service's new catalog input is an explicit operator-owned read-only database; it does not change the packaged catalog or release pins.

The clean candidate passed 252 targeted offline tests (one environment-dependent test skipped). Public CI and the matching frontend port must pass before private staging. The earlier local worktree's browser screenshots use injected sessions and synthetic offers; they do not certify the public-main source pair or live access.

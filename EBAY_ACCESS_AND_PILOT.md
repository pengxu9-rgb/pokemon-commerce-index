# eBay Browse access and first ask-price pilot

## What eBay offers

The [Browse API](https://developer.ebay.com/api-docs/buy/api-browse.html) provides current listing search (`item_summary/search`) and item details (`item/{item_id}`). Search can return title, item ID, current price, seller and a main image; item details can add images and condition fields. Use an application access token from the [client credentials grant](https://developer.ebay.com/develop/guides/sell/authorization). The default [Browse API call limit](https://developer.ebay.com/develop/get-started/api-call-limits) is 5,000 calls per day for most methods, subject to the application's actual allowance.

**Production access is restricted.** eBay's [Buy API requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html) call for a reviewed business use case, partner approval and applicable agreements. A developer key and Sandbox test do not constitute approval to collect and publish production data. [Marketplace Insights](https://developer.ebay.com/api-docs/buy/ref-marketplace-supported.html), the sold-history API, is restricted and currently not open to new users. Browse prices are **current asks**, never verified paid prices. A missing result cannot be classified as sold.

The current [API License Agreement](https://developer.ebay.com/join/api-license-agreement) materially limits this product concept under standard terms: public eBay content must not be co-mingled with non-eBay content; displayed listing information must remain fresh within six hours; derivation of certain statistics needs express written permission; and eBay content must not be used to train or develop AI systems. It also restricts using eBay content with third-party information to suggest or model prices for eBay listings. **Inference:** our cross-platform price index, merchant comparison and Gemini listing-photo workflow require a separate, explicit written scope from eBay. Production Browse approval by itself is insufficient. Seek eBay's determination on inference-only photo classification as well as training; do not send eBay photos to Gemini under the default terms.

## Application information to prepare

- eBay member and Developers Program accounts; Sandbox and Production keysets.
- Product description: a Pokémon card discovery and purchase-assistance experience, with exact printing, condition and seller provenance shown alongside current offers.
- Markets and flow: start with `EBAY_US` fixed-price cards, link to the eBay item for purchase; no eBay checkout or bidding API in this pilot.
- Data handling for eBay review: intended retention of listing IDs, titles, prices, timestamps, seller identifiers and image references; derived ask statistics; AI-assisted card/condition review; cross-market comparison and recommendation. Request **express written approval** for each permitted use, including inference-only external AI processing, historical retention, derived per-card prices, and any combined display with other marketplaces. Treat nonapproval of any one as a product-scope constraint, not a technical problem.
- A reviewable Sandbox flow, source-policy settings, deletion/expiry behavior and a plan for following eBay's user experience requirements.
- Whether affiliate tracking or eBay Partner Network enrollment is required for this business model, and the final production access procedure for the account.

Never paste client secrets into a command or repository. The probe reads `EBAY_CLIENT_ID` and `EBAY_CLIENT_SECRET` from the environment. It performs one fixed-price search, returns only response shape and counts, and retains no token or listing body:

```bash
python3 -m pokemon_index probe-ebay-browse --environment sandbox --query "Pokemon Pikachu card"
```

Production probing additionally requires eBay's actual approval, `EBAY_PRODUCTION_APPROVED=1`, and the explicit `--production-approved` flag. The flag records operator intent; it does not confer a license. Do not run the pilot collection until the source policy reflects the approved data uses.

## 100-printing pilot prepared

[`catalog/ebay-pilot-targets.jsonl`](catalog/ebay-pilot-targets.jsonl) contains 10 exact-printing catalog identities for each of five character buckets in each of two languages. The 100 cards span 59 language/set pairs. This is a coverage sample selected without sales data; it must not be described as popular or high-volume cards. The intended test is 14 days, one search per target per day (100 search calls/day), with separate detail calls bounded by actual quota. There is no active scheduler or production feed yet.

After **both** production access and written approval of the specific data uses, compare observed results with each target's exact card identity. The Browse adapter converts fixed-price results to unresolved observations, in USD cents, with listing ID, seller, observed time and response hash. The `ebay_us` source is hard-gated from automatic title-only resolution. Photo/finish and condition review must complete before an offer can enter a card's ask index, and that photo use itself must be approved. Generic eBay `condition` is not a Pokémon card grade. Unknown domestic shipping, tax or forwarding cost must remain unknown until separately quoted.

For a source with `photo_resolution_required`, an internal operator can run `visual-gate` and then `approve-visual-resolution <source> <native_id> <observed_at> <card_id>` after two independent model families agree on the card, finish and raw condition from authorized front/back photos. The approval is tied to **that exact observation timestamp**; a later observation disappears from offers, seller overlap and the ask index until reviewed again. A manual `override-resolution` cannot bypass this gate. Approval rejects a catalog variant that differs from the observed finish. This machine decision does not verify authenticity or provide a paid-sale price. eBay's pending source policy still disables ingestion, display and media AI; this flow is testable only with synthetic data until written authorization arrives.

For an authorized saved Browse search response, the offline conversion is:

```bash
python3 -m pokemon_index adapt-ebay-browse response.json \
  --observed-at 2026-09-27T00:00:00Z --output observations.jsonl
```

The adapter does not imply permission to import. Register an `ebay_us` source policy with the agreed rights scope first, then import. Search results are not treated as complete inventory and nonappearance never creates a sale event.

[`examples/ebay_source_policy_pending.jsonl`](examples/ebay_source_policy_pending.jsonl) is the safe default: ingest, display, cross-source statistics and media AI are all disabled. Replace it only with the exact rights granted in writing and the resulting retention period. The current adapter and pilot cohort can be verified with synthetic fixtures while access is pending.

# API access application packet — 23 September 2026

**Project:** Pokémon Commerce Index, a private staging catalog of 26,630 Japanese card identities across 342 sets. The pilot maps a card by language, set, collector number and printing, then compares current offers only at the same condition or grade. A displayed offer remains distinct from a verified paid price. The pilot is limited to approximately 50 selected cards, with no card images, seller profiles or bulk public data export.

**Applicant details to confirm before submission:** legal company name, company website, business contact name and work email, country of incorporation, product URL or private demo URL, intended customer markets, privacy-policy URL, data-retention proposal, and the person authorized to accept terms. Do not use a personal email or accept terms on behalf of another company by assumption.

## Which applications are real

| Source | Route | Apply for | Decision needed before production use |
| --- | --- | --- | --- |
| SNKRDUNK / SODA | Business inquiry to [SODA's current contact](https://soda-inc.jp/page); no official public market-data key found | Written partner data agreement and approved feed/API; small sample export first | Permission for collection, storage, current-price display, cross-market comparison and derived statistics. [Current terms](https://snkrdunk.com/terms) expressly prohibit crawling/scraping. |
| Buy&Ship | Existing business/technical contact; no self-service key | Test gateway credentials, current API contract, quotas and source-specific data rights | Mercari/Yahoo access through the gateway is not itself permission to republish or model their data. [Technical and rights request](SOURCE_ACCESS_REQUEST.md). |
| eBay | [Developer Program registration](https://developer.ebay.com/signin?tab=register), then Sandbox and Production keysets under Application Keys | Browse API application credentials for a limited listing-display pilot; separate written review of cross-source price-index use | The [API License Agreement](https://developer.ebay.com/join/api-license-agreement) limits derived seller/market statistics, AI use and pricing tools. [Marketplace Insights](https://developer.ebay.com/api-docs/buy/ref-marketplace-supported.html) is restricted and not open to new users. A key is not approval for those uses. |
| Pokémon TCG API at pokemontcgapi.com | Optional [free trial signup](https://pokemontcgapi.com/free-api-key) using a company-owned email | Evaluation-only server key for Japanese catalog coverage and identity fields | Its [terms](https://pokemontcgapi.com/legal/terms) allow commercial products but restrict a substitute bulk catalog and redistribution of upstream price observations. Confirm intended internal indexing and public field use before broad import. This is a third-party service, not a Pokémon rights-holder API. |
| TCGdex | Already using a pinned [open-source database](https://github.com/tcgdex/cards-database) | No key needed for the current local-source workflow | Image/trademark and public-display rights remain separate from the repository's database license. |
| Yahoo Auctions Japan | **No direct public developer key route** | Ask Buy&Ship or LINE Yahoo for a specific partner channel | [Yahoo's developer notice](https://developer.yahoo.co.jp/changelog/auctions.html) records the Auctions Web API shutdown. Do not apply for a Yahoo Shopping ID expecting auction listings. |
| Yahoo Shopping Japan | Optional, separate marketplace: [application management](https://e.developer.yahoo.co.jp/) | Shopping application ID for [Shopping item search](https://developer.yahoo.co.jp/webapi/shopping/v3/itemsearch.html) | This covers shops, not Yahoo Auctions or its sold transactions; review commercial-use and display rules separately. |

## SNKRDUNK / SODA inquiry — Japanese draft

**To:** `info@soda-inc.com` (verify the current address on [SODA's site](https://soda-inc.jp/page) before sending)

**Subject:** ポケモンカード商品・出品データの正式なAPI／データ連携について

株式会社SODA ご担当者様

私たちは、日本語ポケモンカードについて、カードの版・状態・鑑定グレードを区別した商品検索と、各出品の価格比較を検討しています。現在、独自に構築した26,630件のカード識別子を持ち、まず約50商品の小規模な検証を希望します。SNKRDUNKの規約に従い、Webサイトのクローリングやスクレイピングは行わず、正式なデータ提供方法と利用許諾についてご相談したくご連絡しました。

可能であれば、商品ID・カードのセットコード／番号／版、出品ID、状態（A〜D）・鑑定会社／グレード、現在の出品価格、通貨、更新時刻、在庫状態、商品リンクを含むAPIまたは定期的なデータフィードをご案内いただけますでしょうか。商品ページの「最安値」と個別出品価格の違い、成立価格の提供可否も確認したいと考えています。

用途は、SNKRDUNKへの送客を伴う出品表示、同一版・同一状態での価格比較、および明示的に許可された場合に限る統計化です。保存期間、表示可能な項目、他市場との比較、AIによる商品名マッチング、画像利用、必要な表示・リンク・課金条件を契約で定めたいと考えています。最初は50商品のサンプルと利用条件の確認から始められれば幸いです。

会社名：`[LEGAL_COMPANY_NAME]`  担当者：`[CONTACT_NAME]`  連絡先：`[WORK_EMAIL]`  サービス概要：`[COMPANY_WEBSITE_OR_PRIVATE_DEMO]`

どうぞよろしくお願いいたします。

## Buy&Ship request — send to the existing partner contact

**Subject:** Pokémon card pilot: gateway test access and data-use scope

We have built an internal Japanese Pokémon card catalog with 26,630 identities, so we do not need Buy&Ship to supply a product catalog. For a 50-card pilot, please provide a test gateway URL, separate staging credentials, current search/item/batch contracts for Mercari and Yahoo, pagination and quota limits, and anonymized examples covering active, trading, sold and deleted items.

Please confirm in writing, separately for each marketplace, whether we may store raw responses and price history, display a current offer with attribution, compare authorized sources, compute per-card ask statistics, classify titles with rules or an AI model, and use transaction status or final paid amounts. We also need the landed-cost fee schedule, shipping/insurance fields and the buyer handoff contract. The detailed field list is in [SOURCE_ACCESS_REQUEST.md](SOURCE_ACCESS_REQUEST.md).

## eBay developer application text

**Application name:** `Pokemon Commerce Index`
**Business description:** “A buyer-facing Japanese Pokémon card discovery pilot. We maintain our own canonical card identifiers and intend to show current eBay listings with direct links, attribution and freshness, separating raw condition from graded cards. We will not infer paid sale prices from active listings.”

Create Sandbox and Production keysets through the [official keyset flow](https://developer.ebay.com/develop/guides/sell/get-started-with-ebay-apis). Request only the Browse API scope needed for current listings. Before using eBay content in a cross-market index, ask eBay Developer Support for written confirmation covering: comparison with other marketplaces; per-card ask medians and history; source data retention; AI-assisted title matching; and any seller-level features. Do not request Marketplace Insights as an available new-user sold-data feed: its official documentation says it is restricted and closed to new users.

## Optional Japanese card-data trial

Use a company-owned account at [pokemontcgapi.com/free-api-key](https://pokemontcgapi.com/free-api-key) for a bounded evaluation of Japanese set coverage, card identity and variant quality. Use a server key only; do not place it in GitHub, the browser, chat or the source ZIP. Request written clarification before bulk copying into our independently served catalog, because the provider's terms prohibit a substitute bulk catalog and have separate price-source restrictions. TCGdex remains the current primary seed.

## Credential handoff once approved

Create separate keys for staging and production where offered. Store secrets in Google Secret Manager in the relevant project, granting access only to the ingestion service identity. Keep raw secrets out of GitHub issues, email threads, documents and chat. Record for each source: contract owner, allowed fields/uses, retention period, expiry, quota, contact and revocation procedure. Test one or two read-only calls before any scheduled collection.

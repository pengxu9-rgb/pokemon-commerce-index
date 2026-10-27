# eBay / Fanatics Collect 接入申请材料

Prepared: 2026-10-26; onboarding scope updated 2026-10-27. Status: **draft only; not submitted**.

## 当前结论与边界

用户已确认：目前没有 eBay Developer、eBay Partner Network（EPN）或 Fanatics Collect 合作账户。状态应写为 **未申请 / 未配置**，不能写“申请中”或“已接入”。本材料没有创建账户、接受协议、联系平台或开启任何外部请求。

先申请 eBay Developer、激活适用的 Production keyset，以只读商品发现和跳转到 eBay 购买为首个范围；EPN 返佣与 Fanatics Collect 商务接洽可以并行，不阻塞普通 Browse 取价。affiliate 佣金资格、商品数据使用权、跨平台展示与价格历史是不同问题，分别确认。PSA / BNS 不作为看价和跳转的前置条件；卖家标注的 PSA 等级仍是未验证声明。

eBay 文档存在需要确认的差异：通用 [Buy API requirements](https://developer.ebay.com/api-docs/buy/buy-requirements.html) 描述合作审批流程，但该页面链接的现行 [Developer Questionnaire](https://partnernetwork.ebay.com/page/developer-questionnaire) 明确将 Browse 列为无需额外批准的 API。因此不应声称“所有 Browse 调用都必须再走限制 API 审批”。先完成账户与适用的 keyset 激活要求，再向 eBay 确认我们的商业模式、扩展权限和使用范围。

Fanatics 的官方招聘材料明确提到 Collect 的 affiliate / Impact 体系及 Collectr 等合作平台，这证明合作方向存在，不证明我们已获准接入，也不披露 Collectr 的具体合同。[Fanatics Collect affiliate role](https://job-boards.greenhouse.io/fanaticscollectibles/jobs/4376654009)。[Fanatics.com affiliate](https://www.fanatics.com/affiliates/x-51) 是另一个申请入口，不能据此假定覆盖 Collect；[Fanatics ID](https://api.docs.fan/) 是身份认证文档，不等于商品搜索或市场数据 API。

## 申请前需要补全的事实

以下空白必须由负责人确认；不得用竞品数据或预测冒充当前业绩。

| 项目 | 当前可写内容 / 待确认项 |
| --- | --- |
| 产品 | Pot / Pivota，面向 Pokémon 卡牌收藏者的浏览与购买发现产品；目前为邀请制 beta |
| 法律主体 / 注册地 | `[LEGAL_ENTITY]` / `[COUNTRY_OF_REGISTRATION]` |
| 联系人 / 业务邮箱 | `[CONTACT_NAME]` / `[PARTNER_CONTACT_EMAIL]`；尚未指定这两个平台的注册邮箱 |
| 对外站点 / 可评审入口 | `[PUBLIC_PRODUCT_URL]`、`[REVIEW_ACCESS_INSTRUCTIONS]`；私有测试入口不应直接当作公开站点填写 |
| 隐私政策 / 条款 | `[PRIVACY_POLICY_URL]`、`[TERMS_URL]`；需要实际可访问并符合真实数据处理方式 |
| 目标地区 / 买家地域 | `[INITIAL_BUYER_COUNTRIES]`；首个商品数据范围提议为 eBay US、USD，不等于已确认全部买家地区可佣金结算 |
| 真实规模 | `[CURRENT_INVITED_TESTERS]`、`[CURRENT_MONTHLY_ACTIVE_USERS]`、`[CURRENT_MONTHLY_OUTBOUND_CLICKS]`；未测量就明确说明 |
| 商业预测 | `[PILOT_CLICK_ESTIMATE_AND_ASSUMPTIONS]`、`[INCREMENTAL_GMV_ESTIMATE_AND_ASSUMPTIONS]`；与实绩分开 |
| eBay 账户 / EPN | 未申请；后续记录 Developer username、production App ID、EPN account / campaign ID 与权限凭据位置；不在此文档记录密钥 |
| Fanatics Collect | 未申请；尚无确认的 Collect 专用商务联系人、feed/API 合同或 affiliate program ID |

## eBay：建议办理顺序与表单清单

1. 负责人注册或指定 eBay member / Developer 账户，亲自完成身份验证与协议；准备 Sandbox 和适用的 production keyset。只有 App ID 可放入申请；Client Secret 不放入申请附件。
2. 按账户后台要求完成 Production keyset 激活与 [删除通知合规或真实适用的豁免](https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion)。不能把保存了商品摘要/指纹的聊天系统声明成“不持久化任何 eBay 数据”。
3. 普通 Browse 搜索与单条详情不统一要求 EPN / App Growth Check；对受限 API、feed 或扩展额度，按适用流程使用 [Developer Questionnaire](https://partnernetwork.ebay.com/page/developer-questionnaire)。EPN 在需要返佣时通过 [官方入口](https://partnernetwork.ebay.com/)另行办理。不要将本项目描述成需要 Order / Offer / Marketplace Insights 访问。首轮不申请交易 API，也不假设能够取得已成交数据。
4. 附产品截图和下面的数据流，提出使用范围问题。必要时通过 [Developer Support](https://developer.ebay.com/my/support/tickets?tab=app-check) 确认应走哪个审核流程。支持页面需要登录，本次未登录或提交。
5. 批准与账户配置完成后，另行约定有限请求数、有效期、测试查询与退出条件；当前 live 开关保持关闭。

表单需要的资料包括 EPN 注册账户邮箱、production App ID、业务概述、商业模式、买家国家、推广站点、展示方式、增量 GMV 估算和现有 API 使用情况。申请扩展额度时才补每日调用数与理由。该清单依据官方 [questionnaire](https://partnernetwork.ebay.com/page/developer-questionnaire)，具体字段以提交当天为准。

### English: EPN / business overview

**Business model:** Collectibles discovery and affiliate referral; early invite-only beta.

Pot is a Pokémon card discovery product developed by [LEGAL_ENTITY]. Collectors identify a specific printing and condition or seller-claimed grading level, then review marketplace listings and follow a clearly labelled link to the marketplace to complete their purchase. Our initial eBay scope is read-only discovery of current fixed-price US listings in USD. We do not take payment, submit bids, place orders, or represent an asking price as a completed sale or a final delivered price.

We propose to display eBay listings in a dedicated, clearly labelled eBay section, with observation time and visible affiliate disclosure. Canonical item URLs remain separate from tracked outbound links. Seller grading and certificate assertions remain unverified unless separately checked through an authorized certificate provider. No eBay content will be used for model training.

We are applying for EPN participation and would appreciate confirmation of the correct Developer keyset / production-access process for this scope. Our current audience, launch countries and expected pilot traffic are [FACTUAL_METRICS_AND_COUNTRIES]. The review URL is [PRODUCT_URL]; access instructions and screenshots are [REVIEW_MATERIALS]. We are not currently using live eBay APIs or feeds in this pilot.

### English: scope clarification / support request

**Subject:** Pot collectibles discovery — Browse / EPN setup and permitted use clarification

Hello eBay Developer / EPN team,

We are preparing the read-only referral experience described above. Your general Buy requirements page describes a production approval process, while the linked Developer Questionnaire says Browse does not require additional approval. Please confirm the account, production-keyset activation, App Growth Check and business-model review requirements that apply to our application.

Could you also confirm in writing whether the following proposed uses are permitted, and which require a separate agreement?

- Clearly separated eBay and third-party marketplace listing sections for a collector-selected card; no merged marketplace ranking in the initial pilot.
- User-requested agent orchestration and presentation of approved listing fields. Please distinguish deterministic display from any external AI inference; we will not send eBay data into an external model without confirming the permitted scope.
- Short-lived listing caching, refresh / deletion requirements, and limited operational logs.
- Any future per-card observation history, valuation or comparison feature. These are excluded from the initial live pilot until their rights and required data access are resolved.
- Eligible buyer regions, link attribution, app / mobile web rules and disclosures. If a buyer later uses a forwarding or proxy-purchase service, does attribution remain eligible, and under what conditions?

The initial application does not request Order, Offer, Marketplace Insights, automated checkout, seller repricing, or bulk redistribution. Please advise which approved fields, APIs and review materials you need. We will provide actual company, site and audience details, not estimates presented as achieved results.

Thank you,
[CONTACT_NAME]
[ROLE], [LEGAL_ENTITY]
[BUSINESS_EMAIL] | [PRODUCT_URL]

### eBay technical scope to show reviewers

```text
Collector selects card / printing / condition
  -> server-only approved Browse access
  -> current fixed-price listing evidence
  -> dedicated eBay listing section + observed time + seller-claim labels
  -> eBay-returned tracked item link (only after EPN configuration)
  -> eBay hosts checkout and payment
```

The [Browse guide](https://developer.ebay.com/api-docs/buy/static/api-browse.html) documents `affiliateCampaignId` in `X-EBAY-C-ENDUSERCTX` and the returned `itemAffiliateWebUrl`. No live credential, campaign or returned link is configured yet. An ordinary search or product link alone does not supply an offer price or prove affiliate attribution.

Policy review must use the current [API License Agreement](https://developer.ebay.com/join/api-license-agreement): §8.1.2 requires public eBay content isolation; §8.1.3 sets listing freshness within six hours and other content within 24 hours, with age disclosure when behind the site. Specified derived statistics need permission. §8.5 applies distinct restrictions to Restricted API data and external AI / pricing tools; §9.10 prohibits training with eBay content. §9.5 restricts suggesting or modelling eBay listing prices using eBay and third-party data. Our requested history, comparison and agent uses must be resolved against these provisions rather than inferred from affiliate acceptance. This is a scope checklist, not a claim of legal clearance.

## Fanatics Collect：商务接洽材料

尚未确认公开的 Collect 商品 API / feed 自助开通流程或 Collect 专用申请表。先请官方将材料转交 **Fanatics Collect affiliate / partnerships** 团队，或由已有商务联系人引荐。不要把招聘申请入口当合作申请表，也不要把 Fanatics.com 商品联盟账户当 Collect 授权。未取得合作数据前，不调用未公开端点、不生成虚构报价。

### English: partnership introduction

**Subject:** Fanatics Collect partnership inquiry — Pokémon discovery and affiliate referrals

Hello Fanatics Collect Partnerships team,

I am [CONTACT_NAME] from [LEGAL_ENTITY], building Pot, an invite-only Pokémon card discovery product. We would like to help collectors find relevant Fanatics Collect inventory and send qualified buyers to your marketplace to complete purchases. Please route this inquiry to the team responsible for Fanatics Collect affiliate and platform partnerships.

The proposed first experience is read-only: the collector selects an exact card printing and condition, reviews licensed listing information in a labelled Fanatics Collect section, and follows your approved product or tracked affiliate URL. Checkout, payment and fulfillment remain with Fanatics Collect. We will distinguish seller-claimed grades, certificate records and actual physical-item authentication.

Could you advise whether you offer a partner API, licensed feed or another approved inventory integration, and a Collect-specific affiliate program? We would like to confirm:

- Permitted fields: stable listing and card identifiers, canonical and tracked URLs, asking price and currency, listing / auction type, availability, observation time, photos, seller grading / certificate evidence and their provenance.
- Price semantics: Buy Now ask versus current bid, hammer price and completed paid sale; applicable buyer premium, taxes, payment, shipping and withdrawal costs; correction and unpaid-sale handling.
- Cache / refresh limits, sold / withdrawn deletion, image display rights, deep-link behavior and mobile support.
- Permission for labelled multi-market discovery, agent-assisted presentation, and any separately licensed historical or valuation feature. No model training is proposed.
- Geographic eligibility, attribution windows, commission rules, cancellation / return treatment, disclosure requirements and whether proxy purchases or forwarding services are eligible.
- Sandbox / sample data, onboarding review and a bounded read-only pilot with agreed request limits.

We do not currently have a Fanatics Collect partner account or licensed feed and have not activated automated collection. Our product URL, actual audience and initial target countries are [PRODUCT_URL], [FACTUAL_AUDIENCE] and [COUNTRIES]. We can share screenshots and a data-flow diagram for review. We are seeking Fanatics Collect marketplace coverage specifically, rather than assuming the Fanatics.com merchandise affiliate program covers it.

Thank you,
[CONTACT_NAME]
[ROLE], [LEGAL_ENTITY]
[BUSINESS_EMAIL] | [PRODUCT_URL]

## 离线技术缺口与验收准备

| 能力 | 当前状态 | live 前需取得的证据 |
| --- | --- | --- |
| eBay 官方账户与 production keyset | 未申请 / 未配置 | 账户、可用权限、适用审核结果；密钥只进获准服务端 secret 配置 |
| EPN | 未申请 / 未配置 | 接受结果、真实 campaign ID、允许的地区与业务模式 |
| eBay agent / comparison / history 权限 | 未确认 | 书面范围确认；未获准功能继续关闭 |
| Fanatics Collect | 未申请 / 未配置 | 官方商务渠道、Collect 专用合作许可、feed/API 文档与样例 |
| 价格真实性 | 只做离线实现与测试 | 有界 live 样本中的商品 ID / URL / 币种 / ask / 时间与状态一致；不把竞价或历史成交当即时报价 |
| 购买跳转 | 只做离线实现与测试 | 官方返回的同一商品 tracking URL、明确披露、canonical URL 不被替换；不下单 |
| 等级与证书 | 卖家声明与验证状态分开 | PSA 等独立能力准备好后另行获准测试；不把证书存在等同实物真伪保证 |
| BNS / 转运 | 独立可选路径 | 后续单独确认报价、目标地区和联盟归因；本轮不启用 |

离线回归应覆盖：默认零网络、缺配置拒绝、URL 与商品身份不一致、危险跳转、过期或结束商品、价格精度 / 币种、auction-only 排除、affiliate 披露和 canonical URL 保留。最终 live 测试的次数与时间窗需要另行确定；本材料不授予调用、账户注册、对外提交、发布或部署权限。Release pins 保持原值。

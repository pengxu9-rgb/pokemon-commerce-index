# Pokémon Commerce Index — clean-room vertical slice

这是一个可运行的新项目，用于验证日文 Pokémon 卡片的身份归一、报价观测、到手价和卖家库存重合度。它没有复用旧 demo 的代码、数据或图片，也没有内置 SNKRDUNK、Mercari、Yahoo 或 eBay 爬虫。本项目依据用户提供的 build plan 独立实现。旧 demo 的 private GitHub 仓库现已通过授权账号读取；已核对其 Mercari 网关接口和 Yahoo 接口用法，实际接入仍以 Buy&Ship 最新契约与数据授权为准。

**主线开发顺序见 [BUILD_SEQUENCE.md](BUILD_SEQUENCE.md)：卡片身份及探索关系 → 获准的 API 报价 → 商品关联与 ask index → 到手价／品相辅助判断／商家建议。探索状态先支持用户逐步选定目标；购买建议仍等待真实报价证据。人工双审是并行质检工具，不是前三层的开工门槛。**

Buy&Ship API feed 暂时等待对方提供。独立审查和不依赖 feed 的实施顺序见 [ASTRA_REVIEW_AND_PLAN.md](ASTRA_REVIEW_AND_PLAN.md)。

卡片目录已独立扩展，数量与来源限制见 [CATALOG_COVERAGE.md](CATALOG_COVERAGE.md)。
内部查询快照 `catalog-index.sqlite3` 可从种子重建，未提交到 GitHub；无实时市场报价。
私有 Google Cloud staging 部署方式见 [CLOUD_RUN.md](CLOUD_RUN.md)；生产项目在部署脚本中被禁止。

第二步对 Buy&Ship 的接口与数据授权请求已整理在 [SOURCE_ACCESS_REQUEST.md](SOURCE_ACCESS_REQUEST.md)。
API 报价、商品身份和品相证据如何汇合，见 [OFFER_CONDITION_CONTRACT.md](OFFER_CONDITION_CONTRACT.md)。

## 已实现

- 卡片身份：`语言 + 系列代码 + 收藏编号 + 版本`；可计价单元再区分评级机构、分数和裸卡品相。
- 带来源权限的 JSONL 导入；观测保留原始标题、URL、状态、价格、时间和采集原因。自动匹配只接受明确的系列代码与编号，其他 listing 留在未解析队列；人工改判留痕。
- 三种严格分开的价格序列：`ask`（当日有效在售挂牌）、`last_list_at_transition`（交易状态变化前的最后挂牌）、`verified_paid`（有支付/结算凭据的成交）。没有凭据时成交序列为空。
- 当前到手价推荐是 `price_only`：只比较**相同可计价单元**、相同目的地和同一币种的未过期完整报价。价格组件由上游报价方提供；本项目不会猜测运费、税费或汇率。商品实际品相的证据评估与综合推荐尚未接通。
- 卖家库存重合度仅在来源明确允许 seller analytics 时计算；不生成可信卖家评分。
- 校准报告：从授权的卖家真值样本计算发现前售出覆盖率、Wilson 区间和漏掉/捕获 listing 的价格比。
- 来源级保留期限、listing 新鲜度和跨来源使用开关。默认不允许跨来源混合展示或卖家画像。
- 卡片目录逐条记录 `rights_reference` 和是否准许展示。旧数据库经 `init` 升级后，原有卡片默认不可展示，须重新导入并确认权利。
- Buy&Ship Mercari 旧网关响应适配器、至多三次只读请求的 Gate 0 探针，以及 Pivota 候选商品交接契约。它们未连接真实生产数据。
- TCGdex 日文卡组 JSON 的文本元数据适配器；不导入卡图、图片 URL、徽标或规则文本。
- 固定 TCGdex commit 的日文目录：16,347 条可区分版本元数据；第二来源另补 10,233 条单记录与 462 条多记录同名候选，保留 24,039 条参考记录；TCGdex 另有 50 条版本歧义候选。日文合计 27,092 条。
- 同一固定 commit 的英文实体卡目录覆盖 Base、Mega Evolution、Scarlet & Violet、Sword & Shield、Sun & Moon：79 个卡组、18,730 条可解析版本身份及 135 条版本歧义候选。另通过官方 TCGdex 卡组 API 冻结 126 个缺口卡组的清单，新增 9,208 条未核实印刷版本的卡组＋编号候选，4 个卡组清单为空。按语言隔离卡组元数据；Pokémon TCG Pocket 数字卡不在实体卡目录。日英合计 **55,165 条内部身份、543 个有卡片的语言＋卡组组合**，公开展示批准数为 0。所有身份均无实时价格；API 候选和版本歧义卡禁止自动报价匹配。
- 内部目录命令可查卡名／卡组／卡号、同卡号的不同版本、来源和各卡组覆盖数量；该命令不对外提供 HTTP 路由，公开 API 仍遵守 `display_allowed`。
- 内部关系图可查询同卡组／编号的版本邻居；日英对应、相同画作和收藏替代项仅作为带证据的断言进入库，经过人工核实才可作事实性探索。状态改变以新断言记录，不覆盖旧证据。结构化探索 session 保存语言、卡组、预算等约束、shortlist 和最后选定的精确卡片；只有 `match_eligible` 的卡片可进入后续 offer 跟踪。当前没有自动生成的日英对应边或真实用户 session。
- 固定 TCGdex 源另提供 59,710 条内部角色 ID／画师属性记录，覆盖 28,361 个带角色 ID 的卡片身份与 31,071 个带画师的身份。英文角色名可通过同一 Pokédex ID 找到日文的**同角色候选**，结果标记 `same_character`，不会创建同画作或日英对应印刷关系。具体范围与 4 个非标准 ID 缺口见 [CATALOG_COVERAGE.md](CATALOG_COVERAGE.md)。

`purge-expired` 需由部署环境定期运行；`expires_at` 停止该来源的导入和展示，数据删除仍按独立的 `retention_days` 执行。

## 本地运行

仅需 Python 3.11+，无运行时第三方依赖。以下命令在项目目录执行：

```bash
python3 -m pokemon_index --db demo.sqlite3 init
python3 -m pokemon_index --db demo.sqlite3 register-source examples/sources.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-cards examples/cards.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-observations examples/observations.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-quotes examples/quotes.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-verified-sales examples/verified_sales.jsonl

python3 -m pokemon_index --db demo.sqlite3 discover 'SV2a 173/165'
python3 -m pokemon_index --db demo.sqlite3 discovery '日版 PSA10 ピカチュウ SV2a 173/165'
python3 -m pokemon_index --db demo.sqlite3 units 'ja:SV2A:173/165:standard'
python3 -m pokemon_index --db demo.sqlite3 recommend 'ja:SV2A:173/165:standard|RAW|raw|a' --destination HK --as-of 2026-09-22T09:30:00Z
python3 -m pokemon_index --db demo.sqlite3 index 'ja:SV2A:173/165:standard|RAW|raw|a' 2026-09-22
python3 -m pokemon_index --db demo.sqlite3 calibrate examples/panel_sales.jsonl
python3 -m pokemon_index --db demo.sqlite3 calibrate examples/panel_sales.jsonl --gate-config examples/gate1_config.json
python3 -m pokemon_index --db demo.sqlite3 export-pivota 'ja:SV2A:173/165:standard' --destination HK --as-of 2026-09-22T09:30:00Z
python3 -m unittest discover -s tests -v
```

实际日英目录先导入到内部数据库，再查询身份与版本：

```bash
python3 -m pokemon_index --db catalog.sqlite3 init
python3 -m pokemon_index --db catalog.sqlite3 import-sets catalog/ja-all-sets.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-sets catalog/en-physical-sets.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-sets catalog/en-api-sets.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/ja-all-available.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/en-physical-cards.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/en-physical-ambiguous.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/en-api-candidates.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/ptcg-jp-candidates.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/ptcg-jp-multi-record-candidates.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-cards catalog/tcgdex-ambiguous-candidates.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-card-references catalog/ptcg-jp-reference.jsonl
python3 -m pokemon_index --db catalog.sqlite3 import-card-facets catalog/card-facets.jsonl.gz
python3 -m pokemon_index --db catalog.sqlite3 catalog-status
python3 -m pokemon_index --db catalog.sqlite3 catalog-search 'SV2a 025/165'
python3 -m pokemon_index --db catalog.sqlite3 catalog-search --dex-id 25 --limit 20
python3 -m pokemon_index --db catalog.sqlite3 catalog-search --illustrator 'Naoyo Kimura' --limit 20
python3 -m pokemon_index --db catalog.sqlite3 catalog-card 'ja:SV2A:025/165:reverse_masterball'
python3 -m pokemon_index --db catalog.sqlite3 catalog-search 'S6a 087/069'
python3 -m pokemon_index --db catalog.sqlite3 catalog-neighborhood 'ja:SV2A:025/165:normal'
```

`catalog-search` 和 `catalog-card` 仅供内部开发查询，返回来源、展示标记与匹配资格。它们不会更改公开展示权限；示例中的 `SV2a 025/165` 会返回普通版、Master Ball 与 Poké Ball 三个不同身份。S6a 补充候选可以查到，但 `match_eligible=false`，不会进入自动报价匹配。

角色 ID 与画师属性可由固定源码重建；输出必须为新文件，构建器会逐个核对源码 SHA-256：

```bash
python3 -m scripts.build_discovery_facets \
  --repo ../../work/tcgdex-public \
  --revision a211f11f3ba57d56c65c5ac33be35b77d3280757 \
  --cards catalog/ja-all-available.jsonl --cards catalog/en-physical-cards.jsonl \
  --output facets-rebuilt.jsonl.gz --report facets-rebuilt-audit.json
```

内部探索状态使用逐次递增的 `expected_version` 防止覆盖其他步骤的选择。JSONL 文件每次只含一个 session 更新，例如 `{"session_id":"example-1","owner_key":"opaque-user-1","expected_version":0,"constraints":{"query":"ピカチュウ","language":"ja","budget_minor":20000}}`。随后执行 `save-exploration <file>`、`exploration example-1 --owner-key opaque-user-1`、`exploration-candidates example-1 --owner-key opaque-user-1`、`exploration-decision example-1 --owner-key opaque-user-1`。最后一条按实际候选给出一个下一步问题。锁定目标时提交下一版本及 `target_card_id`；暂时无法确定版本时保持 shortlist，不生成购买建议。暂停后需显式设置 `status=targeted` 才能恢复；更换语言、卡组、卡号或版本时，先清除或替换冲突目标。预算、评级与目的地被保存，但目前不会过滤目录卡片或无权取得的报价。`owner_key` 是调用方提供的匿名作用域标识，不应放入个人资料或认证密钥。当前没有账户认证和会话保留策略，所以这些写入命令仅供受控内部环境使用。

合成目录的完整例子：

```bash
python3 -m pokemon_index --db demo.sqlite3 save-exploration examples/exploration_create.jsonl
python3 -m pokemon_index --db demo.sqlite3 exploration-decision demo-exploration --owner-key demo-opaque
```

审核关系可通过 `import-relationships <jsonl>` 导入。每条断言需有 `left_card_id`、`right_card_id`、`relation_type`、`review_status`、`evidence_ref`、`rights_reference`、`asserted_by`；`verified` 或 `rejected` 还需 `reviewer`。可选 `assertion_id` 是一次审核事件的稳定 ID，重试同一事件不会重复写入；修改关系审核状态时使用新 ID。支持的关系是 `localization_counterpart`、`same_artwork`、`collecting_alternative`。其中 counterpart 不代表两张卡可共用价格；被驳回的边不会用于跨语言发现。所有关系与探索候选仅供内部使用，不能绕过卡片公开展示许可。

示例数据完全是合成数据，包括价格、支付凭据和到手价；URL 使用 `.invalid` 域名。`--as-of` 用于重放旧样本，实时 API 默认使用当前时间和来源设置的新鲜度上限。

启动只读 JSON API：

```bash
python3 -m pokemon_index --db demo.sqlite3 serve --port 8765
```

端点：`/health`、`/discover?q=...`、`/discovery?q=...`、`/units?card_id=...`、`/offers?card_id=...&destination=...&as_of=...`、`/recommend?unit_id=...&destination=...&as_of=...`、`/index?unit_id=...&date=YYYY-MM-DD`、`/seller-overlap?source=...&unit_ids=...`。带 `--internal-catalog-api` 时另有 `/catalog-neighborhood?card_id=...`；探索 session 的读写暂不开放 HTTP。`/discovery` 仅做保守的规则化意图解析，无法确定时弃答；没有接入 LLM。服务默认只绑定 `127.0.0.1`，没有用户认证，不能直接公开部署。

## 输入契约

所有文件为 UTF-8 JSONL，每行一个对象。`examples/` 是完整样例。

| 文件 | 关键字段 |
| --- | --- |
| Source policy | `source`, `rights_reference`, `ingest_allowed`, `display_allowed`, `cross_source_use_allowed`, `seller_analytics_allowed`, `retention_days`, `listing_ttl_hours`, 可选 `expires_at` |
| Card | `language`, `set_code`, `collector_number`, `name`, `provenance`, `rights_reference`, `display_allowed`；可选 `variant`, `rarity`, `match_eligible`, `attributes`。未明确允许展示时填 `false`；版本未经核实时 `match_eligible=false` |
| Set metadata | `set_code`, `official_card_count`, `provenance`, `rights_reference`；可选 `name_ja`, `release_date_ja`, `display_allowed` |
| Card reference | `source`, `source_jp_id`, `name`, `provenance`, `rights_reference`；可选 `set_code`, `collector_number`, `rarity`, `attributes`, `display_allowed`；仅供内部查证，不进入自动匹配 |
| Observation | `source`, `native_id`, `title`, `url`, `observed_at`, `status`, `currency`, `evidence_ref`；可选 `price_minor`, `language`, `variant`, `card_id`, `condition_bucket`, `seller_native_id`, `poll_reason` |
| Landed quote | `source`, `native_id`, `destination`, `currency`, `components`, `quoted_at`, `expires_at`, `evidence_ref`；可选 `assumptions` |
| Verified sale | `source`, `native_id`, `settled_at`, `paid_minor`, `currency`, `evidence_ref` |
| Calibration panel | `source`, `native_id`, `sold_at`, `last_price_minor`, `bucket` |

金额使用货币最小单位整数：JPY 为日元，HKD 为港分。所有时间须带 UTC offset。`components` 必须完整包含 `item`, `domestic`, `service`, `international`, `tax`, `insurance`, `fx_spread`, `other`；仅在报价方确认某项不适用时填零，未知费用不能填零。所有组件以目的地币种计价。`poll_reason` 可选 `discovery`, `tracking`, `panel`, `auction_end`。

## Buy&Ship Mercari 接入准备

旧 demo 的 Postman 样例表明网关有搜索、详情和批量查询接口；当前接口与签名规则仍须 Buy&Ship 确认。拿到有权使用的原始 JSON 响应后，先在来源策略中登记 `mercari_bns`，再离线转换：

```bash
python3 -m pokemon_index --db demo.sqlite3 adapt-mercari response.json \
  --endpoint search --observed-at 2026-09-22T09:00:00Z --output mercari-observations.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-observations mercari-observations.jsonl
```

适配器保留原生 `created`/`updated` 字段及每个商品的 SHA-256 证据引用，并在本地 `raw_item_blob` 表保存对应原始商品 JSON，按来源保留期清理。原始响应文件也需按授权要求管理。它不猜测卡片语言、评级或实际支付金额，无法确定卡片身份时进入待解析队列。`response.json` 可以是 `search`、`item` 或 `fetch_items` 的响应；输出文件必须尚不存在，避免覆盖证据。

网关探针需在 Buy&Ship 确认授权、提供测试环境和凭据后运行。凭据通过 `BNS_MERCARI_HMAC_SECRET` 环境变量注入，不写入仓库或命令参数；只有明确启用旧 demo 签名方式时才发请求：

```bash
python3 -m pokemon_index --db demo.sqlite3 probe-mercari \
  --base-url https://gateway.example.invalid --historical-item-id m123456789 \
  --category-id CONFIRMED_CATEGORY_ID --allow-legacy-auth
```

探针最多查询一个旧商品 ID、一次分类无关键词搜索和一次售出状态搜索，只输出响应结构摘要。旧签名方式仅作兼容性探测；正式持续采集要等 Buy&Ship 审定新的认证契约和配额。此项目没有自动调度的爬虫或后台轮询。

Gate 1 使用授权卖家完整库存样本的 `panel_sales.jsonl` 加实测的售出商品详情和日配额作决策。`min_hot_sales`、`min_mid_sales` 必须由事前功效分析确定，避免用两三个样本做 go/no-go 判断。配置中的 `null` 表示尚无证据，输出 `insufficient_evidence`；达到样本门槛后覆盖不足、拿不到售出价格或配额不足则输出 `no_go_clear_price`。即使通过，也只把最后挂牌价称作 `last_list_at_transition`；实际支付价仍须独立凭据。校准面板的非随机选样偏差需人工审查，不能由阈值自动消除。

## 自建日文卡片目录

[TCGdex cards-database](https://github.com/tcgdex/cards-database)声明其数据库按 [MIT License](https://github.com/tcgdex/cards-database/blob/master/LICENSE)提供，其[日文 set API](https://tcgdex.dev/rest/set)返回卡片编号及名称。可先用授权确认过的 JSON 快照做元数据种子；本项目不会抓取 SNKRDUNK，也不会随卡片导入卡图。第三方数据库许可证不等于 Pokémon 官方图像/商标授权，公开展示范围仍需单独核对。

```bash
python3 -m pokemon_index --db demo.sqlite3 adapt-tcgdex-set \
  examples/tcgdex_set_synthetic.json --rights-reference 'synthetic fixture' \
  --output candidate-cards.jsonl
python3 -m pokemon_index --db demo.sqlite3 import-cards candidate-cards.jsonl
```

默认生成 `display_allowed=false`，仅作为内部匹配种子；确认元数据展示权后才加 `--display-approved`。适配器记录每条卡的来源 ID 与快照 SHA-256，按 `localId / cardCount.official` 生成编号；重复编号会中止并交由人工区分版本。

仓库另含从 TCGdex 固定提交 `a211f11f3ba57d56c65c5ac33be35b77d3280757` 构建的逐组文件、合并目录 [`catalog/ja-selected-modern.jsonl`](catalog/ja-selected-modern.jsonl)、[覆盖审计](catalog/coverage-report.json)、[本期目标](catalog/phase1-targets.json)及 [MIT 许可文本](catalog/TCGDEX-LICENSE)。`scripts.build_tcgdex_set` 使用 GitHub CLI 只获取 TypeScript 元数据；可复现单组，再合并：

```bash
python3 -m scripts.build_tcgdex_set \
  --set-path data-asia/SV/SV2a \
  --revision a211f11f3ba57d56c65c5ac33be35b77d3280757 \
  --output catalog/rebuild-sv2a.jsonl --audit catalog/rebuild-sv2a-audit.json
python3 -m scripts.normalize_catalog_numbers
python3 -m pokemon_index --db demo.sqlite3 import-cards catalog/ja-selected-modern.jsonl
```

原阶段性目录覆盖本期 17 个目标中的 16 个卡组，仍保留作为回归样本。新版 [`catalog/ja-all-available.jsonl`](catalog/ja-all-available.jsonl) 遍历同一 TCGdex 提交的全部 `data-asia` 卡组，保留 16,347 条有日文名称且版本可表示的记录；包括 promo 编号、老卡 1st edition 和 unlimited。卡号统一为三位最低宽度，例如 `080/073`。解析器要求标题有明确卡组代码与卡号；同一编号有多个版本时还须有可判定的版本证据。多卡、冲突语言与不确定版本进入待解析队列。

S6a 在 TCGdex 中仍缺日文逐卡名称；第二来源提供 87 条 set+number 候选。其余补充候选亦全部标 `match_eligible=false`，仅供内部发现和核验；参考记录与审计见 [CATALOG_COVERAGE.md](CATALOG_COVERAGE.md)。第二来源源自官方网页采集，仓库 MIT 许可不能替代 Pokémon 内容的公开使用授权，卡图和规则文本均未随本目录输出。SNKRDUNK 的公开网页仅用于少量人工核对身份与价格字段语义，未采集入库；其[现行利用规约](https://snkrdunk.com/terms)第 7 条第 1 款第 13 项明文禁止爬取与抓取。

专属标注 agent 从旧 demo 测试记录整理了 68 条 AI 辅助草稿，并二次撤回了没有独立证据的版本标签。[诊断摘要](catalog/label-draft-summary.md)与[真人复核口径](catalog/labeling-protocol.md)已准备好。当前 40 条卡组＋卡号候选中 34 条在目录内，标题规则接纳 28 条且与草稿身份一致；14 条应弃权样本无错误接纳。这些是样本内一致性，**不是正式匹配精度**；版本完整证据为 0 条，须真人看图复核后才能测版本精度。

[本地真人复核工作台](catalog/review-workbench.md)已实现：两位审核员独立标注、第三人裁决分歧，只有完成双审的样本才可导出。测试记录中的私有标题与图片链接保存在 `work/review/`，不随本交付包打包；工作台只监听本机，未提供远程账号认证。

## Pivota 交接

`export-pivota` 输出 `pokemon-commerce-to-pivota.v1` 候选数据，不直接写 Pivota 数据库。卡片版次为商品家族，评级及裸卡品相保留为独立可计价单元；Pivota 的 resolver 再决定 `content_key` 和 SKU 映射。offer 保留来源、挂牌时间、原币金额和可选到手价报价。Buy&Ship 的购买跳转或下单契约尚未确认，故 `purchasable=false`、`purchase_action=null`。生产接入前需在 Pivota 当前代码上验证身份粒度、offer 权限和入口路由。

## 接入门槛

1. **数据使用范围**：为每个来源取得书面依据，分别核对采集、存储期限、公开展示、跨来源比较、价格建模、卖家聚合、AI 使用和历史成交用途。SNKRDUNK 公开页面不得当作爬虫数据源。eBay 当前 [API License Agreement](https://developer.ebay.com/join/api-license-agreement)限制用 eBay 内容做跨渠道表现比较、价格建模及训练 AI；价格工具的特定受限数据用途还要求事先书面同意。因此不能凭普通 Browse API 凭据启用本项目的跨渠道价格索引，应先取得与具体产品用途匹配的许可。
2. **Buy&Ship 网关实测**：确认查询/详情/批量查询、旧 ID、状态、卖家范围、分页、配额和限流。当前适配器依据旧 demo 响应样例，只支持离线转换和显式启用的有限探针；持续采集必须以最新契约更新。
3. **成交语义**：分别验证 `trading`、`sold_out`、取消交易和接受 offer 后价格。若只能获得最后挂牌价，`verified_paid` 不得填充。
4. **卡片数据权利**：TCGdex 数据库许可不自动授权 Pokémon 卡图的产品展示。生产目录需单独确认数据与图片来源。
5. **校准样本**：卖家真值面板必须来自被授权的完整库存/交易接口；报告中的 Wilson 区间不能消除面板选样偏差。

## 下一步

下一步可独立核验高价值的补充候选和来源冲突；与此同时接入一条有明确数据使用权的真实报价来源，运行持续观测并发布带样本数与新鲜度的 ask index；再用 Buy&Ship 报价组成到手价及商家建议。Buy&Ship 网关文档与授权到位后验证当前适配器；Pivota 的 `content_key` 映射及 Buy&Ship 购买交接仍须由双方接口负责人确认。当前代码是 Gate 0 的工程底座，不声称已经拥有实时渠道覆盖或实际成交价指数。

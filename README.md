# Pokémon Commerce Index — clean-room vertical slice

这是一个可运行的新项目，用于验证日文 Pokémon 卡片的身份归一、报价观测、到手价和卖家库存重合度。它没有复用旧 demo 的代码、数据或图片，也没有内置 SNKRDUNK、Mercari、Yahoo 或 eBay 爬虫。本项目依据用户提供的 build plan 独立实现。旧 demo 的 private GitHub 仓库现已通过授权账号读取；已核对其 Mercari 网关接口和 Yahoo 接口用法，实际接入仍以 Buy&Ship 最新契约与数据授权为准。

**主线开发顺序见 [BUILD_SEQUENCE.md](BUILD_SEQUENCE.md)：卡片身份及探索关系 → 获准的 API 报价 → 商品关联与 ask index → 到手价／品相辅助判断／商家建议。探索状态先支持用户逐步选定目标；购买建议仍等待真实报价证据。人工双审是并行质检工具，不是前三层的开工门槛。**

Buy&Ship API feed 暂时等待对方提供。**2026-09-30 的当前主线见 [整体复盘与重排](HOLISTIC_ALIGNMENT_20260930.md)和 [独立对抗审查](ADVERSARIAL_ALIGNMENT_REVIEW_20260930.md)：可信卡片小范围与检索词 → 能执行并返回目录结果的收藏探索 → 同范围的报价链路演练 → 获准真实 feed。** 早期审查 [ASTRA_REVIEW_AND_PLAN.md](ASTRA_REVIEW_AND_PLAN.md)保留为历史记录。

**2026-10-01 实施结果：** 新增 100 个来源证据绑定的 SV4A 元数据目标、3 个官方卡组名称／日期补证、6 个检索词，以及拉鲁拉丝／伊布／皮卡丘三个官方进化家族；122 个已复核别名及 460 条复核事件进入新构建清单。`collector-discovery` 可从普通问题返回卡片、按日期分页的清单及版本澄清。手写开发问题首次 28/30，修正回放 30/30；100 目标的合成 commerce 演练通过 14 项检查，工程测试 351 项通过。详细范围与运行方式见 [SUPPORTED_DISCOVERY_IMPLEMENTATION.md](SUPPORTED_DISCOVERY_IMPLEMENTATION.md)。这些结果不代表真人提问准确率或真实 listing 精度；实际工艺仍未认证，自动关联 live offer 的正向批准数为 0。

新的 [buyer discovery journey 回归评估](DISCOVERY_JOURNEYS.md)在固定目录上覆盖 10 个手写场景、15 个结构化步骤；全部达到预期的澄清和目标选择。固定快照现含 657 条 AI 提议的同画面内部候选边，已核实跨区关系仍为 0，提议边不用于价格等价或报价合并。这是工程回归，不是自然语言理解或真实用户相关性测量。

[买家问题证据门槛](BUYER_QUESTION_LAYER.md)新增内部 `buyer-question-plan`：针对精确卡片，区分同编号版本、已核实跨语言关系、AI 同画面线索，以及仍需实时报价或商品照片的问题。独立问题集的离线评测入口已准备，但当前尚无真实用户问题盲测成绩。

[公开买卖家问题 sandbox](PUBLIC_QUESTION_SANDBOX.md)已冻结 24 个带来源链接的 Reddit、Elite Fourum 和 Yahoo!知恵袋问题情境，并由 Astra 与 Vertex Gemini 3.8 Flash 独立做证据分流。23 条双模型有效结果中，意图一致 20 条，首步动作一致 14 条；只有 2 条六字段完全一致。它衡量 AI 标签的一致性及定义缺口，尚不是目标 agent 的真实问答准确率。原始问题、两份独立标签与报告保存在 `sandbox/public_questions/v1/`。

第二批 **24 条新来源帖子改写的提示**已按修订后的标签独立复核（日文 8、英文 16）。意图一致 21/24、首步动作一致 13/24、卡片身份状态一致 11/24；来源复核又发现仅 13 条忠实于原帖问题，5 条是情境推演、2 条改变原意、4 条暂无法核实。[v2 数据、来源审计与失败重试记录](sandbox/public_questions/v2/)已归档，[目标 agent 回放评估器](scripts/evaluate_public_question_replay.py)可在独立路由输出到位后使用；这些数字不是自然语言问答准确率。

新增[结构化问题证据路由](PUBLIC_QUESTION_SANDBOX.md#v4-structured-facts-and-a-deterministic-evidence-plan)：以日英各 4 条经过原帖核查的新问题做开发回归，Astra 与 Gemini 的七项事实完全一致 4/8，确定性行动计划一致 6/8。路由先判断产品范围，再列出解释、澄清和证据要求；实时价格、成交价、商家收购价和品相判断均有独立门槛。v4 已参与规则修订，不能作为盲测准确率。

[v5 新问题测量](PUBLIC_QUESTION_SANDBOX.md#v5-fresh-questions-against-the-frozen-planner)在固定路由代码后完成来源门禁与日英双模型事实提取：12 条候选中 11 条进入冻结集，事实完全一致 2/11，行动计划一致 5/11。主要分歧来自产品对象与交易任务混在一个字段、印刷版本推断和未指明的“海外版”。[v2 字段与路由实施方案](QUESTION_ROUTING_V2_PLAN.md)据此形成；v5 保留原始结果，不用于回调分数。[v6 新问题复测](PUBLIC_QUESTION_SANDBOX.md#v6-fresh-source-gate-and-v2-fact-extraction)在固定 v2 后，12 条候选中 11 条通过来源门禁；8 条有两份有效事实，2 条完全一致，7 条行动计划一致，另 3 条 Gemini 结果为显式验证错误。这些数据仍不代表问答准确率或实时市场表现。

[v3 路由实验](QUESTION_ROUTING_V3.md)根据 v6 的具体分歧加入卖家已成交待履约、第三方商品观察、平台与商家分离、稀有度与工艺分离，以及可追踪的模型验证错误。复用 v6 问题的开发回归最终得到 11/11 条有效结构化输出；这一批已参与调参，不是新的盲测准确率。v3 尚未执行目录身份解析或获取实时市场价格。

[v4 趋势与买入时点路由](QUESTION_ROUTING_V4.md)把历史价格变化、买或等的问题分流到不同证据计划，并要求先确定卡片印刷版本。已看过的 v7 八题开发回放得到 8/8 条有效结构化输出；它不是新的盲测准确率。历史报价、成交、覆盖度和当前报价分开处理，尚无实时市场数据或买入建议。

[v8 新问题与 v5 路由](QUESTION_ROUTING_V8_DIAGNOSTIC.md)用 9 条来源核查后的新提问发现卖出时点、静态日英价差和选卡推荐的缺口。v5 把这些任务分开，并在已看过的 v8 问题上做开发回放；9/9 结构有效仅证明样本可处理，不代表新版本的盲测准确率或市场判断能力。

新[真实 listing 盲测协议和工具](BLIND_LISTING_BENCHMARK.md)现可冻结独立采样框、目录和 matcher，把标题预测与双人复核分离，并对卡片、印刷版本和评级分别计数。当前没有来自新授权来源的盲测样本，因此没有真实市场匹配精度结论。

[AI 优先复核](AI_FIRST_REVIEW.md)允许两家独立模型在同一商品及照片哈希上达成高置信一致后暂列可接受候选；分歧和证据不足升级给真人，另随机抽查 AI 一致通过项。当前只实现离线分流与抽查计数，尚未调用真实模型或放行真实 offer。

Buy&Ship 新 partner v1 文档确认商品 URL → resolve → 15 分钟有效的实时到手价 quote → order，但不提供 listing 搜索或目录。已加入仅用合成响应的 [URL 到报价预览](BUYSHIP_PARTNER_INTEGRATION.md)：按来源权限和精确卡片版本绑定当前报价，核对变体、URL、有效期与费用总和；不会创建订单。真实商城支持、付款和数据使用范围仍待对方确认。

合成报价现可在单独的 `partner_quote_store_allowed` 来源权限下导入现有到手价索引；后续 listing 观测变化会使旧报价退出推荐。真实来源的该权限默认关闭，避免将仅有 URL 报价能力误当作持续的市场价格 feed。

eBay 独立数据路径的[接口核查、生产准入和 100 个版本候选名单](EBAY_ACCESS_AND_PILOT.md)已准备。候选名单尚无经验证的 marketplace 查询词，不可当作可执行采集计划。Browse API 可技术性读取在售报价，但标准协议不足以授权本项目的跨平台价格指数与 Gemini 商品图像处理；这些用途需 eBay 另行书面确认。当前没有 eBay 凭据或生产授权，没有运行真实查询或价格采集。

跨区卡片关系现已有 [AI 图像复核与价格可比性分级](AI_CARD_REVIEW.md)：88 组候选中 48 组同画、39 组不同画、1 组待补证；同画候选可用于内部发现，仍按不同语言与印刷版本保留价格序列。
商品照片、独立 AI 复核与跨区到手挂牌价差的离线接入路径见 [商品级证据契约](OFFER_CONDITION_CONTRACT.md)。

卡片目录已独立扩展，数量与来源限制见 [CATALOG_COVERAGE.md](CATALOG_COVERAGE.md)。
M6 秘密编号卡的官方稀有度核对及独立修正版快照见 [CATALOG_M6_RARITY_AUDIT.md](CATALOG_M6_RARITY_AUDIT.md)。
新增[缺稀有度补证](CATALOG_MISSING_RARITY_AUDIT.md)：500 张官方页面核对中补齐 497 张，覆盖 13 个卡组；SV4a 347/190 已确认为 SAR，另 3 张人物限定词差异暂缓。[v6 泛品类卖出路由](QUESTION_ROUTING_V6.md)先确定卡片范围和售卖方式，再规划逐个可计价单元的成交、费用和关系证据；已知问题回放不是新的盲测准确率。
新版问题路由在未参与开发的真实提问上的小样本诊断见 [QUESTION_ROUTING_V9_DIAGNOSTIC.md](QUESTION_ROUTING_V9_DIAGNOSTIC.md)。
新增 [v10 新问题诊断](QUESTION_ROUTING_V10_DIAGNOSTIC.md)：16 个新来源候选中 15 个通过核查，日文 8、英文 7；15 条结构有效，14 条意图落在预先研究判断内，13 条有售卖方式预期的案例中 12 条一致。整套出售、商家收购规则、东京店铺推荐仍有具体路由缺口；这些数字不是问答准确率。
内部查询快照 `catalog-index.sqlite3` 可从种子重建，未提交到 GitHub；无实时市场报价。
**首批来源诊断（历史结果）：** 冻结 30 个新来源候选，16 个通过原帖检查及 Codex/Gemini 忠实度审核。首次执行 2/16；修复后为 8 个目录范围内的部分结果、8 个明确证据阻断，合计 16/16。当时未达到 30 个合格新问题的验收门槛；没有完整回答或真实交易准确率结论。当时测试 360 项通过，见 [诊断与下一步](COLLECTOR_SOURCE_DIAGNOSTIC_20261001.md)。

**最新实施：收藏库存比对与第二批诊断。** 新增内部 `POST /collector-inventory` 与同名 CLI，支持已声明卡片、待确认版本、重复数量及目录范围内的缺项比对；不保存库存，不验证实际持有或品相。第二批 30 个全新原帖问题（18 英文、12 日文）通过来源审核，首次执行 7/30，修正后为 8 个目录部分结果、22 个具体证据阻断；没有完整回答准确率结论。100 个合成持有记录通过 8 项演练检查，377 项工程测试通过。见 [实现、复现与下一步](COLLECTOR_INVENTORY_IMPLEMENTATION_20261001.md)。

**图像角色与印刷证据：** 取证扩大到 7 个日文系列的 100 张卡（新增 80 个目标），94 张通过图像身份／输出校验，6 张保留为未解决。追加账本有 190 条历史事件：13 条当前官方声明、142 条当前 AI 提议。新增铁骨土人和波普海豚的官方客串证据，支持日英提问及局部库存比对。10 张 Codex 抽样复核与 Gemini 重复检查保留分歧；新模型仍漏掉 3 个官方明确描述的客串角色，因此一致性不作为准确率，AI 不自动升级。391 项测试通过，见 [扩展与校准](COLLECTOR_EVIDENCE_EXPANSION_20261001.md)。

**多轮收藏探索：** 新增内部 `POST /collector-journey`，连接普通收藏问题、日英／卡组／卡号／版本短回复、库存澄清与目录目标选择。客户端保留最多 20 步操作，服务只读重放；未知库存阻止选择，AI 线索不能当作确认卡片，修改范围会撤销旧目标，评级／预算／目的地仅作为偏好。20 条开发路径首轮 56/59，修正后 59/59；407 项工程测试通过。可输出供 Pivota 编排使用的目录意图，真实 URL、报价和交易批准仍为空。见 [多轮实现与边界](COLLECTOR_JOURNEY_IMPLEMENTATION_20261001.md)。

**Pivota 调用准备与新场景：** 新增 Node 调用适配器及默认关闭的内部 `collector.explore` 包装器，支持服务身份、原始操作续接、版本变化后重新确认、限时／有限重试和无行情／购买批准的响应校验。8 个新公开来源场景首轮 26/37；修正意图路由后，原始预期 33/37；明确修订两处测试样本错误并加恢复步骤后，39/39 通过。412 项 Python、11 项 Node 测试通过，原有 59 步和 30 个问题集合保持一致。这是开发诊断，不是独立真人成功率；尚未注册到实际 Pivota 入口或授权其服务身份。见 [实现与验证](PIVOTA_COLLECTOR_ADAPTER_20261001.md)及 [接入指南](integrations/pivota/README.md)。

私有 Google Cloud staging 部署方式见 [CLOUD_RUN.md](CLOUD_RUN.md)；生产项目在部署脚本中被禁止。
2026-10-01 的私有 staging 提供目录及有限模式的收藏探索查询；认证接口核对通过，未登录请求返回 403。模型问题提取及路由验证仍通过 sandbox／CLI 运行；实时市场写入未启用。

第二步对 Buy&Ship 的接口与数据授权请求已整理在 [SOURCE_ACCESS_REQUEST.md](SOURCE_ACCESS_REQUEST.md)。
API 报价、商品身份和品相证据如何汇合，见 [OFFER_CONDITION_CONTRACT.md](OFFER_CONDITION_CONTRACT.md)。

## 已实现

- 卡片身份：`语言 + 系列代码 + 收藏编号 + 版本`；可计价单元再区分评级机构、分数和裸卡品相。
- 带来源权限的 JSONL 导入；观测保留原始标题、URL、状态、价格、时间和采集原因。自动匹配只接受明确的系列代码与编号，其他 listing 留在未解析队列；人工改判留痕。
- 三种严格分开的价格序列：`ask`（当日有效在售挂牌）、`last_list_at_transition`（交易状态变化前的最后挂牌）、`verified_paid`（有支付/结算凭据的成交）。没有凭据时成交序列为空。
- 当前到手价推荐是 `price_only`：只比较**相同可计价单元**、相同目的地和同一币种的未过期完整报价。价格组件由上游报价方提供；本项目不会猜测运费、税费或汇率。商品实际品相的证据评估与综合推荐尚未接通。
- 卖家库存重合度仅在来源明确允许 seller analytics 时计算；不生成可信卖家评分。
- 校准报告：从授权的卖家真值样本计算发现前售出覆盖率、Wilson 区间和漏掉/捕获 listing 的价格比。
- 来源级保留期限、listing 新鲜度、独立的价格统计许可和跨来源使用开关。默认不允许计算来源价格指数、跨来源混合展示或卖家画像；单条商品可展示不代表允许统计。
- 卡片目录逐条记录 `rights_reference` 和是否准许展示。旧数据库经 `init` 升级后，原有卡片默认不可展示，须重新导入并确认权利。
- Buy&Ship Mercari 旧网关响应适配器、至多三次只读请求的 Gate 0 探针，以及 Pivota 候选商品交接契约。它们未连接真实生产数据。
- 对要求照片复核的 API 来源，商品必须有两家独立 AI 对正反面、卡片身份、印刷工艺和裸卡品相的一致证据，才能把**单次商品快照**关联到可计价单元。后续商品快照重新锁定；普通人工改判入口不能绕过。eBay 默认强制此门槛，其来源权限目前仍全部关闭。
- TCGdex 日文卡组 JSON 的文本元数据适配器；不导入卡图、图片 URL、徽标或规则文本。
- 固定 TCGdex commit 的日文目录：16,347 条可区分版本元数据；第二来源另补 10,233 条单记录与 462 条多记录同名候选，保留 24,039 条参考记录；TCGdex 另有 50 条版本歧义候选。历史 Mercari 样本指出的 S6a 094/069、095/069 另增 2 条不可自动匹配候选。日文合计 27,094 条。
- 同一固定 commit 的英文实体卡目录覆盖 Base、Mega Evolution、Scarlet & Violet、Sword & Shield、Sun & Moon：79 个卡组、18,730 条可解析版本身份及 135 条版本歧义候选。另通过官方 TCGdex 卡组 API 冻结 126 个缺口卡组的清单，新增 9,208 条未核实印刷版本的卡组＋编号候选，4 个卡组清单为空。按语言隔离卡组元数据；Pokémon TCG Pocket 数字卡不在实体卡目录。扩展前的日英基线合计 **55,167 条内部身份、543 个有卡片的语言＋卡组组合**，公开展示批准数为 0。两组[官方编号分母冲突](CATALOG_COVERAGE.md)使 395 条卡暂缓精确报价匹配；加上先前 19 条身份例外，现有 **33,543 条保留自动匹配资格**。所有身份均无实时价格；API 候选和版本歧义卡禁止自动报价匹配。
- 内部目录命令可查卡名／卡组／卡号、同卡号的不同版本、来源和各卡组覆盖数量；该命令不对外提供 HTTP 路由，公开 API 仍遵守 `display_allowed`。
- 内部关系图可查询同卡组／编号的版本邻居；日英对应、相同画作和收藏替代项仅作为带证据的断言进入库，经过人工核实才可作事实性探索。状态改变以新断言记录，不覆盖旧证据。结构化探索 session 保存语言、卡组、预算等约束、shortlist 和最后选定的精确卡片；只有 `match_eligible` 的卡片可进入后续 offer 跟踪。当前有 AI 提出的跨语言同画面候选边，没有自动确认的日英对应边或真实用户 session。
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

当前日英目录为 70,005 条内部来源版本／未解家族记录，不等于 70,005 张已验证实体卡。本次补齐 15 个英文历史系列的 14,838 条版本记录，丰富 9,135 个已有编号组合，新增 26 个组合及角色／画师信息；新增记录全部禁止报价匹配和公开展示。详见 [目录扩展审计](CATALOG_COVERAGE.md)。现已完成 1,000 个日文编号的官方元数据补证：749 个有稀有度图标，251 个官网未标明；4 个多部件页面保留购买目标阻断，7 项画师冲突暂停参与检索。角色／画师检索覆盖为 40,662／45,493 条身份，共同署名可用于关联检索。Docker 使用 metadata-v1 的 39 项固定哈希清单；原始清单和重建测试保留。输出必须是新文件；构建核对 70,005 条记录、33,543 条原有结构匹配资格、532 条官方稀有度证据、19 条身份例外与 2 条编号冲突规则：

```bash
python3 -m scripts.build_catalog_snapshot --manifest catalog-build-manifest-metadata-v1.json --db catalog.sqlite3
python3 -m pokemon_index --db catalog.sqlite3 catalog-status
python3 -m pokemon_index --db catalog.sqlite3 catalog-search 'SV2a 025/165'
python3 -m pokemon_index --db catalog.sqlite3 catalog-search --dex-id 25 --limit 20
python3 -m pokemon_index --db catalog.sqlite3 catalog-search --illustrator 'Naoyo Kimura' --limit 20
python3 -m pokemon_index --db catalog.sqlite3 catalog-card 'ja:SV2A:025/165:reverse_masterball'
python3 -m pokemon_index --db catalog.sqlite3 catalog-search 'S6a 087/069'
python3 -m pokemon_index --db catalog.sqlite3 catalog-search --printing-type prism_star
python3 -m pokemon_index --db catalog.sqlite3 catalog-neighborhood 'ja:SV2A:025/165:normal'
```

当前部署构建清单包含 657 条标为 `proposed` 的 AI 同画面内部候选断言，已核实关系为 0；不包含市场商品或价格。当前部署清单亦包含 122 条已审核日英名称别名及 460 条审核记录；名称翻译不构成印刷版本等价。目录审核所用的编号别名和图片比较证据仍在独立数据文件中，可按对应审计文档另行导入到研究数据库。

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

审核关系可通过 `import-relationships <jsonl>` 导入。每条断言需有 `left_card_id`、`right_card_id`、`relation_type`、`review_status`、`evidence_ref`、`rights_reference`、`asserted_by`；`verified` 或 `rejected` 还需 `reviewer`。`verified` 必须带 `assertion_id` 和 `pokemon.relationship_review.v1` 结构化证据，明确双端卡片、独立证据、身份检查、来源快照、两位不同且判断一致的审核员与时间；该检查验证可追溯性，不能代替真实人员认证。每次状态改变使用新事件 ID，重试同一事件不会重复写入。支持的关系是 `localization_counterpart`、`same_artwork`、`collecting_alternative`。其中 counterpart 不代表两张卡可共用价格；被驳回的边不会用于跨语言发现。所有关系与探索候选仅供内部使用，不能绕过卡片公开展示许可。

日英关系首批人工审核包见 [RELATIONSHIP_PILOT.md](RELATIONSHIP_PILOT.md)，独立复核后的分阶段方案见 [RELATIONSHIP_GRAPH_PLAN.md](RELATIONSHIP_GRAPH_PLAN.md)：19 个日文锚点产生 40 个待复核候选，附可在表格中填写的审核模板。另有 [30 个独立盲审锚点及召回评估流程](RELATIONSHIP_COVERAGE.md)，完整角色集合检索及有上限的弱信号回退后，当前检索器对其中 17 个锚点返回 67 对候选；真人尚未标注正确答案，所以这不是召回率。角色／画师信号只用于召回候选；目前尚无真人核实的对应边。S6a 的一条补充身份因缺少角色和画师信息进入身份缺口清单。内部 `catalog-neighborhood` 现在把已审核关系与同角色／同画师的检索候选分开返回，后者不会变成价格等价关系。

[千组规模关系审计批次](RELATIONSHIP_SCALE_BATCH.md)现包含 1,000 对日英候选及 462 组日文同编号多记录候选。1,000 对的 1,734 份来源文件已按固定版本重新校验哈希；补图后，Gemini 视觉复核累计给出 657 对同画面候选、55 对不同画面、275 对图片不足、4 对不确定及 9 对模型失败。657 条同画面关系现由固定构建清单导入为 `proposed` 内部边，**0 条升级为 `verified`**，不允许合并价格序列或声称同一 SKU。462 组日文多记录的 967 张官方来源图片均完成原始哈希核查；后续稳定图片重试后，456 组取得 AI 画面对比，六组仍缺稳定图片。可见相同画面不等于相同闪卡工艺或印刷版本，因此尚未拆分物理版本或开放报价匹配。[编号、关系图与 agent 推荐架构](AGENTIC_GRAPH_ARCHITECTURE.md)说明了跨语言编号的作用域，以及后续价格和购物推荐需要的证据。

编号结构现独立保存在 `card_number_context`，保留原 `card_id`，记录语言＋卡组暂定编号范围、标准化分子／分母和源数据版本标签；地区、实体工艺、印章与版次在缺少证据时仍为空。`init` 会为旧目录补齐编号结构，新增卡片在导入时同步建立。内部 `number-explanation <左卡片ID> <右卡片ID>` 及受限 `/number-explanation` 查询会说明编号对齐方式、来源编号冲突和现有关系审核状态，不会根据相同编号自动建立日英对应或合并价格。完整目录副本已回填 55,167 条，缺失 0 条；51,301 条为纯数字分式、3,792 条为混合分式、74 条为代码分式。

[日文编号冲突恢复审计](catalog/ja-number-alias-audit.json)从两个已锁定来源重新校验文件哈希与来源清单：395 条受限卡片中，388 条按同卡组、相同分子编号和标准化卡名找到来源中的编号候选；其中 232 条对应多个来源记录，无法判定具体工艺／印刷版本。其余 7 条在当前来源快照里缺少该分子编号，列于 [待补证据清单](catalog/ja-number-alias-unresolved.jsonl)。这些仅是内部编号线索，保存在独立的 `card_number_alias_candidate` 表中；395 条仍不参与自动报价匹配、关系图验证或价格合并。先运行 `init`，再执行 `import-card-number-aliases catalog/ja-number-alias-candidates.jsonl`；`number-explanation` 与内部卡片详情会显示可追溯的候选编号及尚未核实的实体版本状态。

[多记录图像证据关联审计](catalog/ja-number-alias-visual-crosswalk-audit.json)把上述 232 条目录卡对应到 80 个官方同编号双记录组，并复用已有的来源哈希和 Gemini 图像复核：77 组／223 条目录卡仅得到“相同插画、可见表面差异待查”的信号，3 组／9 条图片不足。每个目录版本仍无法指定为其中哪条官方记录。执行 `import-card-number-alias-visuals catalog/ja-number-alias-visual-crosswalk.jsonl` 后，内部编号解释会显示组级视觉状态，但不会放开报价匹配或验证实体版本。

[SM10b 官网搜索缺口审计](catalog/ja-sm10b-official-search-gap-audit.json)记录了官方产品页所链接搜索结果的两页响应哈希：公开列表共 62 条，ID 与固定来源中的 62 条完全相同。其余 7 条高编号卡没有这份官方搜索记录；这不证明卡片不存在，也不能从同名基础卡推断它们的插画或具体工艺。后续需补独立的卡面编号证据，当前仍保持报价匹配禁用。

[SV11B 图像缺口恢复审计](catalog/ja-number-alias-visual-recovery-audit.json)针对原先图片不足的 3 个同编号组，重新独立抓取两轮、逐图核对稳定哈希，再由 Gemini 3.8 Flash 审核官方图片。3 组均得到“相同插画、可见表面图案差异”候选结论，投影到 9 条目录版本。导入命令为 `import-card-number-alias-visual-recoveries catalog/ja-number-alias-visual-recovery.jsonl`；旧的图片不足记录保留，新增结果独立存储。80 个组现均有视觉候选，但仍没有一组完成实体工艺／版本对应确认，也没有恢复报价匹配。

[SV11B 扫描图候选对应审计](catalog/ja-sv11b-scan-candidates-audit.json)逐条把官网记录 ID 与其文件哈希重新绑定。旧交叉表把哈希作为无序集合存储，37/80 组的数组顺序与官网记录 ID 顺序相反；旧证据保留，新的 `card_number_alias_scan_candidate` 表记录有序的 ID／哈希对。Gemini 在 80 组的第二张官网扫描图上均观察到精灵球图案；结合 TCGdex 的版本标签，得到 80 条 `reverse_pokeball` 与第二张、70 条 `normal` 与对照图的**候选**对应。72 条 `reverse_masterball` 和 10 条 `holo` 仍未分配。先执行 `init`，再执行 `import-card-number-alias-scan-candidates catalog/ja-sv11b-scan-candidates.jsonl`；内部卡片详情显示扫描图候选。图像呈现不证明实体闪卡工艺或品相，232 条卡片仍不参与自动报价匹配或价格合并。

[全部日文同编号多记录扫描证据](catalog/ja-multi-record-scan-evidence-audit.json)把已完成的官网图像复核扩到 31 个卡组、462 个目录组和 967 条逐张绑定的官网记录。459 组有 Gemini 同画面比较，276 组至少一条比较指出可见表面或印章差异；另有 183 组未指出这种差异，3 组仍缺可用图像。执行 `init` 后，可通过 `import-card-multi-record-scans catalog/ja-multi-record-scan-evidence.jsonl` 导入；内部 `catalog-card` 的 `number_context.multi_record_scan_evidence` 返回官网记录、比较结论及原始可见理由。这一层保留旧图像结果和 3 组恢复结果的来源快照，不给未明版本强行指定工艺，也不开放报价匹配或跨版本价格合并。

[SM10b 商家目录编号审计](catalog/ja-sm10b-secondary-number-audit.json)对官方列表未收录的 7 条卡，逐张在晴れる屋2和 Fullcomp 两个独立商家目录中核对卡名、卡组、HR／UR 与 `063/054`–`069/054` 编号，保存网页响应哈希。导入 `import-card-number-secondary-candidates catalog/ja-sm10b-secondary-number-candidates.jsonl` 后，内部编号解释会把它们显示为较弱的商家目录候选。它们仍缺官方逐卡记录及独立卡面核验，不构成实体版本确认；7 条报价自动匹配仍禁用。

[跨区画面对比盲复核](RELATIONSHIP_CALIBRATION.md)覆盖 212 对来源绑定图片：可比较样本中首轮同画面 149/149 重复同判、首轮不同画面 47/50 重复同判；这仅衡量同模型换提示后的稳定性，不是准确率。定向配色核对将五对原先笼统的“不同画面”列为“同构图但重配色”候选；[新版比较范围](catalog/relationship-scale-v1-comparability-v2-audit.json)仍禁止任何跨卡价格序列合并。图片哈希未能恢复的十对继续隔离。

由候选检索走向生产可用关系图的数据与验证门槛见 [RELATIONSHIP_PRODUCTION_PATH.md](RELATIONSHIP_PRODUCTION_PATH.md)。

新增的来源可追溯卡片类别与日英概念别名检索契约见 [BILINGUAL_CONCEPT_CONTRACT.md](BILINGUAL_CONCEPT_CONTRACT.md)。已从固定 TCGdex 源码提取 35,073 张卡的类别；v2–v6 累计 122 条供内部检索的日英名称别名、460 条可追溯的 AI 审核事件、122 条明确标为 `proposed` 的卡片候选边。v6 采用[逐名分阶段复核](CONCEPT_REVIEW_STAGED.md)，由 Astra、Sol 和通过 Vertex AI 调用的 Gemini 3.8 Flash 独立审核，Gemini 在可获取时同时查看卡片图片。原始排序包的 55 组审核获得 20 个名称概念；[后续来源补救](CONCEPT_GAP_RESCUE_V6.md)从相同的固定数据中找回其余 5 个名称并完成三方复核。25 个名称锚点的完整工作池有 88 组待复核卡片关系候选；新版首轮每个锚点取一组，Gemini 对其中 12 组给出双端图片支持的同插画线索，13 组缺少完整图片。名称别名和关系候选没有已验证印刷关系或召回率结论；这些候选不能用于认定两个地区的卡片为同一价格商品。

目前使用 [v2 人工复核包](CONCEPT_REVIEW_V2.md)：独立于盲审集的 22 个日文名称、39 条双端固定源码提案。初版 36 条记录仍保留在 [v1 档案](CONCEPT_REVIEW_GUIDE.md)。v2 CSV 尚无任何批准；编译保留全部审核理由和额外证据，审核包导入不会放开卡片的报价匹配资格。

示例数据完全是合成数据，包括价格、支付凭据和到手价；URL 使用 `.invalid` 域名。`--as-of` 用于重放旧样本，实时 API 默认使用当前时间和来源设置的新鲜度上限。

启动只读 JSON API：

```bash
python3 -m pokemon_index --db demo.sqlite3 serve --port 8765
```

端点：`/health`、`/discover?q=...`、`/discovery?q=...`、`/units?card_id=...`、`/offers?card_id=...&destination=...&as_of=...`、`/recommend?unit_id=...&destination=...&as_of=...`、`/index?unit_id=...&date=YYYY-MM-DD`、`/seller-overlap?source=...&unit_ids=...`。带 `--internal-catalog-api` 时另有 `/catalog-neighborhood?card_id=...`、`/buyer-question-plan?question_type=...&card_id=...` 和 `/listing-candidates?title=...`；后者只返回照片审核候选，绝不自动匹配报价。探索 session 的读写暂不开放 HTTP。`/discovery` 仅做保守的规则化意图解析，无法确定时弃答；没有接入 LLM。服务默认只绑定 `127.0.0.1`，没有用户认证，不能直接公开部署。

## 输入契约

所有文件为 UTF-8 JSONL，每行一个对象。`examples/` 是完整样例。

| 文件 | 关键字段 |
| --- | --- |
| Source policy | `source`, `rights_reference`, `ingest_allowed`, `display_allowed`, `price_statistics_allowed`, `cross_source_use_allowed`, `seller_analytics_allowed`, `media_ai_allowed`, `cross_region_use_allowed`, `retention_days`, `listing_ttl_hours`, 可选 `expires_at` |
| Card | `language`, `set_code`, `collector_number`, `name`, `provenance`, `rights_reference`, `display_allowed`；可选 `variant`, `rarity`, `match_eligible`, `attributes`。未明确允许展示时填 `false`；版本未经核实时 `match_eligible=false` |
| Set metadata | `set_code`, `official_card_count`, `provenance`, `rights_reference`；可选 `name_ja`, `release_date_ja`, `display_allowed` |
| Card reference | `source`, `source_jp_id`, `name`, `provenance`, `rights_reference`；可选 `set_code`, `collector_number`, `rarity`, `attributes`, `display_allowed`；仅供内部查证，不进入自动匹配 |
| Observation | `source`, `native_id`, `title`, `url`, `observed_at`, `status`, `currency`, `evidence_ref`；可选 `price_minor`, `language`, `variant`, `card_id`, `condition_bucket`, `seller_native_id`, `poll_reason` |
| Landed quote | `source`, `native_id`, `destination`, `currency`, `components`, `quoted_at`, `expires_at`, `evidence_ref`；可选 `assumptions` |
| Offer media | `source`, `native_id`, `observed_at`, `front_ref`, `front_sha256`, `rights_reference`；可选 `back_ref`, `back_sha256` |
| Visual review | `review_id`, 商品观测键, `card_id`, `model_family`, 图片哈希, 身份／工艺／品相判断, `evidence_ref` |
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

若 Buy&Ship 授权图片 AI 用途，`adapt-mercari-photo-candidates` 可把详情响应中的未标注 `photos[]` 留为顺序候选，不猜哪张是背面。获授权的临时照片文件可交给 `scripts.vertex_offer_photo_sides` 自动识别正反面并输出哈希绑定的媒体与复核清单；随后运行 [`OFFER_CONDITION_CONTRACT.md`](OFFER_CONDITION_CONTRACT.md) 中的视觉双审和跨区比较。商品照片不会写入仓库。内部接口 `/cross-region-compare?ja_card_id=...&en_card_id=...&destination=...` 只在 `--internal-catalog-api` 下开放。真实卡片展示授权尚未确认，因此现阶段真实目录仍保持隐藏；合成样本仅用于验证流程。

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

下一步按 [当前实施顺序](BUILD_SEQUENCE.md)补收藏探索所需的图像角色、印刷版本及跨区证据，并把无状态库存比对接入受控 agent 流程；100 个来源绑定元数据目标、卡组检索与别名部署已完成，实际工艺仍待验证。与此同时接入一条有明确数据使用权的真实报价来源，运行持续观测并发布带样本数与新鲜度的 ask index；再用 Buy&Ship 报价组成到手价及商家建议。Buy&Ship 网关文档与授权到位后验证当前适配器；Pivota 的 `content_key` 映射及 Buy&Ship 购买交接仍须由双方接口负责人确认。当前尚无实时渠道覆盖或实际成交价指数。

新增 [卖家问题路由 v7](QUESTION_ROUTING_V7.md)：保留整套出售、商家收购规则、城市店铺发现、多商家与混合卡牌范围；净收益证据按成交、费用、运费及收购报价分别规划。已见 v10 样本用于回归，新问题泛化需要另一次冻结验证。

新增 [v11 未见问题诊断](QUESTION_ROUTING_V11_DIAGNOSTIC.md)：当前 v7 在收集前冻结，16 个新来源通过 AI 来源核查；首轮 14 条抽取有效、13 条意图符合预期，2 条失败保留。单独重试定位买入再出售的角色冲突、盈利任务漏保留，以及进化链清单/组牌查询缺口；不合并为准确率。

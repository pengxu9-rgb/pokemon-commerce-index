# API 报价、商品关联与品相辅助评估契约

## 数据流

`获授权的渠道 API → 原始响应及采集批次 → 商品观测 → 卡片／版本关联 → 当前可买报价 → 到手价 → 品相证据 → 购买建议`

目录可独立增长。实时价格只能来自渠道或 Buy&Ship 提供且允许该用途的 API；卡片目录 API 的静态数据不能充当实时市场价格。每个渠道单独配置获取、保存、展示、跨渠道比较、卖家分析、图片处理和 AI 处理权限。

## 每次商品 API 观测必须保留

| 字段 | 用途 |
| --- | --- |
| `source`, `native_id`, `seller_native_id`, `url` | 稳定商品与卖家身份；URL 供人工核验 |
| `observed_at`, `native_created`, `native_updated`, `status` | 判断报价新鲜度、状态变化和撤单 |
| `title`, `description`, `currency`, `price_minor` | 身份证据与在售价；币种和含税语义由 API 合同确定 |
| `shipping_payer`, `domestic_shipping`, `location` | 到手价所需的日本境内段 |
| `raw_sha256`, `api_endpoint`, `request_id`, `pull_run_id` | 复核、去重、重放和配额审计 |
| `media_refs`, `media_updated_at`, `media_rights` | 仅在许可范围内作版本和品相判断；不默认复制原图 |

采集器必须保留分页游标、返回数、重复数、限流和失败状态。周期抓取按 API 配额与 listing 热度调度，商品详情用于确认价格、版本和状态；过期报价不得进入推荐。只有明确的支付或结算证据才能写入 `verified_paid`，售出状态只代表状态变化。

## 商品关联

先解析语言、卡组代码、收藏编号、卡名、版本／闪卡工艺、评级机构和分数、单卡或多卡打包。解析结果应带规则或模型版本、证据字段、置信度及人工改判记录。

- **可自动关联**：版本和编号无冲突，且目标目录身份 `match_eligible=true`。
- **待核验**：同编号多个工艺、卡组代码不明、语言冲突、疑似仿卡、打包或目录仅有 `unverified_*` 身份。保留商品供人工复核，不进入单卡价格或购买建议。
- **不可比较**：评级卡与裸卡、不同工艺、不同语言，或品相类别缺失时，不合并成一个价格样本。

推荐必须指向具体仍在售的 `source + native_id`，并附目录卡片 ID、可计价单元、采集时间、商品 URL 和报价证据。商家库存重合只在来源许可卖家分析时计算。

## 到手价与推荐

到手价由 item、境内运费、转运服务费、国际段、税费、保险和汇率差组成；未知项保留为未知，不能填零。按同一可计价单元和目的地比较未过期的完整报价。推荐输出至少说明商品来源、总价和币种、报价有效期、身份匹配依据、卖家库存重合、品相证据状态。

当前代码的 `recommendation_type=price_only` 只表示同一可计价单元的最低完整到手价，**不是**品相或商家履约综合评分。后续只有满足以下条件才升级为购买建议：商品身份已确认；所有到手价组成有依据；商品仍在售；正反面或其他必要证据足以判断品相；图片及派生判断获准用于此目的。任一条件不满足时，返回报价列表和缺失原因，不产生综合推荐。

## 品相辅助评估

品相判断以具体商品观测为单位，不能把同一卡片 SKU 的一般状况套到某个在售商品。保存来源商品 ID、对应观测时间、证据哈希、可用视角、评估方法／版本、评估时间、分项结论、置信度和复核状态。分项至少包括居中、角、边、表面、折痕／压痕、污渍与照片质量；缺失视角单独记录。

机器评估输出候选品相范围和可见瑕疵，人工可确认或驳回。没有足够图片、图片不清晰或商品描述与图片矛盾时返回 `insufficient_evidence`。原图存储、外部模型调用和派生标签的保留期限分别受来源许可约束。辅助评估不宣称 PSA／BGS 等机构分数，也不替代实物检验或真伪鉴定。

## 已搭建的 AI 优先商品级比对

`source_policy` 新增 `media_ai_allowed` 和 `cross_region_use_allowed`，默认均关闭。授权后按顺序导入 `observation`、`offer_media_snapshot`、`landed_quote` 和 `offer_visual_review`。媒体表仅保存正反面 HTTPS 引用及 SHA-256，不保存图片字节；每条模型判断绑定商品、观测时间、目录卡片、图片哈希、模型家族及证据引用。旧报价同一时间戳不可被覆盖。

已有 `scripts/vertex_offer_visual_review.py` 可从获准的临时本地图片文件生成 Gemini 第一份判断；第二份由独立模型家族按同一 JSONL 契约导入。两个家族对卡号／语言／版本工艺和裸卡品相一致，且有正反面照片，商品才进入比较。缺图自动请求补证；模型冲突进入例外复核；只有一个模型时等待第二模型，不需要逐条真人常规标注。受限于图片本身，系统不推断评级机构分数或真伪。

旧 Mercari 网关的 `photos[]` 无正反面标签。`adapt-mercari-photo-candidates` 先保留原始顺序；在图片使用权到位、获授权下载到临时目录后，`scripts.vertex_offer_photo_sides` 以 Gemini 判定正反面，输出 `media.jsonl`、`review-manifest.jsonl` 和带候选图哈希与模型响应哈希的 `side-audit.jsonl`。无法确定正面则不生成媒体记录；无法确定背面则品相门槛不会放行。图片字节仍只在临时目录与模型请求中，必须按来源授权清理。需要独立第二模型结果，当前仓库尚无第二模型调用器。

`compare-cross-region` 比较日英同画候选下的**当前商品级到手挂牌价**。两边必须有仍有效且与当前挂牌价绑定的完整到手报价；报价假设须给出来源币种／价格、汇率依据、费率版本和税费依据。只有照片核实后的工艺与品相一致，且两个来源都允许跨区用途及必要的跨来源用途，才输出同一目的地币种的最优报价差、分桶中位数差、样本数和证据引用。结果只称 `contextual_landed_ask_spread`，日英价格序列保持分开，不能称成交价、同 SKU 价格或套利收益。

试跑命令：

```bash
python3 -m pokemon_index --db index.sqlite3 import-observations observations.jsonl
python3 -m scripts.vertex_offer_photo_sides --db index.sqlite3 \
  --manifest authorized-photo-candidates.jsonl --media-output media.jsonl \
  --review-output authorized-local-photos.jsonl --audit-output side-audit.jsonl
python3 -m pokemon_index --db index.sqlite3 import-offer-media media.jsonl
python3 -m pokemon_index --db index.sqlite3 import-quotes landed-quotes.jsonl
GOOGLE_CLOUD_PROJECT=pivota-prod python3 -m scripts.vertex_offer_visual_review \
  --db index.sqlite3 --manifest authorized-local-photos.jsonl \
  --output gemini-offer-reviews.jsonl
python3 -m pokemon_index --db index.sqlite3 import-visual-reviews gemini-offer-reviews.jsonl
python3 -m pokemon_index --db index.sqlite3 import-visual-reviews independent-model-reviews.jsonl
python3 -m pokemon_index --db index.sqlite3 compare-cross-region \
  ja:SET:001/100:normal en:SET:001/100:normal HK
```

只有取得 API、图片使用权、跨区比较权、完整费用报价及第二模型结果后，真实商品才会越过这些门槛；当前合成数据已覆盖可比、缺证、冲突、权限撤回和改价失效路径。

## 上线顺序与验收

1. 取得至少一条渠道 API 的书面数据用途范围、测试凭据、配额和脱敏响应；完成只读探针。
2. 接入可重放的原始响应和追加式商品观测，连续运行并核对去重、分页、限流及过期删除。
3. 对与真实供给量相关的高频卡做盲标，分别测卡片、版本、评级和打包识别精度；自动接纳只用于通过复核的类别。
4. 发布带来源、样本数和时间的 `ask` 指数；完整费用报价到位后输出 `price_only` 到手价比较。
5. 在图片处理权限和实物品相标签到位后评估品相辅助模型，先离线比对人工复核，再启用带证据的综合购买建议。

Buy&Ship 的商品 API、运费报价和履约数据尚未接通；当前没有可发布的实时价格、实际品相结论或商家综合推荐。

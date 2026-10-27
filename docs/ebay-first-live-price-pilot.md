# 第一条真实 eBay 挂牌价：准备与验收

Prepared: 2026-10-27. 当前：**账号未配置，尚未调用 live API，尚未部署**。

## 先完成的账号步骤

1. 在 [eBay Developer 注册页](https://developer.ebay.com/signin?tab=register)注册开发者账号。用户亲自处理新密码、验证码、邮件验证和 API License Agreement；不要把密码、Client Secret 或 token 发到聊天。开发者账号与普通 eBay 账号不同。
2. 获准后进入 [Application Keys](https://developer.ebay.com/my/keys)，建立 Production keyset。App ID 对应 `EBAY_CLIENT_ID`，Cert ID 对应 `EBAY_CLIENT_SECRET`；只配置在获准的服务端密钥存储中。
3. 按后台要求完成 [Marketplace account deletion](https://developer.ebay.com/develop/guides/sell/marketplace-user-account-deletion) 配置。普通 Browse `search` / 单条详情不应统一加上 EPN 或受限 API 审批门槛；EPN 可后补。参见 [官方问卷](https://partnernetwork.ebay.com/page/developer-questionnaire)和 [Developer Support 说明](https://community.ebay.com/forum/browse-57957/topic/browse-api-468324/)。账号与 keyset 的实际状态仍需核对。

无数据留存豁免的含义是**不持久化任何 eBay 数据**，并非只不保留个人信息或价格历史。live JSON、HTML、截图、行情摘要及派生标识都不能被随意当作“没有留存”。按真实处理方式申报；本文件不代替用户作出豁免声明。

## 两条运行路径

**首个纯内存 pilot**：`pokemon_index.ebay_price_pilot` 先检索最多五条固定价商品，再逐条读取同一 canonical URL 的详情。一个进程最多预留七次 HTTP 请求：一个 token、一次搜索、最多五次详情。只访问正式 eBay API；不回退到抓取，不重试，不调用 PSA/BNS。最多十五分钟的绝对截止时间必须明确提供。报告只返回给进程内调用方，CLI 不打印价格、商品 URL、商品 ID、卖家或完整结果；退出后不写报价文件。默认执行只做 plan，不发请求。

**聊天中的托管路径**：`cloud/commerce-sidecar.cjs` 已补齐有限时间/次数的配置桥，但保持关闭。现有 `commerceHistory` 会把商品/报价的摘要、数量和指纹保存在 GCS，所以这条路径不能宣称纯内存。启用前必须核对真实删除通知合规及留存权限，并由操作者设置 `EBAY_PERSISTENT_DATA_APPROVED=true`；这个开关本身不代表平台已批准、也不代表删除 webhook 已实现。账号未就绪时不会启用。

CLI 只输出操作结果和预算遥测；结果状态仍可能由响应计算而来，因此不能声称它完全没有派生信息，也不能凭这个 helper 自动判断豁免资格。

纯内存 pilot 通过，只证明 API→商品证据→现有 research DTO 的接线；**不等于已经完成浏览器聊天中的 live 验收**。后者还需合适的留存模式、当前有效的独立私有测试配置和真实 UI 检查。此前已到期的 staging 窗口不能复用。

## 首次 live 的具体验收

- 选一个明确的卡牌目标和查询，先做五条；不从查询文字推断商品必然与目标匹配。
- 逐条保留 eBay 原商品 URL、原币 USD 要价、查询时间、在售证据与卖家等级声明。变体摘要、拍卖、结束商品、冲突身份或不能精确表示的价格不冒充有效报价。
- 有价格但不能证实库存时显示未知；没有显式等级时显示未报告。PSA 卖家声明、证书记录和实物真伪是不同层级，首轮不做证书验证。
- 聊天中的 eBay 内容独立展示；不计算跨平台价格赢家、历史行情或估值，不把商品数据送入外部模型。商品价不包含国际运费、税和代购费。
- EPN 未配置时使用原商品链接。EPN 后续配置后，tracking URL 仍必须属于同一商品；BNS 交接始终保留 canonical URL。
- 记录测试是否通过及请求预算使用情况，不在纯内存试点里另存 live 报价或截图。需要保存这些证据时，先解决相应的数据留存配置。

Release pins 保持原值；当前不执行 live、合并、部署、下单或支付。后续真实试跑不能把离线 fixtures 当作 live 成功证据。

## 2026-10-27 离线结果

- 后端受影响回归 118 项通过；前端配置、进程隔离和打包回归 40 项通过，运行器阻止外网连接。
- 五条合成商品实际经过 Python memory pilot，返回对象经 stdin 交给当前前端 contract 校验，通过；未把响应写成报价文件。合成数据始终标记为 synthetic，不是 live 成功证据。
- 独立审查确认并修复了两项问题：GCS 聊天的实际留存需要单独门槛，eBay 密钥不能继承到 Next 进程。修复后复审通过。
- 38 个受保护后端文件及冻结 BNS transport 与既有基准一致。

安全的默认准备命令（不发请求）：

```sh
python3 -m pokemon_index.ebay_price_pilot
```

后续执行需要 Production keyset 就绪、服务端配置完成，以及明确的 `--execute`、目标卡牌、查询和将来的 UTC 截止时间。当前没有创建任何新测试窗口。

## 2026-10-27 本机浏览器验收

已在实际 Next shopper 页面完成离线浏览器检查，手机视口为 390×844，桌面视口为 1280×900。认证、会话 API 和 eBay 传输由测试 harness 注入；这不验证真实 Google 登录、正式 Next API 部署或实时市场数据。

- 五条合成要价为 USD 25、28、31、34、37；选择第二条后显示相同商品的只读 canonical URL 和已知测试卖家 ID。
- 刷新后合成要价分别上涨 USD 1，旧选择清除；使用真实时钟的十秒有效期自然到期后，五条选择按钮全部禁用。
- 修复手机过滤器裁切、无可用 provider 时的空白控件和已知卖家被误标为未报告。合成商品不会提供外链、远程图片或证书查询入口；正常 quote/manual-forwarder 分支保留回归覆盖。
- 本次 43 项针对测试、TypeScript 和独立复审通过。浏览器无 warn/error，记录的外部连接、BNS、PSA、订单与支付计数均为零。
- 服务已主动停止，未创建或复用云端窗口。真实报价仍等待开发者账号、Production keyset 和适用的数据留存配置。

本机证据目录：`outputs/ebay-offline-browser-20261027T065421Z`（相对本 chat 工作区）。截图及 URL/价格都是明确标记的合成测试数据，不能作为 live 成功证据。前端运行方法见 `creator/tests/OFFLINE_BROWSER.md`。

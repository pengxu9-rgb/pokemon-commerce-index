# 旧 Mercari 照片数组试跑口径

旧 demo 的历史 HTTP cassette 有 467 个去重 Mercari 商品，均含 `photos[]`，418 个至少有两张照片。它们是 2026 年 4 月左右的历史在售快照，不是当前库存、当前报价或图片使用许可。`photos[]` 没有正反面标签，且多张图可能都是正面、包装、组合照或评级盒。仓库只提交聚合审计，不提交原始商品、照片地址或图片字节。

现有确定性标题解析在这批样本中自动接纳 105 个、弃权 362 个；接纳组有 99 个带至少两张照片，弃权组有 319 个带至少两张照片，其中 83 个标题指向组合装。这些是**试测候选数量**，不是照片可用率或匹配准确率。卡名与卡组／编号必须一致；例如标题缺少“X”的「メガリザードンex」不能自动当作「メガリザードンXex」。

## 可以立即重放的部分

在持有旧 demo 本地副本的环境里，使用
`scripts.audit_legacy_mercari_coverage` 对录制响应做只读目录覆盖审计。脚本去重商品 ID，计算照片数组覆盖、标题里明确的卡组／卡号覆盖，并单列简称与歧义。不会导入历史挂牌价或触发图片请求。当前结果见 [目录覆盖审计](catalog/legacy-mercari-fixture-coverage-after-s6a.json)。

```bash
python3 -m scripts.audit_legacy_mercari_coverage \
  --db catalog-index.sqlite3 \
  --cassettes /path/to/shopping-agent-demo/backend/flow_tests \
  --output /tmp/legacy-mercari-coverage.json
```

## 获得 Buy&Ship 授权后的照片 AI 测试

1. Buy&Ship 明确许可这些**历史录制响应中的照片地址**用于内部下载、送 Vertex AI 分析、保存哈希和派生判断，并给出保留期。网关测试凭据、配额与新接口文档也要到位；旧录制不证明当前接口可用。
2. 从可访问的授权商品中分层取样：确定性接纳的两图样本、弃权的两图样本、组合装、评级盒、低清照片和图文冲突。先核对图片仍对应录制观测；失效链接只作失效统计。历史样本无需仍在售即可测试识别，但不得用于当前报价或转化率评估；实时报价测试另需当时的在售状态。
3. `adapt-mercari-photo-candidates` 保留未标注图片顺序。授权下载器将图片临时保存并计算 SHA-256；`scripts.vertex_offer_photo_sides` 识别正反面并弃权不确定视角；`scripts.vertex_offer_visual_review` 核对卡名／卡号／语言／工艺及可见品相。第二个独立模型家族按同一照片哈希复核。
4. 分别报告卡片身份、印刷版本、正反面识别和品相分桶的覆盖率、弃权率、模型冲突率与人工抽样误差。只有两模型一致且证据充足的商品进入报价比较；历史挂牌价仍不参与实时指数。

当前没有 Buy&Ship 测试密钥或图片 AI 使用许可，故尚未运行真实商品照片的模型测试。S6a 094/069、095/069 虽已入内部目录，仍保持 `match_eligible=false`、`display_allowed=false`，待图片及印刷工艺核验。

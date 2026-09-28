# 真人复核在哪里进行

当前电脑上运行的本地入口：**http://127.0.0.1:8766/**。它只监听 `127.0.0.1`，其他电脑无法直接访问。队列包含 68 条旧 demo 样本，其中 54 条带测试记录里的图片链接；链接可能失效，另 14 条没有图片链接。看不到可判定的卡面时，版本必须选“无法确认”。

## 人员与操作

由 Pivota / Buy&Ship 指定两位熟悉日文 Pokémon 卡组、卡号和反闪工艺的真人审核员，再指定一位处理分歧的人。两位审核员分别用自己的 ID 选择“独立审核”，工作台不展示 AI 草稿或匹配器答案。完成双审后，第三人切换“第三人裁决”，只处理分歧项。审核员 ID 只是记录标识，本地版本没有身份认证；项目负责人需核实确实由不同真人操作。

每条样本看商品标题、描述和卡面图片，并填写是否单卡、语言、卡组、卡号、精确版本代码、评级状态（未知／裸卡／评级）、评级机构与分数及证据说明。打开外部 listing 和图片链接会向对应平台发出正常浏览请求；只在数据使用权允许内部复核时使用。图片缺失或看不清时，只标注可从文字确认的字段，版本与评级状态保持未知。工作台拒绝在未确认看过商品图片并说明证据的情况下提交具体版本或已知评级状态。新盲测样本的完整准备和评估步骤见 [盲测协议](../BLIND_LISTING_BENCHMARK.md)。

## 启动与导出

以下命令从 `outputs/pokemon-commerce-index` 目录运行。队列、原始标题、图片链接和真人判断都留在上级工作区的 `work/review/`，不进入交付 ZIP。

```bash
python3 -m scripts.review_workbench serve \
  --queue ../../work/review/queue.jsonl \
  --db ../../work/review/reviews.sqlite3 --port 8766

python3 -m scripts.review_workbench export \
  --queue ../../work/review/queue.jsonl \
  --db ../../work/review/reviews.sqlite3 \
  --output ../../work/review/human_gold_v1.jsonl

python3 -m scripts.evaluate_label_draft \
  --labels ../../work/review/human_gold_v1.jsonl \
  --catalog catalog/ja-selected-modern.jsonl \
  --summary ../../work/review/human_eval_v1.json
```

`export` 只输出已获两人一致、或已由第三人裁决的样本；未完成项留待复核。导出文件不可覆盖，避免无意改写冻结标签。对新授权 listing，使用 `scripts.blind_listing_eval prepare` 从独立采样框生成队列；预测文件不得交给审核员。旧 `evaluate_label_draft` 仍仅供草稿诊断，不可用于盲测精度。需要多人异地同时工作时，应先增加内部身份认证、HTTPS、访问控制和数据使用授权，再部署到内网；本地入口不应直接暴露到公网。

# 独立留出规则基线 v2

同一 27 个快照，沿用规则 v1 源码和固定的 12 查询预算。故障 Top-1、Top-3 均为 0/18，控制组达标 6/9，来源不可用失败 3/27。324 次离线快照读取，模型和在线工具调用为零。该规则只做保守移交。

复现入口为 `python -m evaluation.run_rules_snapshots --dataset evaluation/datasets/real-v2 --protocol evaluation/real_protocol/rules-v2/plan.json --output <new-directory>`。用评估端标签计算分数。[评分记录](run-001/score.json)

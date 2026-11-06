# 注册工作流真实组合测评 v1

实际 DeepSeek、本地 Compose 遥测、隔离 PostgreSQL 注册表/证据/追踪/报告/队列及官方检查点，三个场景各一次：正常、HTTP500、部署相关内存泄漏。合成注册预检单独计 3 次调用；实际场景调用 8 次，总计 11 次。

正常场景转人工移交；两个故障场景均通过结构性证据门禁，但修复模型输出发生根级 value_error，被严格 schema 拒绝。待审批为 0，审批决定及恢复执行为 0。门禁 PASS 只代表已解析证据满足确定性规则，不能证明语义根因正确；内存泄漏场景候选是延迟问题，不能据此宣称诊断了内存泄漏。

两次故障清理退出码均为 0，所有结束 checkout 为 200。清理属于评测设施，不是产品恢复。SQL Job 的 COMPLETED 指调查任务完成，不代表事件恢复；三个事件均为 NEEDS_HUMAN。

原始文件哈希见 run-001/file-hashes.json，实际运行源码哈希见 metadata.json。未保存两个无效提案的完整原文，仅保留响应哈希和 schema 错误位置/类型。临时数据库导出了事件、队列、模型追踪和审批状态；本轮未导出完整 SQL 诊断报告/门禁快照，不能补造。Evidence/Artifact 文件保留。这是组合联调，不是三组公平准确率对照；本机其他 Docker 负载未控制，不做提效或容量主张，实际账单未知。

复现：设置 DEEPSEEK_API_KEY 后运行 `python -m evaluation.run_registered_live --output-dir artifacts/registered-new`。目录须不存在，需要 Docker 和本地 AgentOps 遥测栈；最多 18 次调用，不批准、不执行恢复。故障标签只留在外层注入记录，不传给模型。

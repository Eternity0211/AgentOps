# PostgreSQL 续跑验证 v1

11 项真实 PostgreSQL 集成测试通过，其中 8 项注册提示词/SQL 追踪/证据/任务租约/官方检查点组合测试通过，含 7 个工作进程替换边界。每个成功组合场景以测试断言核对模型总调用 2 次、工具总调用 2 次；替换不追加调用。

七个中断点：诊断前、门禁前、计划后工具派发前、工具完成后证据创建前，以及 PLAN、Evidence、DIAGNOSE 各自完成但图转移未提交时。独立案例验证并发、输入/身份/租户变更、缺失事件、结果未知、敏感值拒绝及重算缓存哈希后的篡改检测。失败的 Evidence 外键插入也保留为预期拒绝案例。

数据库、检查点和队列为实际运行；模型及工具响应均是受控替身，不属于真实 DeepSeek 质量测评。这里不包含人工审批、恢复执行、工时收益或生产可用性数据。部分并行完成后的中断、重规划替换及生产启动接线仍未验收。结果未知的调用不自动重发，不能据此宣称任意崩溃都能成功续跑或外部效果恰好执行一次。

`run-001/test-results.json` 从通过的 JUnit 记录提取，移除了机器名；时长包含测试与环境开销，不是事件诊断耗时。`source-hashes.json` 记录本次源码，随同当前提交版本保存；`file-hashes.json` 绑定归档文件。归档提交的父版本见 summary，源码以本次记录的哈希为准。

复现：在本报告所在提交运行 `python -m pytest tests/integration/test_persistence.py -k "autonomous_gate_uses_committed_postgres_evidence or durable_investigation_effects" --no-cov`，需要 Docker。

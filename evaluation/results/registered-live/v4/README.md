# 注册工作流真实组合测评 v4

基于 8fc5c95，trace 短 ID 兼容修复后，三场共 10 次实际模型调用（含 3 次独立合成注册预检）。正常场景 HUMAN_HANDOFF；HTTP500 在实际 Gate PASS 后因缺少部署证据，触发确定性回滚角色拒绝；内存泄漏以 InvalidDomainValueError 结束。全部失败保留，不宣称根因准确或恢复成功。

SQL 导出保留 3 条报告、1 条 Gate、1 条 evaluation.rollback_evidence_refused 审计，拒绝原因哈希对应 ROLLBACK_DISTINCT_VERSION_EVIDENCE_REQUIRED。HTTP500 只有两次模型调用，未调用修复模型；审批与执行表为空。证明真实路径触发缺部署证据拒绝，不证明合法真实回滚建议已经测通，也不能把前后差异归因为单一修复。

两次故障清理返回 0，三个结束 checkout 返回 200。清理不是产品恢复。内存泄漏 InvalidDomainValueError 具体子原因未记录，不能推测；报告存在不等于后续流程成功。trace 读取兼容成功也不代表可用 span 充分。实际账单和人工收益未测。

[原始摘要](run-001/summary.json)、完整业务/检查点 SQL、报告、Evidence、调用事件、源码哈希和逐文件哈希一起保留。没有审批决定或恢复执行。

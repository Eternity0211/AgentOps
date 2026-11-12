# 真实模型测评覆盖清单

> 2026-11-12：剩余缺陷、未测指标、四组对照、前后差值及真人/账单/真实历史前置条件，
> 统一由 `TODO.md` 的 “Final closure and comparative validation plan” 跟踪。旧 R/C 项保留为
> 历史记录，不能单独作为完成或提升声明。
> FC0 已将 16 个旧开放项映射到严格注册表 `evaluation/closure/v1/registry.json`；其中
> FC5–FC8 明确依赖真实历史、真人参与或账单数据，其余工程与测量批次按依赖顺序执行。
> FC1 已提供统一配对评分契约；后续前后对照必须输出绝对/相对差、配对 bootstrap 区间、
> 精确 McNemar/符号检验和 Holm 校正，且安全或成本/时延门槛失败时不得声称改善。
> FC2a 已实现 transport 1.5.0 的字段预算和一次有界修复，并保留同适配器内的 1.4.0
> 基线 profile 与交错顺序 runner。
> FC2b 已在实际调用前冻结 162-outcome 配对计划：每个输入/模式交错 1.4.0 与 1.5.0，
> 固定 FC1 阈值和失败计入规则；运行器不接受 evaluator-only 标签。
> FC2c 已完成 81 对实测。终止性结构/协议失败从 12/81 降至 4/81（-8），有效结果从
> 69/81 升至 76/81（+8.64 个百分点），但零失败验收未通过；时延、token 与费率上界
> 均回退，FC1 不允许声称整体改善。原始结果和可复算评分均已保留。
> FC2d-a 已针对剩余的超长解释、`steps_note`、Incident 错配及其调用额度连锁失败实现
> candidate 1.6：请求中加入 schema 派生的精确字段、保守字符上限和字面 Incident 绑定。
> 它不截断或修正模型输出，不增加调用/重试，也不放宽 schema 或 Evidence Gate；尚待冻结实测。
> FC2d-b 已在任何 1.6 provider 调用前冻结 1.5/1.6 的 81 对、162-outcome 计划，绑定
> implementation commit、输入、模拟历史、后置评分标签、runner、transport 及两层 scorer
> 哈希。FC2c 原结果不作为新运行的 baseline 复用，避免跨时间窗口伪配对。

截至 2026-11-06 的阶段审计；不是全部验收通过声明。目标是在保留人工执行授权的前提下，用可解析证据缩短诊断时间。方法包括固定观测回放、实际本地故障注入、真实模型调用、SQL 工作流组合，以及独立确定性安全/续跑测试。预期收益需要对照验证，当前没有证实诊断质量、人工效率或 MTTR 提升。

| 测量项目 | 已有证据与结果 | 结论及剩余边界 |
| --- | --- | --- |
| 根因 Top-1/Top-3 | [54 次真实对照](../evaluation/results/real-comparison/v1/README.md)：单次 5/18，图 4/18 | 图低 5.6 个百分点；已知家族、小样本、混合修订，不支持收益声明 |
| 正常/证据不足/反证 | 同轮两组各 0/9 达标 | 已测未达标，不能删除失败样本 |
| 报告与流程失败 | 单次合法 8/27、失败 19/27；图合法 7/27、失败 20/27 | 工具故障与模型错误分开；部分异常组无法细分 |
| 结构输出前后对照 | [81 对、162 个真实结果](../evaluation/results/structured-reliability/v1/README.md)：终止无效 12→4，有效结果 69→76 | 减少 8 个终止无效，但未归零；有效率差的 95% 区间含零，资源指标回退，FC2 继续开放 |
| 历史记忆 | [模拟历史](../evaluation/results/simulated-memory/v1/README.md) 2/18，控制组 0/9 | 模拟独立报告；无真实已关闭历史，真实记忆按用户决定未测 |
| 工具/Evidence 来源 | 固定观测 374/420 读取组合可用，46 个 trace 失败 | 有来源与哈希；当前 trace 兼容修复后重新测量，未证明证据充分 |
| 调用/token | 真实对照 74 请求，输入 201871、输出 24965；模拟历史 44 请求，输入 161089、输出 15691 | 原始用量可核验；不得把预算估计当账单 |
| 实付费用 | provider 未返回实际账单 | 未测，不填零 |
| 调查时间 | 合法报告样本中位数单次 4773ms、图 4625ms；P95 4859/10312ms | 样本集合不同，不换算提效百分比；失败耗时见原始分布 |
| 注册/SQL/审批等待 | [v2](../evaluation/results/registered-live/v2/README.md) 8 调用、1 PENDING | 提案将 LOG 当部署证据，复核拒绝；不是正确恢复 |
| 动作证据角色 | 捕获 v2 负例回归：缺部署证据前置拒绝、零 provider/审批；有效类型夹具通过 | [v4 真实路径](../evaluation/results/registered-live/v4/README.md) HTTP500 Gate PASS 后拒绝，零修复模型调用/审批；不等于语义因果证明 |
| 实际复测失败 | [v3](../evaluation/results/registered-live/v3/README.md) 6 调用、3 场均 trace 失败 | 零报告/门禁/审批/执行；正常观测有一次 502；故障清理不计恢复 |
| 中断/重放/未知结果 | [14 项 PostgreSQL 组合](../evaluation/results/durable-replay/v1/run-002/README.md)，重规划与并行续跑有精确调用计数 | 真实数据库、受控模型/工具；不冒充真实模型准确率 |
| 并发/吞吐 | [旧版局部负载](../evaluation/results/load/v1/run-001/README.md)，API/SQL/租约/进程内 worker 各有独立分母 | [v6 七场串行实测](../evaluation/results/registered-live/v6/README.md)已有 6 个工作流排队/CPU/Python 堆分布，另 1 个缺测；不是生产容量，[并发实测](../evaluation/results/concurrent-registered/v1/README.md)已测 2/4 路共享队列和事件归属；小批次不代表生产容量 |
| 规则公平基线 | [同 27 快照规则补充](../evaluation/results/rules-snapshots/v1/README.md)：Top-1/3 0/18、控制 6/9、失败 3/27 | 固定 324 快照读取、无模型；旧规则与原始遥测存在输入域差异，不作为单变量因果比较 |
| 安全/拒绝/过期/越权/并发审批 | [当前安全矩阵](../evaluation/results/safety-matrix/v1/README.md)：2991 项回归通过，src 语句与分支 100%，13 类逐项映射 | 确定性测试与真实归档核验；不等于模型安全成功率、真实人工审批或产品恢复 |
| 人工流程 | [模拟操作员](../evaluation/results/simulated-operator/README.md) 与实际审批分离 | 模拟不能证明真人工时、UX 或授权；真实审批/人工收益未测 |
| 产品恢复/稳定窗口/复发 | 实验没有真实人工批准的执行 | 未测；确定性 verifier 测试和评测清理不能替代实测 |
| 独立留出与泛化 | 18 本地故障观测、3 正常、6 派生控制；首个输入参与 smoke | 不声称独立生产留出；未见变体与跨环境泛化仍缺 |

下一步按 FC 清单顺序：先消除 FC2 剩余四个终止无效并复测，再完成 FC3 内存证据对照、
FC4 未触碰留出集质量对照、FC9–FC11 工程测量及 FC12–FC13 汇总。真实历史、实付账单、
真人收益等缺失项保留未测，不构造数据填补。

# Evidence-Bound Portfolio and Resume Statements

## Usage contract

These statements describe repository evidence, not a person's employment, team size, ownership
percentage, or production impact. Keep the denominators, environment, and limitations whenever a
number is used. Every quantitative statement below comes from a committed create-only result or
the versioned clean-machine record.

## Verified project summary

AgentOps Incident Commander is an evidence-driven microservice incident diagnosis and controlled
recovery platform. It limits LLMs to two bounded decision roles: Diagnosis proposes evidence-linked
hypotheses, and Remediation proposes a typed rollback only after a deterministic evidence gate.
Schema validation, policy, human approval, execution, five-signal health verification, and failure
routing remain deterministic authority boundaries. The repository includes a six-fault simulator,
PostgreSQL/pgvector durability, LangGraph checkpoints, a Next.js administration console,
OpenTelemetry-based observability, immutable audit records, versioned evaluation, and locked CI
delivery controls. This is a repository-verified local/hosted-runner system, not a claimed
production deployment.

## Resume-ready statements

Use only bullets that match the contributor's actual work. Keep the evidence references available
in a portfolio version.

- Designed and implemented an evidence-driven incident commander with two bounded LLM decision
  roles and a non-bypassable recovery chain: schema validation, deterministic policy, human
  approval, idempotent execution, and deterministic five-signal verification. [E1]
- Built a versioned six-scenario, four-baseline evaluation harness that separates diagnosis quality
  from recovery safety; each baseline measured 4/4 dangerous-action blocks, 0/2 unapproved
  executions, 1/2 eligible automated recoveries, and 5/6 recovery-safe outcomes. [E2]
- Implemented PostgreSQL/LangGraph crash, replay, and stale-lease controls; the committed resilience
  evaluation passed 13/13 declared controls across 20 collected tests. [E3]
- Established reproducible release gates on a GitHub-hosted Ubuntu checkout: 2,788 Python tests at
  100% statement/branch coverage, 317 console tests at 100% statement/branch/function/line
  coverage, 8 desktop/mobile browser tests, offline package builds, SBOM generation, and configured
  repository/image security scans. [E4]
- Designed the comparison to report negative results rather than manufacture improvement: the
  deterministic rules baseline achieved 6/6 correct handoffs, all three mock-model baselines
  achieved 0/6, and bounded incident memory added 192 input tokens with no scored outcome change
  in this exact six-case experiment. [E2]

## 中文简历表述

以下为英文条目的等价中文版本；仅在本人确实完成相应工作时使用，并保留证据编号与实验范围。

- 设计并实现证据驱动的微服务故障指挥平台，将 LLM 限制为诊断与修复建议两个决策角色，
  通过结构校验、确定性策略、人工审批、幂等执行和五信号健康验证形成不可绕过的恢复链。[E1]
- 构建覆盖 6 类故障、4 组基线的版本化评估体系，将诊断质量与恢复安全分离；每组基线均测得
  危险动作阻断 4/4、未审批执行 0/2、符合条件的自动恢复 1/2、恢复安全结果 5/6。[E2]
- 实现 PostgreSQL/LangGraph 崩溃恢复、重放和租约过期控制；已提交的韧性评估在 20 个测试中
  通过 13/13 项声明控制。[E3]
- 在 GitHub 托管的 Ubuntu 环境建立可复现发布门禁：2,788 项 Python 测试达到语句/分支
  覆盖率 100%，317 项控制台测试达到语句/分支/函数/行覆盖率 100%，并通过 8 项桌面/移动端
  浏览器测试、离线打包、SBOM 生成及配置范围内的仓库/镜像安全扫描。[E4]
- 以可证伪方式报告对比结果：规则基线正确移交 6/6，三组 mock 模型基线均为 0/6；在本次
  6 案例实验中，引入受限历史记忆增加 192 个输入 token，但未改变任何评分结果。[E2]

## Optional bounded-load statement

If a component benchmark is relevant, the only supported wording is scoped to the committed local
run: "Executed a bounded four-surface benchmark on Python 3.12.14, Windows AMD64, 8 logical CPUs:
API health completed 128/128 operations at concurrency 8; PostgreSQL Evidence reads and Job leases
each completed 64/64 at concurrency 8; worker processing completed 64/64 at concurrency 4." [E5]

Do not turn the observed operations-per-second values into production capacity, SLO, availability,
or broker-need claims. PostgreSQL used a temporary Testcontainer, while API and worker probes ran
in-process.

## Quantitative evidence map

| ID | Supported claim | Committed evidence |
| --- | --- | --- |
| E1 | Two-agent boundary and deterministic recovery authority chain | [Project specification](PROJECT_SPEC.md), [architecture](ARCHITECTURE.md), [safety-chain ADR](ADR/0001-agent-boundaries-and-safety-chain.md) |
| E2 | Six scenarios, four baselines, diagnosis/recovery ratios, 192-token memory delta | [Evaluation report](EVALUATION_REPORT.md), [metrics JSON](../evaluation/results/comprehensive/v1/run-001/metrics.json), [comprehensive report](../evaluation/results/comprehensive/v1/run-001/README.md) |
| E3 | 13/13 resilience controls across 20 tests | [Worker-resilience raw result](../evaluation/results/comprehensive/v1/run-001/worker-resilience-raw.json), [comprehensive report](../evaluation/results/comprehensive/v1/run-001/README.md) |
| E4 | Clean runner versions, test counts, coverage, browser tests, build and scans | [Clean-machine rehearsal](CLEAN_MACHINE_REHEARSAL.md) |
| E5 | Bounded operations, concurrency, environment, durations and rates | [Load raw result](../evaluation/results/load/v1/run-001/load-raw.json), [generated load report](../evaluation/results/load/v1/run-001/README.md) |

## Claims not supported

The committed measurements do not support any of the following statements:

- production-ready, production-proven, highly available, or a measured reduction in MTTR;
- statistical superiority, general incident coverage, or hosted-model quality/cost conclusions;
- a duplicate-execution rate from the four baselines, which record `not_measured (0/0)`;
- improved diagnosis from LangGraph or incident memory in the measured experiment;
- production throughput, capacity, SLOs, availability, or a demonstrated need for Kafka/NATS;
- zero vulnerabilities, because the security gate has a defined severity/fix policy and npm
  development-tool advisories remain documented;
- production Kubernetes control, arbitrary shell execution, or LLM authority to mutate or declare
  recovery success.

## Reproduction and update rule

Before changing a number, reproduce the relevant create-only runner from the exact revision in the
[evaluation report](EVALUATION_REPORT.md) or repeat the workflow procedure in the
[clean-machine rehearsal](CLEAN_MACHINE_REHEARSAL.md). Commit the raw artifact and generated report
before updating this file. If a metric has no denominator or reproducible source, omit it rather
than estimating it. Any future production claim requires a separately versioned production
measurement plan and results; local fixtures and CI runs cannot be relabeled after the fact.

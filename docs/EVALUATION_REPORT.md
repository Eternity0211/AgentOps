# Reproducible evaluation report

This report publishes the measured AgentOps evaluation without converting local, deterministic
experiments into production claims. The authoritative machine-readable results are the immutable
JSON artifacts linked below; this document explains their method, environment, interpretation,
and exact reproduction path.

## Methods

The evaluation uses six versioned fault scenarios: release-induced HTTP 500, database-pool
exhaustion, Redis timeout, downstream latency, deployment-linked memory leak, and configuration
drift. Four predeclared baselines receive the same label-free observations, diagnosis dataset,
recovery fixtures, Ground Truth manifest set, safety chain, and aggregate resource limits:

1. `baseline-a-rules`: deterministic rules only;
2. `baseline-b-single`: one sequential mock-model pass;
3. `baseline-c-graph`: the bounded production Diagnosis LangGraph with parallel read-only tools;
4. `baseline-d-memory`: the same graph with at most two advisory, closed historical references.

Diagnosis and recovery safety are separate tracks. Each system finishes before the isolated scorer
loads Ground Truth. The diagnosis track measures ranking, evidence behavior, correct typed handoff,
duration, tool calls, tokens, and recorded cost. The recovery track uses shared typed fixtures and
the deterministic schema, policy, approval, executor, and verifier chain. Only Ground Truth cases
marked automation-eligible enter the automated-recovery denominator.

The create-only comprehensive generator hash-verifies every baseline artifact and applies the
predeclared metrics policy. Worker crash/replay/lease recovery is measured by a separate fixed test
suite and bound into the comprehensive result. A separate bounded-load run exercises four local
component surfaces; it is not part of the diagnosis-quality comparison.

## Execution environment

The four baseline runs used Python 3.12.14 on `win32-amd64`, an AMD64 machine with 8 logical CPUs,
concurrency 1, and seed 7. They ran on 2026-10-29 UTC from four exact clean revisions because each
runner and its result were committed atomically. The shared model was deterministic
`diagnosis-mock/1.0.0`; recorded model cost was zero micro-USD.

The worker-resilience run used Python 3.12.14 on `win32-amd64` at generator revision
`5d036744fbe1ce430b4b59e48f54bfc10373baea`, from
`2026-10-29T14:21:10.765930Z` through `2026-10-29T14:21:41.339819Z`. The bounded-load run used the
same Python/platform and 8-logical-CPU machine at revision
`1678dd05e077dcf16db7dd7779f2642009275406`, from
`2026-10-30T01:35:33.060649Z` through `2026-10-30T01:35:51.057636Z`. Its PostgreSQL workloads used
a temporary Testcontainer; its API and worker probes ran in-process.

## Measured results

The canonical [comprehensive report](../evaluation/results/comprehensive/v1/run-001/README.md)
contains every metric and denominator. The principal diagnosis results are:

| Baseline | Top-1 | Top-3 | Correct handoff | Unsupported conclusions | Input/output tokens |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rules | 0/6 | 0/6 | 6/6 | 0/0 | 0/0 |
| Single pass | 2/6 | 2/6 | 0/6 | 4/6 | 864/1484 |
| Controlled graph | 2/6 | 2/6 | 0/6 | 4/6 | 912/1484 |
| Graph plus memory | 2/6 | 2/6 | 0/6 | 4/6 | 1104/1484 |

All four recovery tracks measured 4/4 dangerous-action blocks, 0/2 unapproved executions, 1/2
eligible automated recoveries, and 5/6 safe outcomes. The memory experiment added 192 input tokens
relative to the otherwise-identical graph and changed no scored outcome. This is a null result for
this exact deterministic model, dataset, and three-record historical-reference set only.

The worker-resilience suite passed 13/13 declared controls across 20 collected tests. The bounded
local load run completed all configured operations: API health 128/128, Evidence reads 64/64, Job
leasing 64/64, and worker processing 64/64. Exact durations, concurrency, and locally observed
rates remain in the raw load artifact rather than being generalized here.

## Raw artifacts

All links below are repository-versioned inputs or create-only outputs:

- Rules: [diagnosis raw](../evaluation/results/rules/v1/run-001/diagnosis-raw.json),
  [recovery raw](../evaluation/results/rules/v1/run-001/recovery-safety-raw.json), and
  [score](../evaluation/results/rules/v1/run-001/safe-outcomes.json).
- Single pass: [diagnosis raw](../evaluation/results/single-agent/v1/run-001/diagnosis-raw.json),
  [recovery raw](../evaluation/results/single-agent/v1/run-001/recovery-safety-raw.json), and
  [score](../evaluation/results/single-agent/v1/run-001/safe-outcomes.json).
- Controlled graph:
  [diagnosis raw](../evaluation/results/controlled-graph/v1/run-001/diagnosis-raw.json),
  [recovery raw](../evaluation/results/controlled-graph/v1/run-001/recovery-safety-raw.json), and
  [score](../evaluation/results/controlled-graph/v1/run-001/safe-outcomes.json).
- Graph plus memory:
  [diagnosis raw](../evaluation/results/controlled-graph-memory/v1/run-001/diagnosis-raw.json),
  [recovery raw](../evaluation/results/controlled-graph-memory/v1/run-001/recovery-safety-raw.json),
  and [score](../evaluation/results/controlled-graph-memory/v1/run-001/safe-outcomes.json).
- Aggregate: [metrics JSON](../evaluation/results/comprehensive/v1/run-001/metrics.json) and
  [worker-resilience raw](../evaluation/results/comprehensive/v1/run-001/worker-resilience-raw.json).
- Load: [raw result](../evaluation/results/load/v1/run-001/load-raw.json) and
  [generated report](../evaluation/results/load/v1/run-001/README.md).

The versioned [evaluation plan](EVALUATION_PLAN.md),
[comparison plan](../evaluation/plans/v1/comparison.json),
[metrics policy](../evaluation/metrics/v1/policy.json), and
[load plan](../evaluation/load/v1/plan.json) define the experiment before interpretation.

## Reproduction

Check out each recorded full revision with a clean tree and use a new empty output directory. The
runners are create-only and intentionally refuse to overwrite the committed `run-001` artifacts.
With the repository environment installed, run:

```text
python -m evaluation.run_rules_baseline --output-dir <new-rules-dir> --code-revision f6f6395a297ed6c723017973924cd3b455874a0b --run-id <new-safe-id>
python -m evaluation.run_single_agent_baseline --output-dir <new-single-dir> --code-revision 06718e14ce76c6ea1ad78cfb8f20beb9f4be0871 --run-id <new-safe-id>
python -m evaluation.run_controlled_graph_baseline --output-dir <new-graph-dir> --code-revision 0fab551974a3d6e10adc7e84d1566a3045d60887 --run-id <new-safe-id>
python -m evaluation.run_controlled_graph_memory_baseline --output-dir <new-memory-dir> --code-revision 70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65 --run-id <new-safe-id>
```

At comprehensive-generator revision `5d036744fbe1ce430b4b59e48f54bfc10373baea`, with all four
baseline directories present at their repository paths, generate worker evidence and the aggregate
report into new paths:

```text
python -m evaluation.run_worker_resilience_evaluation --output <new-worker-json> --code-revision 5d036744fbe1ce430b4b59e48f54bfc10373baea --run-id <new-safe-id>
python -m evaluation.comprehensive_metrics --output-dir <new-comprehensive-dir> --worker-result <new-worker-json>
```

Reproduce bounded load from its exact revision with Docker available for Testcontainers:

```text
python -m evaluation.run_bounded_load_evaluation --output-dir <new-load-dir> --plan evaluation/load/v1/plan.json --code-revision 1678dd05e077dcf16db7dd7779f2642009275406 --run-id <new-safe-id>
```

Compare canonical JSON fingerprints printed by each runner with the fingerprints recorded in its
committed README and in [the evaluation plan](EVALUATION_PLAN.md). Wall-clock durations may differ
across machines; derived decisions and canonical non-timing content remain governed by the
versioned contracts.

## Limitations

- Six deterministic scenarios and one run per baseline do not establish statistical superiority,
  general incident coverage, or production reliability.
- The mock model is reproducible but does not measure a hosted model's quality, latency, or cost.
- Exact-match labels and typed handoff reasons deliberately make the scoring conservative.
- Duplicate execution is **not measured** by the four baseline artifacts (`0/0`): their adapter
  does not dispatch the fixture's declared duplicate delivery. Separate deterministic replay tests
  must not be presented as a baseline rate.
- The rules baseline's empty diagnosis has 0/0 unsupported conclusions and references; that does
  not imply diagnostic accuracy.
- Local durations and bounded-load rates are machine- and run-specific. They are not capacity,
  availability, throughput, service-level, or broker-need claims.
- The recovery fixtures measure the deterministic safety chain independently of Diagnosis Agent
  quality. Proposal correctness therefore does not measure Remediation Agent generation quality.
- Historical-reference retrieval is bounded and synthetic. The measured null result neither proves
  nor disproves the value of incident memory in other datasets or models.

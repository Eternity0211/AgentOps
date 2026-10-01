# Evaluation Plan

## Versioned inputs

Every run records dataset and scenario versions, Ground Truth manifest hashes, evaluator/rule version, code SHA, prompt and model settings, tool schema versions, policy version, random seed, environment/hardware, concurrency, start/end time, and raw per-incident results. Reports are generated artifacts, never hand-edited claims.

## Required baselines

1. deterministic rules system;
2. single agent without controlled graph orchestration;
3. controlled LangGraph agent system;
4. controlled LangGraph system plus historical incident memory.

All groups receive the same allowed observation surface and scenario split. Ground Truth remains evaluator-only.

## Metrics

- root cause Top-1 and Top-3 accuracy;
- unsupported-conclusion rate and fabricated-reference rate;
- correct refusal/human-handoff rate when evidence is insufficient;
- time to diagnosis, tool-call count, tokens, and cost;
- remediation-plan correctness and dangerous-action block rate;
- duplicate execution count, recovery rate, rollback rate;
- worker crash-recovery success rate.

Report denominators, failed/aborted runs, distribution summaries, and uncertainty. Safety metrics include adversarial prompt-injection, authorization-bypass, stale approval, replay, timeout, and missing-evidence suites.

## Dataset split and leakage controls

Scenario templates are versioned and parameterized. Development, regression, and held-out evaluation variants must not share exact identifiers or Ground Truth payloads. Historical-memory experiments can retrieve only training/reference incidents, never the current case or held-out labels. The evaluation harness asserts that agent contexts contain no Ground Truth-only fields or hashes.

## Promotion gates

Prompt/model/policy changes require schema validity, zero fabricated evidence references in the safety regression set, no dangerous-action-policy regression, and configured statistical/absolute thresholds for diagnostic and cost metrics. Initial thresholds will be recorded only after a measured baseline; they must not be invented during scaffolding.

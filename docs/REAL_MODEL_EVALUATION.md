# Real-provider evaluation

## R1: read-only DeepSeek smoke adapter

The opt-in evaluation adapter calls only the official DeepSeek chat endpoint using
`deepseek-flash`, JSON output, disabled thinking, temperature zero, a 2,048-output-token
ceiling, a 60-second request timeout, no retries, no redirects and no environment proxy.
It reads DEEPSEEK_API_KEY from the process environment. Never place keys in commands
committed to the repository, results, or documentation.

Run with an environment-provided credential:

```powershell
.venv/Scripts/python.exe -m evaluation.run_deepseek_smoke --output-dir artifacts/my-run
```

Output directories are create-only. A flushed, fsynced hash-only journal records each
request before dispatch and completion afterward. Bodies, telemetry text, reasoning and
credentials are not stored. Existing DiagnosisReport validation and current-observation
reference membership are required. Usage survives output-validation failures when available;
cost remains explicitly unavailable because token counts are not a billing receipt.

This is an evaluation-only transport, not production composition. API/worker provider
invocation remains disabled. It cannot execute tools, approve recovery, bypass Evidence Gate,
or create immutable runtime Evidence. A validated fixture report is never a runtime Gate PASS.
Scenario-bearing case IDs are replaced with opaque incident IDs; scoring policy is loaded
only after all requests complete. Only synthetic, credential-free observation summaries are sent.

The six-case replay is a smoke experiment, not a live fault-injection benchmark. Exact existing
root-cause IDs are scored without semantic relabeling. Plausible differently named hypotheses
can fail exact matching; do not retrospectively adjust the policy to improve results. No
comparison to mock timing is a valid speedup claim. All incomplete measurement areas remain
open in TODO.md.

Official protocol references:
- https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/
- https://api-docs.deepseek.com/zh-cn/guides/json_mode/

## Required next measurements

| Category | R1 coverage | Remaining work |
| --- | --- | --- |
| Diagnosis | Exact-label Top-1/Top-3, schema failures, reference membership | Held-out repeats, semantic rubric declared in advance, correct handoff, missing/counter evidence |
| Efficiency | Provider wall duration per case | Live first evidence, correct diagnosis, approval/execution/verification, paired human baseline |
| Human effort | Not measured | Active minutes, queries, page switches, interventions, postmortem edits |
| Recovery | Not exercised by R1 | Live approved actions, eligible denominator, first success, stability, recurrence |
| Safety | Transport/schema/reference negative unit tests | Existing deterministic suites, real-model adversarial outcomes, authorization and replay |
| Evidence/audit | Hash journal and fixture reference membership | Runtime store ownership/freshness/independence, redaction and audit correlation |
| Resilience/load | Not provider measurements | Fixed crash/concurrency/outage suites and bounded load runner |
| Resources/cost | Provider token counts and duration | Versioned rate card or billing, tool/retry counts, infrastructure and cost per successful outcome |

Human or production-dependent metrics must remain unmeasured until the corresponding observations
exist. Safety tests are not production reliability estimates. Real-model proposals cannot stand
in for human approval; no end-to-end recovery success is credited from diagnosis-only calls.

## Measurement coverage for the requested checklist

The current integration is an evaluation adapter only. It is not a deployed Diagnosis or
Remediation service integration. The following statuses intentionally distinguish an observed
provider metric, a deterministic regression check, and an unmeasured business outcome.

| Requested metric | Current measurement |
| --- | --- |
| Top-1 / Top-3 | Exact existing root-cause-ID scoring on six synthetic-summary calls |
| Correct human handoff | Not scored: no scenario-specific handoff reason in this report contract |
| Unsupported conclusions | Not semantically measured; label mismatches are not automatically unsupported prose |
| Fabricated references | Unknown fixture-ID count; not a runtime immutable-record resolution rate |
| Missing-evidence recognition | No independent expected missing-evidence rubric yet |
| First useful evidence time | Unmeasured: summaries are preloaded |
| First correct diagnosis time | Unmeasured: provider completion time alone is insufficient |
| Alert-to-recovery / MTTR | Unmeasured: no real-provider recovery experiment |
| Approval wait / execution / verification duration | Existing deterministic checks only, not real incident time distributions |
| Human active minutes / queries / page switches / interventions | Requires paired human trial |
| Postmortem authoring and editing time | Requires paired human trial |
| Remediation suggestion correctness | Unmeasured: adapter emits DiagnosisReport only |
| Eligible / first-attempt recovery success | Existing fixed recovery fixtures remain separately reported; no new provider recovery credit |
| Recurrence rate | Requires declared post-recovery follow-up window |
| Verification-failure handoff | Deterministic regression coverage, not real-provider success rate |
| Dangerous action blocking / unapproved execution | Deterministic policy/executor regression; diagnosis-only calls cannot measure action rates |
| Expired or mutated approval rejection | Deterministic regression coverage |
| Authorization refusal / duplicate execution / false closure | Deterministic regression coverage; no production frequency estimate |
| Evidence resolution / ownership / freshness / independence | Deterministic regression coverage; fixture membership does not establish these properties |
| Counter-evidence handling | Schema and deterministic Gate regression; no semantic model rubric yet |
| Audit completeness | Hash-only provider start/finish journal plus existing runtime audit tests |
| Sensitive-information leakage | No real secrets in input; deterministic redaction tests, no general zero-leakage claim |
| Crash resume success / resume time | Fixed 13-control worker suite; elapsed suite time is not resume latency |
| Duplicate delivery / stale lease recovery | Fixed worker and concurrency regression coverage |
| Queue wait / concurrent throughput / P95 latency | Bounded component load only; no queue-wait or P95 distribution added |
| Provider timeout rate | Per-call statuses in six-case run; timeout refusal also tested with deterministic transport |
| Calls / input-output tokens / retry count | Actual real-provider journal; retries configured to zero |
| Tool calls | No Tool Gateway dispatch in this experiment; not a real investigation tool count |
| Model fee / infrastructure cost / cost per correct result | Unavailable without billing or versioned rate card and resource accounting |
| Time / labor / cost reduction | No paired baseline; no improvement percentage claimed |
| Rule / single / graph / memory quality differences | Existing mock results only; real-provider fair comparison remains open |

All future quality comparisons must predeclare model settings, equal aggregate budgets,
observation access, prompt/schema versions, holdout split and scoring rubric before running.
Do not compare API wall time to mock execution time or use a synonym-normalization rule invented
after seeing these outputs.

## Paired real-provider replay v1

`python -m evaluation.run_real_comparison --output-dir artifacts/paired-run` performs
three repeats of the same six cases in single/graph/memory modes (54 calls). The fixed public
cause taxonomy is declared before running; this is a new experiment, not a rescore of R1.
Modes share model, output ceiling, observation IDs and scoring. Order rotates between repeats.
Graph nodes actually execute the existing LangGraph topology with in-memory checkpoints.
Collection is a fixed deterministic fixture-read plan, not model-generated planning or a live
Tool Gateway. The evidence gate always hands off because fixture IDs are not runtime Evidence.
Historical references are bounded and advisory; citing them as current evidence is rejected.
No runtime provider or mutation capability is enabled. Unknown fees remain null; graph zero
cost bookkeeping is explicitly marked unenforced and is never reported as a measured fee.
This comparison measures orchestration overhead and historical-context effects on known inputs.
It cannot establish held-out generalization, production throughput, recovery or human efficiency.

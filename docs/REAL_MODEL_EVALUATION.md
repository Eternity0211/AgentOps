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

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

## Live Compose diagnosis experiment

`python -m evaluation.run_live_diagnosis --output-dir artifacts/live-run` uses the
repository fault injector against the independent AgentOps Compose project on ports
18080/19090/13100/13200/13000. It generates eight business requests per fault, collects
actual Prometheus/Loki/Tempo observations, and calls the real model once. It verifies
baseline and post-cleanup checkout success. Cleanup runs in finally and earns no recovery
credit. The evaluator uses fixed read endpoints and allowlisted liveness probes; models
receive no commands, fault names or Ground Truth. This is evaluator-driven collection,
not autonomous Tool Gateway investigation or persisted runtime Evidence Gate verification.
Output includes per-call hashes, observed source presence and human-review terminal status.
Do not infer approval, automated recovery or production quality from these observations.

## Adversarial provider probes

`python -m evaluation.run_real_adversarial --output-dir artifacts/adversarial-run`
predeclares six probes and two repeats: log instructions, cross-incident references,
historical-as-current references, approval bypass, synthetic canary echo and missing evidence.
It records strict schema/reference outcomes, exact synthetic-canary echo and the explicit
missing-evidence refusal oracle separately. The model has no mutation capability. An absent
capability is not an executor block-rate measurement, and small-sample safety is not universal
injection resistance. No real credential is sent as a probe.

## Nonhuman summary and remaining human gate

`python -m evaluation.summarize_nonhuman --root evaluation/results/deepseek/v2` derives
counts, nearest-rank P95, raw durations, measured token totals and conservative model-price
bounds. Failed calls remain in quality denominators; missing usage remains unavailable.
The versioned rate card binds the official pricing page observed on 2026-11-03. The interval
spans cache/peak differences and is not an invoice. Container samples are resource snapshots,
not infrastructure monetary cost. Human approval, human labor and paired MTTR remain pending.
Source presence, fixture reference membership and schema validity must not be promoted to
claims of independent runtime evidence or full autonomous incident recovery.

Provider schema failures additionally record only field locations and validation error types,
never input values, provider exception bodies, response text or reasoning.

## Live prompt v1.1 and immutable experiment evidence

The initial live experiment exposed missing or contradictory counter-evidence fields. Prompt
`deepseek-readonly-smoke/1.1.0` adds explicit field rules and a handoff example; old results
remain unchanged. Subsequent live runs create domain Evidence/Artifact records in the ignored
local `artifacts/live-evidence/<run>/<incident>` store, with real collection time ranges,
redaction, prompt-injection inspection, query/source provenance, quality penalties for incomplete
windows/truncation, expiry and immutable content hashes. Valid reports are re-resolved through
the existing Artifact verifier and deterministic Evidence Gate. This is a local experimental
store, not PostgreSQL workflow persistence, and a PASS never grants recovery authority.
The original live-002 runner captured HEAD at completion, so its raw code_revision is a
completion revision; execution began at dd3c168. Keep this correction with the raw record.
The runner now captures revision before its first effect.

## Typed planning and remediation transport

The evaluation-only `structured_model` adapter has three closed purposes: PLAN, DIAGNOSE
and REMEDIATE. Planning emits both the existing typed InvestigationPlan and bounded tool
proposals; the existing compiler validates exact registered read tools, argument schemas,
query uniqueness and aggregate budgets before any dispatch. Source/tool mismatches refuse.
The transport has fixed official endpoint, bounded context, call count, output, response size
and timeout, no automatic retry or redirects, and content-free start/finish records.
Observed usage survives schema failures; conservative peak-price reservations are explicitly
not billed costs. Diagnosis references must belong to supplied current Evidence IDs.
Remediation cannot dispatch without a typed Gate PASS and must match both Gate fingerprints,
incident, candidate and evaluated references. It has no approval or execution capability.
This is not yet production worker composition or prompt promotion; those remain C3/C4 work.

## Autonomous local investigation v1

`python -m evaluation.run_autonomous_live --output-dir artifacts/new-run [--smoke]`
now uses a real PLAN call, the existing deterministic compiler, the existing Tool Gateway,
actual local v2 read adapters, immutable experiment Evidence and the existing Diagnosis
LangGraph. A second real call produces the report, whose references are resolved before
the deterministic Gate. Source/tool consistency, catalog version, service allowlists,
parallelism, cost reservations and aggregate budgets remain server checks.

Loki labels and structured metadata are retained; trace details and bounded metric changes
replace event-name-only/cumulative summaries. Exact query specifications are retained in
Artifact payloads and reconstructable request_spec_* query fields. JSON is trimmed only at
record boundaries; incomplete windows and dropped records reduce quality. Each experiment
uses an isolated SKU so old inventory depletion cannot contaminate its baseline.

Prompt transport v1.1 includes an explicit planning example and rejects extra fields rather
than stripping model output. Schema errors retain field paths/types only. The first local
normal-baseline smoke completed five Gateway reads and two real model calls; this is a
connectivity/workflow observation, not an incident-recovery or accuracy benchmark.
PostgreSQL checkpoints, registered prompt lifecycle, durable progress and work leasing are
still C3 work. Actual approval and product writes remain outside this evaluation runner.

## Autonomous checkpoint composition

The autonomous investigation accepts an official checkpointer and uses the existing
DiagnosisWorkflowRunner to distinguish new work from continuation. A real PostgreSQL
integration test closes and replaces the saver, then replays a completed investigation
without additional model/tool calls. The normal unit flow also verifies terminal replay.
This proves completed-run replay only. Mid-investigation reconstruction of compiled calls,
Evidence, reports and model-call budgets remains C3 work; do not claim general crash recovery
from this test. The default evaluation CLI still uses in-memory checkpoints until the durable
composition is complete.

## Transaction-owning workflow ports

PostgresWorkflowEvidenceStore, PostgresWorkflowPromptStore and PostgresWorkflowModelTraceStore
compose the existing repositories with an independently committed transaction for each write.
Evidence identifiers are published after commit; Prompt lifecycle/model-call changes retain
atomic repository audit. Integration tests verify cross-session reads, tenant isolation,
committed lifecycle transitions and rejected duplicate Evidence/trace completion without
corruption. Full regression: 2,844 tests and 100% source statement/branch coverage. These ports
are integration building blocks; complete durable autonomous-worker composition remains open.

## Bounded supplementary investigation

The autonomous graph now permits one evidence-driven replan under 12 aggregate read calls
and four aggregate model calls. A candidate's declared missing evidence is returned to the
planner. Equivalent earlier queries are rejected by the same compiler before dispatch.
Round-specific identities keep calls and Evidence unique; incremental stores retain original
immutable records and append a separate manifest. Explicit model handoff/refusal does not
force another investigation. Tests cover first-round PASS, second-round PASS after missing
evidence, aggregate accounting and terminal replay without further effects. Query specifications
use base64url JSON chunks to preserve spaces exactly across bounded query fields.

## Committed Evidence in autonomous workflows

The investigation accepts a transaction-owning Evidence store. Each new immutable record
commits before the report receives its ID, and Gate resolution uses that store rather than
an in-memory substitute. PostgreSQL tests cover successful resolution and failed insertion
preventing the diagnosis call. Evidence/call identities are scoped to the incident; Artifact
identities use bounded hashes, and experiment incidents/SKUs are unique per run. Evidence
lineage now uses the exact Gateway call ID, also visible in hash-only tool audit projections.
This injection point is verified; the default local CLI still requires the remaining C3
composition for full Prompt/Job/model-trace persistence.

## Durable evaluation effect replay

The registered job handler accepts `SqlInvestigationEffects` in addition to its SQL stores and
official PostgreSQL checkpointer. [ADR 0008](ADR/0008-evaluation-effect-replay.md) defines the
separate operation namespace, ownership/input/source bindings, committed claims, vetted result
cache, and independent append-only audit verification. Restored plans pass the compiler again;
cached read results and Evidence IDs reconstruct process-local state. Plan/report completion
before graph checkpointing can resume without another provider call. An incomplete effect
refuses redispatch because its external outcome may be unknown. This is not an exactly-once
provider guarantee and does not guarantee recovery from arbitrary instruction-level failures.

PostgreSQL tests exercise before-dispatch/before-Evidence boundaries and completion-before-graph
transition failures for PLAN, Evidence and DIAGNOSE. These use controlled provider fixtures,
not actual DeepSeek responses. Additional tests cover replacement before a supplementary plan
and before its Evidence creation: first-round feedback and Evidence remain present, with four
model calls and three total reads. A partially completed parallel wave reuses the finished read
and dispatches only the pending one. An uncertain dispatched read is refused on subsequent
attempts and cannot produce a successful Job. Production startup composition remains separate.
Default local comparison runners
retain their original behavior; the published 54+27 real-model outcomes are never rewritten.

Progress schema 1.1.0 retains up to three previous FAILED/CANCELLED attempt summaries in its
persisted step projection. The recorder's default remains terminal-immutable; the audited
evaluation fixture explicitly enables two retries. These progress retries do not authorize
dispatch: the effect store separately checks committed/uncertain outcomes. Legacy 1.0.0 rows
must pass their original hash/ownership checks before migration. See
[ADR 0009](ADR/0009-bounded-tool-progress-retries.md). This is backend progress history; the
administration view still shows the current step status rather than a retry-history UI.

## Isolated lab Prompt registration preflight

`evaluation/lab_prompts.py` runs the versioned mechanical
[bootstrap protocol](../evaluation/registered_protocol/v1/bootstrap.json) before activating
PLAN/DIAGNOSE/REMEDIATE registrations in the fixed `registered-evaluation-lab` tenant. It
drafts first, makes three actual provider calls, checks the plan through the shared compiler,
resolves diagnosis references and Gate decisions against immutable fixture Artifacts, and
admits the typed remediation against a separately declared synthetic Gate. The current-version
and introducing-deployment references must differ. All three must pass before any promotion.
Failures remain DRAFT and are retained in per-purpose records. Other tenants refuse before work.

The observations and Gate are explicit synthetic safety fixtures, not historical Incidents or
real fault outcomes. Mechanical regression does not measure semantic root-cause accuracy,
human review or production readiness. The normal Prompt lifecycle and audit are used without
fabricated provider successes; this isolated preflight is not production Prompt promotion.

Three actual-provider preflights are now [archived](../evaluation/results/lab-prompt-bootstrap/README.md):
two v1 calibrations and one v2 calibration adding explicitly synthetic stack/canary observations.
All nine responses pass transport/schema validation. In all three runs, diagnosis still declares
missing Evidence and fails Gate; PLAN and REMEDIATE mechanical checks pass. Consequently every
Prompt remains DRAFT (zero activations), with SQL lifecycle audit exported before container
cleanup. The v2 fixture was designed after seeing v1 and is not an unseen test. No pending
approval, real fault recovery, or production promotion is claimed by these preflights.


The separately versioned v3 calibration uses the same six v2 observations and diagnosis
instruction 1.1.0 (transport 1.3.0). It distinguishes required candidate support from optional
follow-up details while explicitly forbidding omission of real requirements. Gate/compiler
rules remain unchanged. Three actual calls pass and three lab registrations become ACTIVE;
SQL exports contain nine lifecycle audit events. This is exposed synthetic calibration, not
unseen quality evaluation, production promotion, human approval or recovery execution.


`persist_registered_report_gates` bridges the registered SQL diagnosis and remediation paths.
It reloads the stored report, verifies its tenant/Incident/workflow and successful model-trace
fingerprint, resolves current Evidence/Artifacts, and atomically records each deterministic
Gate decision with its audit. Caller-supplied candidate reports or PASS booleans are not inputs.
This step does not request approval or dispatch recovery; the existing registered remediation
adapter subsequently requires the exact stored PASS before and after model invocation.


`propose_and_request_sql_review` composes the stored Gate pre/post checks, registered
remediation invocation, server-owned Policy input factory and committed Approval request.
Provider work runs outside SQL transactions. Policy decisions, including refusals, have
hash-bound audit events; an eligible request commits its PENDING Approval/review snapshot
atomically with the Policy audit. It provides no approve/execute capability. The combined
PostgreSQL test uses controlled provider responses and separately checks Policy denial;
actual-provider live composition remains a separate evaluation requirement.


`run_registered_case` composes SQL Incident transitions, Job claim/lease, registered model
traces, durable effects, Evidence/report persistence, deterministic stored Gate, remediation,
Policy and PENDING review. A server callback advances POLICY_REVIEW only after proposal
admission. Failure routes to NEEDS_HUMAN; no approver/executor capability is present. Controlled
PostgreSQL tests reach AWAITING_APPROVAL across all three bootstrap fixture versions, with
in-memory checkpoints in these particular cases. Earlier tests separately exercise official
PostgreSQL checkpoints. A live telemetry CLI and actual-provider combined run remain open.


The actual [registered live rehearsal](../evaluation/results/registered-live/v1/README.md)
runs the official PostgreSQL saver plus SQL queue/registry/report/Evidence/traces against
actual Compose observations and actual provider calls. Three cases finish: normal handoff,
HTTP500 and memory-leak both refused at remediation schema. Eleven total calls include three
separate synthetic bootstrap calls; zero PENDING approvals or executions. Both fault cleanups
return zero and checkout returns 200. SQL task completion is not Incident recovery. Full report/
Gate SQL snapshots and invalid proposal bodies were not exported in this first run; the record
states these limitations rather than reconstructing missing outputs. The next integration
iteration must address the cross-reference contract and retain complete reviewable SQL records.


The [v2 rehearsal](../evaluation/results/registered-live/v2/README.md) clarifies the existing
distinct-reference constraint (transport 1.3.1, remediation Prompt 1.1.0), retaining schema/Gate
rules. It exports all domain table rows and official checkpoint rows, with binary values base64.
Eight actual calls yield two read-tool failures and one PENDING review request. Post-hoc role
review finds LOG used as introducing-deployment Evidence and recommends rejection; this is not
an actual approval decision. The snapshot preserves that unsafe recommendation and empty
execution tables. Pending persistence is demonstrated, but recommendation correctness is not.
A deterministic action-evidence-role guard remains required before claiming safe remediation.

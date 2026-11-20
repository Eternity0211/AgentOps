# AgentOps Incident Commander Evaluation Plan

## Project outcome scorecard

The project-level effect contract is defined in
[`PROJECT_EFFECT_SCORECARD.md`](PROJECT_EFFECT_SCORECARD.md) and its machine-readable authority at
[`evaluation/scorecard/v1/scorecard.json`](../evaluation/scorecard/v1/scorecard.json). It makes
time to correct diagnosis, time to stable recovery/MTTR, active operator labor, diagnosis/action
correctness, and recurrence the core outcomes. Safety is a hard gate; tokens, latency, cost,
durability and throughput are supporting engineering measurements rather than substitutes for
those outcomes.

The next development-stage measurement is a new untouched lab holdout with frozen rules, single-
model and controlled-graph arms. A simulated-history arm is exploratory only. The formal confirmed-
history arm, human study, approved recovery comparison, actual cost reconciliation, and recurrence
claim remain blocked until their explicitly named external inputs exist.

### Frozen FC4 development holdout

The create-once runtime inputs are under
[`evaluation/datasets/lab-holdout-v1`](../evaluation/datasets/lab-holdout-v1), while labels, power
arithmetic, and the complete hash manifest are separately stored under
[`evaluation/lab_holdout/v1/evaluator_only`](../evaluation/lab_holdout/v1/evaluator_only). The set
contains 120 fault cases, twenty for each of the six declared fault families, plus ten each of
normal, insufficient-evidence, counter-evidence, and prompt-injection controls. Fault cases cross
direct/cross-service dependency, recent/old/no deployment change, and three bounded signal levels.

The pre-run sizing contract declares a 15-percentage-point minimum relevant paired Top-1 effect,
two-sided alpha 0.05, power 0.80, and a 0.30 discordant-pair assumption. Its fixed calculation
requires 103 fault pairs; the dataset freezes 120. This adequacy statement is conditional on those
assumptions and does not guarantee significance. The generator, plan, every input, runtime index,
labels, and power file are hash-bound. Publication tests reject changed bytes, reused prior IDs or
input hashes, runtime label fields, incomplete strata, or changed power arithmetic.

The dataset is frozen before FC4c candidate work. Development/error analysis must use other data.
FC4d may run this set once after the candidate and scorer are frozen; failures stay in the
denominator and selective reruns remain forbidden.

### Frozen FC4 development error census

Before candidate changes, the existing candidate-1.11 development outcomes were classified by
[`evaluation.diagnosis_error_analysis`](../evaluation/diagnosis_error_analysis.py). Its immutable
publication is under
[`evaluation/results/diagnosis-error-analysis/v1`](../evaluation/results/diagnosis-error-analysis/v1).
Among 54 fault outcomes, 36 were Top-1 correct and 18 were misses. Nine memory-leak misses safely
handed off because the legacy main context omitted the independently validated FC3 GC-aware facts.
Nine bad-configuration misses emitted the observed HTTP symptom after collecting only gateway
Evidence, without downstream configuration or deployment Evidence. The candidate response is
therefore limited to the already validated context contract plus bounded deterministic read-only
downstream expansion. Ranking changes remain out of scope until decisive Evidence is present.

The analysis is post-hoc and is not a new quality measurement. It hashes the evaluator-only
labels, frozen outcomes and analyzer source, publishes no provider response body, and cannot be
used to tune or inspect the untouched FC4 lab holdout.

The candidate implementation is selected explicitly by `EvidenceStrategy`; the existing legacy
path remains the default. `GC_AWARE` changes only context construction. `GC_AWARE_CAUSAL_SCOPE`
also applies a deterministic route guard when a proposed `http-500` cause is supported only by
upstream Evidence while a deeper allowlisted failing dependency is directly observed. The guard
uses current topology plus error spans/logs, chooses at most the deepest observed service, and is
satisfied only by that service's deployment Evidence plus one logs/metrics/traces read. It cannot
name a cause, issue a write, bypass the Gate, or expand a second service. If the bounded replan or
provider-call reserve is unavailable, the result is human handoff.

The snapshot runner records the evidence strategy and provider-call ceiling in each runtime
manifest. This permits the next development comparison to give baseline and candidate identical
ceilings while changing only the declared strategy. The integration fixture is a behavior and
safety test, not a measured quality-effect claim; FC4c2 remains open until the separate development
comparison is frozen, executed and scored.

### Separate FC4 candidate-development set

The strategy is not tuned on either the candidate-1.11 error census or the untouched FC4 lab
holdout. A create-once development set lives under
[`evaluation/datasets/evidence-strategy-development-v1`](../evaluation/datasets/evidence-strategy-development-v1),
with its isolated labels and complete file manifest under
[`evaluation/evidence_strategy_development/v1/evaluator_only`](../evaluation/evidence_strategy_development/v1/evaluator_only).
It contains 27 cases: three variants for each six fault families and three each for normal,
insufficient-Evidence and counter-evidence controls. Its IDs and input hashes are disjoint from
real-v1, real-v2 and the FC4 lab holdout. The memory cases contain five GC-bound retained-memory
samples; bad-configuration cases contain an observed cross-service failure that exercises the
bounded causal-scope route.

The label-free pair runner in
[`evaluation/run_evidence_strategy_pair.py`](../evaluation/run_evidence_strategy_pair.py) changes
only the declared `EvidenceStrategy`. Both arms use transport 1.11, the same provider settings,
six-call provider ceiling, twelve-call tool ceiling, frozen snapshots and controlled-graph mode.
Arm order alternates by case. Runtime manifests bind the selected strategy and ceiling. Existing
outcomes may be resumed only when the protocol and input hashes match; partial directories become
retained failures. Evaluator labels are loaded only by the post-run paired scorer. A separate
implementation-bound protocol commit is required before any provider call.

The dedicated scorer in
[`evaluation/score_evidence_strategy_pair.py`](../evaluation/score_evidence_strategy_pair.py)
publishes paired Top-1, Top-3, safe-control, valid-outcome and Evidence-integrity rates plus paired
duration, input-token, output-token and deterministic rate-card cost distributions. Every metric
contains baseline, candidate, absolute and relative change, a 95% interval and its paired test.
Fault failures count as incorrect diagnoses, control failures count as unsafe, and unknown resource
pairs remain visible and close the resource gate. Candidate acceptance additionally requires the
frozen minimum Top-1 correct-count gain, Top-3 and control non-inferiority, zero candidate failures,
zero terminal schema/protocol invalids, complete Evidence resolution and the latency/cost gate.

The provider-call protocol is frozen at
[`evaluation/evidence_strategy_development/v1/pair-plan.json`](../evaluation/evidence_strategy_development/v1/pair-plan.json).
It binds implementation commit `18fda0a6`, all runner/workflow/transport/scorer source hashes, the
dataset index and isolated labels. Both arms use transport 1.11, DeepSeek Flash with identical
generation settings, a six-call provider ceiling, four successful graph-model-call ceiling and
twelve read-tool ceiling. The acceptance floor is at least two additional Top-1-correct fault
cases out of eighteen, with Top-3 and control non-inferiority, zero candidate failures, zero
terminal schema/protocol invalids, complete Evidence integrity, and the frozen resource margins.
All 54 outcomes must finish before labels are opened; the result is retained even if it rejects
the candidate.

Run-001 is published under
[`evaluation/results/evidence-strategy-development/v1/run-001`](../evaluation/results/evidence-strategy-development/v1/run-001).
It completed 27 outcomes per arm. Top-1 and Top-3 increased from 2/18 to 7/18: +5 correct cases,
+27.78 percentage points, with a paired 95% bootstrap interval from 0 to +55.56 points. Safe
controls stayed 9/9 and every citation resolved with a matching Artifact hash. Candidate medians
also moved in the favorable direction: duration 5,485→4,843 ms (-642), input tokens 5,080→4,839
(-241), output tokens 828→744 (-84), and deterministic rate-card cost 2,510,400→2,349,300 nUSD
(-161,100). These resource deltas are not actual billing or human-time claims.

The frozen acceptance decision is nevertheless `false`: failures decreased from 9/27 to 3/27 but
the candidate threshold was zero. All twelve failures occur after a schema-valid replan response,
where the deterministic plan compiler rejects an equivalent prior read at
`compile_investigation_plan:142`. Candidate terminal schema/protocol invalids are zero; its one
initial invalid response was successfully repaired. The next development revision may filter
equivalent prior reads deterministically and retain only novel typed reads, but it must be audited,
must hand off if no novel read remains, and must run a complete new frozen pair. Run-001 will not be
edited, deleted or selectively rerun.

The run-002 implementation now validates the model's entire replan against the unchanged catalog,
source-role, payload, risk and resource rules before filtering anything. It then compares the
compiler's exact tool/version/argument query fingerprints with the already executed history. Only
novel calls and their plan steps remain; dependencies on removed steps are pruned while retained
dependencies keep their original order. The filtered plan is compiled again with the prior-query
set, so filtering cannot admit an invalid or repeated read. The journal records only the round,
counts, decision and query fingerprints, never provider text or tool arguments.

If every proposed call repeats history, the validated repeated plan is returned to the production
graph's existing repeated-query guard. The graph consumes the bounded model call, records
`REPEATED_EQUIVALENT_QUERY`, dispatches no tool and routes to human handoff. The same deterministic
filter applies to both development arms; therefore the next frozen pair still changes only
`EvidenceStrategy`. Run-002 must be a new complete 27-case-per-arm experiment, not a repair or
selective rerun of run-001.

The create-once run-002 protocol is frozen at
[`evaluation/evidence_strategy_development/v2/pair-plan.json`](../evaluation/evidence_strategy_development/v2/pair-plan.json).
It binds implementation commit `7d3d2e3`, the new filter-bearing workflow and transport hashes,
the unchanged dataset and isolated labels, and the same provider settings, ceilings, scorer,
thresholds and parity interleaving as run-001. Its held-constant list explicitly includes the
filter and all-repeated handoff in both arms. No run-002 provider call may precede this protocol
commit.

Run-002 is published under
[`evaluation/results/evidence-strategy-development/v1/run-002`](../evaluation/results/evidence-strategy-development/v1/run-002).
All 54 outcomes completed: failures are 0/27 in both arms, safe controls are 9/9 in both arms,
and all 112 cited Evidence references resolve within their Incident with matching Artifact hashes.
The filter emitted 22 content-free audit events; 15 removed at least one exact prior query, and no
comparison failed. The reliability defect from run-001 is therefore resolved on this development
set.

The frozen quality acceptance still fails. Top-1 and Top-3 are 11/18→12/18, a gain of one case or
5.56 percentage points, with paired 95% interval -22.22 to +33.33 points; the protocol required at
least two additional correct cases. Candidate gains occur on two memory-leak cases, one
bad-configuration case and one Redis case, while it loses one downstream-latency, one HTTP-500 and
one Redis case; three cases are wrong in both arms. Median candidate deltas are +234 ms, +137 input
tokens, +97 output tokens and +129,600 rate-card nUSD. Their intervals cross zero, every resource
claim is `NO_PROVEN_IMPROVEMENT`, and the frozen non-regression margins pass. These costs are rate-
card bounds rather than billing, and workflow duration is not human diagnosis time.

The versioned run-002 error analysis is frozen at
[`evaluation/evidence_strategy_development/v3/error-analysis.json`](../evaluation/evidence_strategy_development/v3/error-analysis.json).
All seven Top-1 discordant pairs sent byte-identical initial PLAN requests across arms, yet all
seven received different provider responses before the strategy-specific diagnosis context or
causal-scope guard could act. Six initial responses validated; the seventh candidate response was
schema-invalid and then repaired. Thus the observed four candidate gains and three candidate
losses contain pre-strategy provider variation and cannot be attributed solely to the evidence
strategy. The artifact binds the immutable score and protocol hashes, records response hashes but
no response bodies, and has a regression test that recomputes every comparison from the archived
events.

The three shared misses identify only one safe, label-free route change. The bad-configuration case
directly observed an unread failing downstream service but the model handed off without a
candidate, so the old `bool(candidates)` condition prevented the already bounded causal replan.
The final revision permits that same one read-only replan when deterministic current Evidence
identifies the missing scope. It also returns the exact legacy diagnosis context whenever no
discriminative GC-aware memory facts exist, eliminating avoidable non-memory prompt perturbation.
The memory and Redis shared misses selected only insufficient or healthy aggregates; they remain
safe handoffs rather than receiving label-aware reads. Schemas, typed Tool Gateway checks, Evidence
Gate, budgets and all write-authority boundaries are unchanged.

Run-003 is the final development-set revision. Its protocol must be committed before calls, retain
the run-002 acceptance thresholds, execute all 54 outcomes once, preserve every failure, and forbid
selective reruns. After scoring, development tuning stops regardless of result. Failure means the
candidate is rejected for FC4d and the negative result is retained; it does not authorize another
revision on these 27 cases. The untouched FC4 holdout remains unopened throughout.

The create-once protocol is now frozen at
[`evaluation/evidence_strategy_development/v3/pair-plan.json`](../evaluation/evidence_strategy_development/v3/pair-plan.json).
It binds implementation commit `3a1ecff9`, the unchanged dataset and evaluator-only label hashes,
the v3 error analysis, all six runtime/scorer source hashes, transport 1.11, identical DeepSeek
settings, equal six-provider/four-graph/twelve-tool ceilings, parity interleaving, and the original
+2-case acceptance floor plus safety/resource conditions. The machine-readable stopping rule says
that this single complete pair ends development-set tuning whether it passes or fails. No run-003
provider call may precede this protocol commit.

Run-003 is published under
[`evaluation/results/evidence-strategy-development/v1/run-003`](../evaluation/results/evidence-strategy-development/v1/run-003).
All 54 outcomes are retained. Candidate Top-1 and Top-3 are 11/18 versus baseline 7/18: +4 correct
cases, +22.22 percentage points, with paired 95% interval +5.56 to +44.44 points. Both arms are 9/9
on safe controls; candidate failures and terminal schema/protocol invalids are zero; every one of
the 95 citations resolves within the same Incident with a matching Artifact hash. The baseline has
one retained failure after an invalid response and unsuccessful repair. The frozen development
acceptance therefore passes.

This promotion result is not itself a final improvement claim. The paired McNemar raw p-value is
0.125 and becomes 1.0 after the frozen Holm correction; the scorer correctly retains
`NO_PROVEN_IMPROVEMENT` because the evidence does not establish the predeclared minimum relevant
effect. Median candidate deltas are +405 ms, +201 input tokens, +112 output tokens and +136,200
rate-card nUSD; all intervals cross zero and all claims remain `NO_PROVEN_IMPROVEMENT`. Run-003 is
immutable, development-set tuning is closed, and the accepted candidate may proceed only to the
once-only, adequately powered FC4 holdout confirmation.

### FC4 untouched three-arm confirmation tooling

The final label-free runner is
[`evaluation/run_final_diagnosis_comparison.py`](../evaluation/run_final_diagnosis_comparison.py).
It requires a separately committed source-bound protocol, verifies the frozen 160-input index,
and rotates deterministic rules, single-model and controlled-graph order by index position. The
two model arms use the same transport 1.11 provider settings, six-provider/four-graph/twelve-tool
ceilings, no history, and the promoted GC-aware causal-scope Evidence strategy. Their declared
independent variable is therefore single-pass model diagnosis versus bounded controlled-graph
orchestration. The unchanged rules system uses its fixed twelve-read schedule and remains a
secondary reference because its collection policy differs from model planning.

Every terminal outcome is written to one shared create-only ledger. A complete rules result lost
before ledger append is validated and recovered without another run. Any other pre-existing
partial directory becomes a hash-bound failed outcome; it is never deleted or selectively rerun.
Runtime manifests bind the protocol, snapshot, source hashes, revision, strategy, profile and
budgets. The runner has no labels parameter and does not read the evaluator-only path.

The post-run scorer is
[`evaluation/score_final_diagnosis_comparison.py`](../evaluation/score_final_diagnosis_comparison.py).
It requires exactly 480 unique outcomes with matching input/protocol hashes and validates every
runtime/source binding before it opens the evaluator labels. Its primary comparison is single
model to controlled graph; rules-to-single and rules-to-graph are secondary. It reports both arm
values, paired deltas and 95% intervals for Top-1, Top-3, safe controls, valid outputs, Evidence
integrity, unsupported-conclusion-free cases, fabricated-reference-free cases, Gate recall,
duration, input/output tokens, rate-card cost, model calls and read-tool calls. It additionally
reports exact conclusion/reference conditional rates and Gate precision with paired bootstrap
intervals when both denominators exist; a zero denominator stays explicit and is never converted
to zero percent. The critical safety gate requires every citation to resolve to the same Incident
and matching Artifact hash; a fabricated reference remains a scored negative result rather than
being hidden by aborting publication.

This implementation does not open or score the untouched labels. The exact once-only protocol is
now frozen at
[`evaluation/final_diagnosis_comparison/v1/plan.json`](../evaluation/final_diagnosis_comparison/v1/plan.json).
It binds implementation `67614aa4`, protocol hash
`dd51fe0bbee172bda4248a021ed3a4c924cf5519d416d5f1acdab02c5d9925a5`, all fourteen
runtime/scorer source hashes, the 160-input index, original dataset plan, freeze manifest, power
analysis and evaluator-label hash without opening the label content. The primary paired Top-1
minimum relevant effect is the power contract's 15 percentage points; all other quality, safety,
Gate and resource thresholds are also fixed before calls. The execution order rotates all three
arms, partial work is retained as failure, selective reruns are forbidden, and scoring begins only
after 480 outcomes validate. The execution is complete; the protocol and opened cohort are now
closed to tuning.

The first execution command stopped during label-free preflight, before output creation or any
provider call, because the shared snapshot validator still carried the earlier 27-case assumption.
The validator now takes the protocol's explicit expected count, and the replacement freeze binds
that shared validator as a runtime dependency. The stopped preflight is not an experimental
outcome or a rerun; no provider call occurred before the replacement freeze.

The once-only run subsequently completed all 480 outcomes. On the first scoring attempt, all
runtime and result audits passed and the evaluator labels were opened, but score generation stopped
before producing any metric because the strict scorer model omitted six audit-only fields already
present in every frozen label record. The compatibility patch declares those exact existing fields;
only `stratum` remains a scoring input. It does not alter label bytes, outcomes, metrics,
thresholds, bootstrap settings, or the no-rerun rule. Because this defect was discovered after
labels were opened, the original protocol remains immutable and a separate source-bound
compatibility amendment is required before score generation.

That amendment is now frozen at
[`evaluation/final_diagnosis_comparison/v1/scorer-compatibility-amendment.json`](../evaluation/final_diagnosis_comparison/v1/scorer-compatibility-amendment.json),
SHA-256 `5c7450c01ae222e0e754bf0d9f6f48682903c0332e73cc79af9da7cad646799d`.
It binds patch commit `7343c028`, the original protocol and scorer hashes, the unchanged label
hash and the exact eight-field label record. Its four explicit mutation flags are false and
Provider reruns remain forbidden.

The amended scorer published the immutable result under
[`evaluation/results/final-diagnosis-comparison/v1/run-001`](../evaluation/results/final-diagnosis-comparison/v1/run-001).
All 480 outcomes are retained: rules recorded 10 failures, single model zero, and controlled graph
one. The primary single-model-to-controlled-graph Top-1 and Top-3 rates are 10/120 to 49/120,
+39 cases or +32.5 percentage points. The Top-1 paired 95% interval is +23.33 to +42.50 points and
the Holm-adjusted p-value is approximately `3.06e-8`. This large lab quality effect is not a
project-level improvement claim because the one structured controlled-graph failure leaves
Evidence-integrity and fabricated-reference-free outcome coverage at 159/160, failing the frozen
critical-safety gate. Median workflow latency, input tokens, and rate-card cost upper bound also
regress by 508 ms, 201 tokens, and 155,100 nUSD. The create-only `file-hashes.json` manifest binds
all 5,994 published files; no Provider result was rerun.

The next optimization cycle uses only separate development fixtures. It first binds an
aggregate-only audit of the generic structured-output failure and graph tail overhead, then may
add a fail-closed terminal fallback and remove redundant context/calls without relaxing schemas,
Evidence Gate rules, budgets, or recovery authority. Confirmation requires a newly generated,
powered, disjoint, label-isolated cohort frozen before candidate calls. That cohort is executed
once, and Top-1 effect, critical safety, and latency/cost gates must pass together. FC4d inputs or
opened labels cannot be used for tuning, prompt selection, or candidate selection.

FC4f audit 001 is now published from a frozen label-free plan. A deterministic development
transport fixture reproduces the terminal defect as two schema-invalid calls followed by
`INVALID_RESPONSE`, with 200 input tokens, 200 output tokens and a 300,000 nUSD rate-card upper
bound but no valid report. A separate 27-pair archived development comparison finds ordinary
controlled-graph overhead of only +16 ms median and +31 ms P95, input-token deltas of 0/-3, and
zero model/tool-call deltas. Because it does not reproduce the confirmation-tail regression, the
next implementation may change only deterministic terminal fallback and an explicit bounded-replan
fixture; it cannot reduce normal Evidence context based on the opened FC4d cohort.

Structured transport 1.12 therefore adds one opt-in deterministic terminal behavior: only when a
DIAGNOSE response and its single bounded repair both fail a repairable schema/binding check, the
evaluation adapter emits a candidate-free and reference-free `HUMAN_HANDOFF`. It retains the two
Provider calls' measured usage, cost upper bound and duration and emits a content-free audit event.
It does not catch PLAN, REMEDIATE, HTTP, timeout, transport, context or budget failures. Version
1.11 and every prior result remain unchanged. The explicit bounded-replan development fixture and
resource-ceiling check remain required before 1.12 can be frozen for a new confirmation cohort.

The first FC4f2b graph fixture now exercises the complete bounded path: two initial reads, one
novel deployment read after a failed Evidence Gate, and a final DIAGNOSE response plus its one
repair that both violate the unchanged explanation limit. Transport 1.12 ends in a deterministic,
candidate-free, reference-free human handoff. The fixture retains three same-Incident Evidence
records, five physical Provider calls, four logical graph model calls, three tool calls, 500 input
and 500 output fixture tokens, and a 750,000 nUSD fixture rate-card upper bound. Its provider,
graph and tool counts stay under the declared 6/4/12 ceilings. This deterministic mock transport
does not estimate actual Provider latency or prove a paired resource effect. A frozen separate
development comparison remains necessary before FC4f2b or FC4f2 can close.

The FC4f2b development runner pairs transport profiles 1.11 and 1.12 on the already separate,
frozen 27-case evidence-strategy development snapshots. Both arms retain the GC-aware causal-scope
strategy, controlled-graph mode and 6/4/12 Provider/logical-graph/tool ceilings. It alternates arm
order, checks implementation and source hashes before any Provider call, never opens labels, and
retains an interrupted case as a failed outcome instead of reusing partial effects. A later protocol
commit will bind its exact inputs, label hash for post-run scoring, implementation revision,
thresholds and stopping rule before the first call. The scorer will report paired safety, validity,
duration, tokens and rate-card estimates; this is development evidence, not the new untouched FC4f4
confirmation cohort.

## Implemented foundation

Contract versions: dataset `phase12-eval-v1`, recovery fixtures
`phase12-recovery-safety-v1`, rules `phase12-rules-v2`, diagnosis raw Schema `1.1`,
recovery-safety raw Schema `1.0`, fairness policy `phase12-fairness-v1`, and safe-outcome scoring
policy `phase12-safe-outcomes-v1`. Diagnosis raw Schema `1.0` and the combined raw Schema `1.1`
are retained only as version history and are not current Harness outputs.

The committed `evaluation/datasets/v1/dataset.json` contains six strictly ordered, label-free cases
covering the same public scenario IDs as the evaluator-only manifests. Each case exposes only a
bounded alert summary, time window, typed observation summaries, and the fixed read-tool catalog.
The current rules in `evaluation/rules/v2/rules.json` bind that dataset version, Harness version, allowed
terminal statuses, mandatory Ground Truth field exclusions, and case/observation/Top-K/tool/token/
cost/duration bounds. Closed JSON Schemas for the dataset, rules, and raw result live under
`evaluation/schemas/`.

`evaluation.harness` exposes two non-interchangeable entry points. `run_diagnosis_track` loads and
hash-binds the label-free dataset/rules/fairness-policy/comparison-plan set and accepts only root-
cause ranks, resolvable Evidence IDs, Evidence Gate outcome, a typed refusal/handoff reason, and
resource use.
`run_recovery_safety_track` accepts only the fixed, versioned inputs in
`evaluation/recovery/v1/fixtures.json`; it never accepts a diagnosis result, candidate ranking,
candidate Evidence ID, scenario identity, or Ground Truth label. Both paths receive the same
immutable fairness profile, reject cross-track fields, validate aggregate resource totals, record
adapter failure under a stable content-free code, and emit distinct canonical create-only raw
artifacts.
It does not import, mount, or load `evaluation/ground_truth/`; scoring joins Ground Truth only in a
later isolated evaluator phase after candidate output exists. Raw artifacts record the exact code
revision, scenario and baseline versions, Ground Truth manifest-set hash (never its labels), model
and settings hash, prompt, policy, tool Schema versions, Python, platform, hardware summary,
concurrency, seed, rules/fairness hashes, run window, per-case track output, calls, tokens, cost,
duration, and stable error code. Diagnosis artifacts bind the dataset hash; recovery-safety
artifacts bind the independent fixture hash. Metadata is persisted around each call and is never
passed into system input.

`evaluation.report` dispatches on the closed track discriminator, reloads an artifact only with its
exact dataset or recovery fixtures plus rules, fairness policy, and comparison plan, verifies every
hash and the complete track-specific case set, and creates (never overwrites) deterministic
Markdown. Diagnosis and recovery columns cannot appear in the other track's report. The current
reports contain only raw status and resource distributions plus a prominent no-claims
notice. It intentionally does not calculate the later Top-K, safety, recovery, or comparative
metrics before their versioned scoring contracts and denominators exist. A bound raw artifact can
be rendered directly with:

```text
python -m evaluation.report --raw <diagnosis-raw.json> --dataset evaluation/datasets/v1/dataset.json --rules evaluation/rules/v2/rules.json --fairness-policy evaluation/fairness/v1/policy.json --fairness-plan <plan.json> --output <diagnosis-report.md>
python -m evaluation.report --raw <recovery-raw.json> --dataset evaluation/datasets/v1/dataset.json --recovery-fixtures evaluation/recovery/v1/fixtures.json --rules evaluation/rules/v2/rules.json --fairness-policy evaluation/fairness/v1/policy.json --fairness-plan <plan.json> --output <recovery-report.md>
```

After both raw tracks are immutable, `evaluation.scoring` alone loads the evaluator-only manifest
set. It verifies the aggregate manifest hash recorded by both runs, joins cases by the separate
dataset/fixture scenario mappings, and applies the non-weakenable policy at
`evaluation/scoring/v1/safe-outcomes.json`. Its create-only score artifact binds both raw hashes,
the diagnosis dataset hash, recovery fixture hash, Ground Truth set hash, and scoring-policy hash.
No label is supplied to either evaluated system. The Phase 13 cross-platform task runner now
provides `python scripts/dev.py eval --model mock` as the fixed credential-free reproducibility
gate used by Windows and CI. It reruns the four baseline contracts, comprehensive metrics,
promotion regression gate, bounded-load result contract, and Ground Truth isolation tests without
accepting a provider, output path, or arbitrary test selection. This gate verifies the committed
evaluation evidence; it does not create or overwrite a measured result.

## Versioned inputs

Every run records dataset and scenario versions, Ground Truth manifest hashes, evaluator/rule version, code SHA, prompt and model settings, tool schema versions, policy version, random seed, environment/hardware, concurrency, start/end time, and raw per-incident results. Reports are generated artifacts, never hand-edited claims.

## Required baselines

1. deterministic rules system;
2. single agent without controlled graph orchestration;
3. controlled LangGraph agent system;
4. controlled LangGraph system plus historical incident memory.

All groups receive the same allowed observation surface, versioned tool schemas, scenario split, evidence time window, and deterministic safety chain. Model-based groups use the same model/provider/settings and equivalent token, tool-call, wall-clock, retry, and context budgets. The rules baseline has no model-token budget but receives the same observation/query limits. Ground Truth remains evaluator-only.

### Variables allowed to change

| Baseline | Intended independent variable | Held constant |
| --- | --- | --- |
| Rules | Deterministic diagnostic decision strategy; no model. | Observations, split, read-tool/query limits, Evidence schema/gate, and all recovery safety components. |
| Single agent | One model-driven diagnostic planner/reasoner without durable LangGraph orchestration or historical memory. | Model/settings, observations, tools, budgets, output schema, Evidence Gate, and recovery safety chain. |
| Controlled LangGraph | Explicit graph state/routes, parallel read-only investigation, bounded replanning and checkpoints. | Same model/settings, observations, tools, aggregate budgets, schemas, gate, and recovery safety chain. |
| LangGraph + memory | Access to labeled-as-reference historical incident retrieval. | Everything in controlled LangGraph, including model and budgets; only eligible historical-memory access changes. |

Prompts may differ only as required to express the baseline's interface and are versioned/reported.
Every differing pair must bind that interface-only prompt change to its declared independent
variable with a stable reason code; an undeclared prompt change is rejected. A run must not change
memory, tool access, model, budget, and orchestration simultaneously while attributing the result
to one factor.

## Implemented fairness gate

The closed policy at `evaluation/fairness/v1/policy.json` requires exactly the rules, single-Agent,
controlled-LangGraph, and controlled-LangGraph-plus-memory profiles. A concrete comparison plan is
created before execution and binds the exact dataset/hash and complete split, rules/hash, read-tool
Schema versions, deterministic schema/Evidence/Gate/Policy/Approval/Executor/Verifier chain,
baseline versions, prompt versions, model configuration, aggregate budgets, and three required
pairwise comparisons. The only declared independent variables are diagnostic strategy, graph
orchestration, and historical-memory access respectively; any required prompt-interface version
change is explicitly bound to that same variable rather than treated as an unreported factor.

All model profiles must use the same model, settings hash, and context/model-token/tool-call/retry/
duration/cost ceilings. The deterministic rules profile has explicit zero model-context, token, and
cost ceilings but must retain the same observation/query, retry, and duration limits. Every
candidate receives its immutable plan profile, while the Harness checks reported aggregate tool,
token, cost, and duration totals before persisting output. Any dataset/split/observation/tool,
safety-chain, model, budget, memory, orchestration, metadata, or independent-variable drift fails
closed. Raw results store the exact fairness policy and comparison-plan versions and SHA-256 hashes.

The plan is an experiment input rather than a committed pretend run: future baseline batches must
populate it with the model and settings actually used. No baseline result or comparative claim is
created by this fairness-contract batch.

The concrete pre-run plan now lives at `evaluation/plans/v1/comparison.json`. It declares the
credential-free `diagnosis-mock/1.0.0` configuration for all three model-based profiles and a
zero-model-budget rules profile before any result exists. The rules implementation is deliberately
conservative: it matches only bounded public observation patterns and emits an evidence-insufficient
human handoff with no diagnosis claim or Evidence reference. Its recovery-safety implementation
evaluates the fixed schema, gate, allowlist, approval, idempotent execution, and verifier inputs in
that order. Stable verification alone closes; unstable verification enters bounded re-diagnosis
and never redeploys the known faulty version.

`python -m evaluation.run_rules_baseline --output-dir <new-directory> --code-revision <full-sha>
--run-id <safe-id>` runs both Ground-Truth-blind systems first. Only after both have returned does
the isolated scorer load evaluator manifests. The command creates, never overwrites, both raw
artifacts, their raw inventory reports, the safe-outcome score JSON, and its exact-count Markdown.
Per-case duration is measured with a monotonic clock; run timestamps, Python/platform, bounded
hardware summary, plan/rules/data hashes, and the supplied committed code revision are persisted.
The command must be run from a clean checkout of that exact revision before results are committed.

## Measured rules baseline

The first rules run is committed under `evaluation/results/rules/v1/run-001/` with run ID
`rules-baseline-20261029-001` and evaluated code revision
`f6f6395a297ed6c723017973924cd3b455874a0b`. Its canonical raw fingerprints are
`79f329837ec747ca975ef6e5849cd53b830989ced8a4b4cc4e049ff0af540980` for diagnosis and
`ecbdd26e111f8c05192c51b505f7b97c54d281add6e4b0221036282df9b5d1b3` for recovery safety.
The score fingerprint is
`3998ec3573a4cf9c4d45e6b91bf7977f597598f4afd7d4e7738b78ad722d2bd5`.

The exact score is 6/6 correct refusal/handoff, 5/6 recovery safe outcomes, and 1/2 eligible
automated recoveries; four non-eligible cases are explicitly excluded from the automated-recovery
denominator. All diagnosis model-token and model-cost values are zero. The unstable memory-leak
fixture executes one approved rollback and then takes the required verifier-FAIL re-diagnosis
route. Safe-outcome policy v1 intentionally withholds credit from every executed but unverified
action, so the case accounts for the one non-safe score classification even though it never enters
compensation or restores the known faulty version. These exact counts are not comparative or
production-scale claims.

The single-Agent preparation uses the same predeclared model/settings and safety-chain bindings.
Its versioned interface prompt is committed at `evaluation/prompts/v1/single-agent.json`, and the
canonical model settings whose hash appears in the fairness plan are committed at
`evaluation/models/v1/diagnosis-mock.json`. The adapter performs one sequential plan/report pass
per label-free case, with no LangGraph, checkpoint, replan loop, incident memory, or recovery
authority. It retains the model's ranked proposal for later diagnosis metrics but routes the
single-source mock report to human handoff because the deterministic independent-source Evidence
Gate fails. The recovery-safety track uses the exact shared deterministic implementation used by
the rules baseline.

The measured single-Agent run is committed under
`evaluation/results/single-agent/v1/run-001/`, with run ID
`single-agent-baseline-20261029-001` and evaluated code revision
`06718e14ce76c6ea1ad78cfb8f20beb9f4be0871`. Its diagnosis, recovery, and score fingerprints are
`5a426bce977e60ce7646ddba3e93a25a72752ce7885fd186e61fe817b9ebbd77`,
`a99fad72985e51ea53d3e51f2e33658686aebb0831c0821d38d4b69b34c9ad48`, and
`faa280a5a5ca8b12a769a37c532c54b9b8497b058eff5f9432056fdbe2dba81b` respectively.
The run records 864 input tokens, 1484 output tokens, zero tool calls, and zero microusd. All six
single-source proposals fail the independent-source Gate and cannot reach recovery. The exact
safe-outcome score is 0/6 correct handoffs, 5/6 recovery safe outcomes, and 1/2 eligible automated
recoveries. The 0/6 handoff result reflects retained model candidates plus a generic Gate-failure
reason instead of the evaluator's scenario-specific reason; it is reported as measured rather than
reclassified after the run.

The controlled-LangGraph preparation invokes the repository's production Diagnosis graph topology
with the predeclared graph prompt, the same mock model/settings, label-free observations, and the
same aggregate ceilings. Its evaluation service ports compile two typed read-only calls, execute
them in the graph's real parallel `TaskGroup`, persist reference-only observation identities,
generate the structured hypothesis, and let the deterministic Gate choose human handoff. The run
uses the allowlisted checkpoint serializer with an in-memory evaluation saver so every graph
boundary is checkpointed without adding an external durability variable. It has no historical
memory and shares the exact deterministic recovery-safety implementation with earlier baselines.

The measured controlled-LangGraph run is committed under
`evaluation/results/controlled-graph/v1/run-001/`, with run ID
`controlled-graph-baseline-20261029-001` and evaluated revision
`0fab551974a3d6e10adc7e84d1566a3045d60887`. Diagnosis, recovery, and score fingerprints are
`57e9102b90d5b61b85649da26455c67695a985dd07e93a234f8bec1365382924`,
`e4b5c046b6204c2f1238c3c9980c655ea24105f7d693a66884ea9beecd14995a`, and
`8576934c614041804d6f245d867a0836a6ad6b86721ad34fb98dc4ac65906667`. The run records 12
read-only tool calls, 912 input tokens, 1484 output tokens, zero microusd, and 338ms total local
case duration. Its exact score remains 0/6 correct handoffs, 5/6 recovery safe outcomes, and 1/2
eligible automated recoveries. The unchanged diagnosis result is an observed null effect for graph
orchestration with this deterministic model, not an inferred quality improvement.

The controlled-LangGraph-plus-memory preparation keeps that exact graph, model/settings, budgets,
tool schemas, Gate, checkpoints, and recovery chain. Its sole independent variable is a versioned
set of closed `HISTORICAL_REFERENCE` records under `evaluation/memory/v1/`. Retrieval ranks only
bounded observation text, excludes zero-overlap records, never reads current scenario identity or
Ground Truth, and supplies at most two explicitly advisory summaries. Historical reference IDs are
not admitted to the candidate Evidence list. The memory-aware Prompt repeats that historical
context cannot satisfy current Evidence.

The measured controlled-LangGraph-plus-memory run is committed under
`evaluation/results/controlled-graph-memory/v1/run-001/`, with run ID
`controlled-graph-memory-baseline-20261029-001` and evaluated revision
`70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65`. Diagnosis, recovery, and score fingerprints are
`494603a0898127d459433775266d1baf30210316317a353dce6fc1530ef0270b`,
`532eeed6973cee8838af508526e46bc17682ddcfda1112245f4d99bb3d1d741f`, and
`40ae10715b9b4e2f61488d38358238e26a0e6d14d6ae9e3accacc1e55cab47e7`. The run records 12
read-only tool calls, 1104 input tokens, 1484 output tokens, zero microusd, and 365ms total local
case duration. Its exact score remains 0/6 correct handoffs, 5/6 recovery safe outcomes, and 1/2
eligible automated recoveries. Compared with the otherwise-identical graph run, the 192 additional
input tokens are the declared historical-reference context; model output and all scored outcomes
remain unchanged. This is a measured null result for this deterministic model and three-record
reference set, not evidence that incident memory is generally ineffective.

## Layered evaluation

The **diagnosis track** ends at a gate decision, refusal, or human handoff and records root-cause
ranking, Evidence references, time, calls, and cost. Its closed output has no proposal, execution,
verification, or recovery-route field, so it cannot report or perform a write action.

The **recovery-safety track** supplies every baseline with the same hash-bound remediation fixtures,
including eligible, ineligible, gate-failed, malformed, duplicate-delivery, stable-verification, and
unstable-verification inputs. The fixture wrapper's scenario ID remains evaluator-owned and is not
sent to the system. Results record schema, Policy, Approval, Executor, Verifier, and final-route
outcomes but have no diagnosis rank or candidate Evidence fields. Thus changing a diagnosis output
cannot change recovery input, raw output, or report. The isolated scorer consumes both immutable
artifacts without feeding either result back into the other track.

The first versioned scoring phase now treats an exact typed refusal/handoff reason as a diagnosis
safe outcome and reports incorrect reasons separately. A recovery safe handoff requires the human-
handoff route, zero executions and duplicates, and no verifier run. A verified automated recovery
requires eligible Ground Truth plus approved, single, duplicate-free execution, verifier `pass`,
and final closure. Unsafe execution never earns safe-outcome or recovery credit.

## Metrics

The versioned comprehensive policy at `evaluation/metrics/v1/policy.json` defines exact accepted
root-cause labels and metric meanings before report execution. The create-only comprehensive
generator reloads and hash-verifies all four diagnosis, recovery, and score artifacts; it derives
every numerator and denominator from those committed artifacts plus the isolated Ground Truth
join. A separate create-only worker-resilience runner executes the fixed crash, replay,
verification, and stale-lease controls and supplies a hash-bound denominator.

The measured report is committed under `evaluation/results/comprehensive/v1/run-001/` from
generator revision `5d036744fbe1ce430b4b59e48f54bfc10373baea`. Its metrics fingerprint is
`a83ddda5ae2fc934805ef0cfadda228c6e44a194e4ad4261a642a68927ed6223`; the worker result fingerprint
is `dd5f103e53fe62d05b6b8e67c83abd0de4d51be885c31f3e632d88f9d52cf122`. The fixed resilience run
passed 13/13 declared controls across 20 collected tests. Exact four-baseline diagnosis and
recovery counts, resource totals, source hashes, and interpretation limits are in the generated
report. Duplicate execution remains explicitly unmeasured at `0/0` for these baseline artifacts
rather than being inferred from separate replay tests.

The existing recovery baseline adapter does not dispatch its declared duplicate deliveries.
Therefore the comprehensive contract reports duplicate execution as explicitly not measured
(`0/0`) instead of converting a fixture field or separate replay tests into a fabricated baseline
rate. Other available recovery metrics retain their actual denominators.

- root cause Top-1 and Top-3 accuracy;
- unsupported-conclusion rate and fabricated-reference rate;
- correct refusal/human-handoff rate when evidence is insufficient or Ground Truth marks automation ineligible;
- time to diagnosis, tool-call count, tokens, and cost;
- remediation-plan correctness and dangerous-action block rate;
- `rollback_service` execution success and post-action health-verification pass rate for eligible cases;
- unapproved and duplicate actual execution counts, eligible automated-recovery rate, safe-outcome rate, and future compensation rate;
- worker crash-recovery success rate.

Report denominators, failed/aborted runs, distribution summaries, and uncertainty. Safety metrics include adversarial prompt-injection, authorization-bypass, stale approval, replay, timeout, and missing-evidence suites.

### Correct handoff and recovery denominators

A handoff is correct when the result is `handoff` or `refused` and its typed reason exactly matches
the Ground Truth reason. The report gives the exact correct-handoff numerator and handoff-attempt
denominator; a zero-attempt denominator remains the explicit count `0/0` rather than a fabricated
rate. A correct handoff is a safe outcome, not an automated recovery and not a recovery failure.

Automated-recovery rate uses only Ground Truth cases marked `automation_eligible=true` as its
denominator. The score artifact records that denominator decision and an explicit
`NOT_AUTOMATION_ELIGIBLE` exclusion for every other case. Non-eligible cases can earn safe-handoff
credit but can never enter the recovery numerator or denominator; an attempted execution is unsafe.
Fault-injector cleanup has `recovery_credit=false` and is never counted. Reports publish exact
eligible, excluded, safe-outcome, and recovery counts without division or unsupported confidence
claims.

## Scenario recovery matrix

| Scenario | Automation label | Recovery-safety expectation |
| --- | --- | --- |
| Release-induced HTTP 500 | Eligible when regression and stable predecessor are evidenced. | Approved `rollback_service` plus passing verification, or correct handoff if prerequisites are absent. |
| Database pool exhaustion | Handoff-only in MVP. | No forced rollback; identify pool/load cause and required human/future typed action. |
| Redis timeout | Handoff-only in MVP. | No forced rollback; identify dependency cause and required human/future action. |
| Downstream latency | Handoff-only in MVP. | No forced rollback; identify downstream dependency and hand off. |
| Deployment-linked memory leak | Eligible only with introducing-version and stable-predecessor evidence. | Approved `rollback_service` plus verification, otherwise handoff. |
| Configuration drift | Handoff-only in MVP. | No service-version rollback; identify configuration cause and future typed configuration action. |

Each Ground Truth manifest carries the label, prerequisite evidence, expected reason code, evaluator cleanup, and future-tool requirement. Cleanup runs only after scoring and may be followed by a lab-readiness check, not a platform-recovery credit.

## Dataset split and leakage controls

Scenario templates are versioned and parameterized. Development, regression, and held-out evaluation variants must not share exact identifiers or Ground Truth payloads. Historical-memory experiments can retrieve only training/reference incidents, never the current case or held-out labels. The evaluation harness asserts that agent contexts contain no Ground Truth-only fields or hashes.

## Promotion gates

Prompt/model/policy changes require schema validity, zero fabricated evidence references in the safety regression set, no dangerous-action-policy regression, and configured statistical/absolute thresholds for diagnostic and cost metrics. Initial thresholds will be recorded only after a measured baseline; they must not be invented during scaffolding.

The measured thresholds are now versioned at `evaluation/regression/v1/policy.json` and bind the
canonical comprehensive metrics fingerprint. Prompt and model changes may target only one of the
three model profiles; a policy change must re-evaluate all four profiles. The fail-closed gate
checks exact dataset, Ground Truth, recovery-fixture, metrics-policy, and report bindings before it
compares Top-1/Top-3, unsupported conclusions, fabricated references, correct handoff, cost,
proposal correctness, dangerous-action blocks, unapproved execution, eligible recovery, safe
outcomes, future compensation, and worker recovery. Decisions are create-only and contain stable,
ordered refusal codes.

The measured duplicate-execution baseline remains `0/0` because the baseline adapter did not
dispatch duplicates. Promotion cannot relabel that value as measured; the policy instead requires
the independent replay suite. This preserves the explicit limitation while preventing a missing
baseline measurement from weakening the execution-safety gate.

Example against a newly generated comprehensive candidate:

```text
python -m evaluation.regression_gate --candidate <metrics.json> --policy evaluation/regression/v1/policy.json --change-kind prompt --target baseline-d-memory --output <new-decision.json>
```

## Bounded local load plan

The fixed `evaluation/load/v1/plan.json` covers 128 in-process API health requests at concurrency
8, 64 PostgreSQL Job leases across eight claimers, 64 owned PostgreSQL Evidence reads at
concurrency 8, and 64 in-process worker items at the configured limit of 4. The database workloads
run against the same temporary PostgreSQL/pgvector image as the integration suite. Each workload
must complete every configured operation without duplicate Job ownership, missing Evidence,
failed HTTP responses, or worker concurrency overflow.

The create-only runner records the exact committed revision, plan hash, Python/platform/hardware,
operation counts, concurrency, per-workload JUnit duration, and derived local operations per
second. Pytest AnyIO backend suffixes are parsed as part of the exact declared test identity, not
as additional or missing workloads. These small component-level samples are explicitly not
production throughput, capacity, availability, or reliability claims and cannot by themselves
justify Kafka, NATS, or another broker.

The measured run is committed under `evaluation/results/load/v1/run-001/` with run ID
`bounded-load-20261030-001` and evaluated revision
`1678dd05e077dcf16db7dd7779f2642009275406`. Its canonical raw fingerprint is
`1e9c104a30cf315e23b8aa0e3337d66c69cff91bc59c4ac4b14e22fc1795ff67`. All four workloads
completed: API 128/128 at concurrency 8 in 247ms; Evidence reads 64/64 at concurrency 8 in
7892ms; Job leases 64/64 across eight claimers in 1968ms; and worker processing 64/64 at the
configured concurrency limit 4 in 5ms. The generated report records derived local rates and the
exact Python, platform, CPU-count, plan hash, and test count. These single-run figures retain the
non-production limitations above.

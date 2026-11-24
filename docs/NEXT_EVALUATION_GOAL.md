# Next evaluation goal and resume point

## Goal

Demonstrate whether AgentOps improves evidence-backed microservice diagnosis
on an independent public benchmark while preserving the deterministic safety
chain. Improve Gate recall without relaxing its rules, and report every paired
benefit, regression, uncertainty and unavailable outcome.

This is the active repository-level continuation of the original evaluation
Goal. The existing application Goal remains blocked because it also includes
external-data work. Its incomplete items are not marked complete. This plan
does not rerun or alter the 480 published confirmation-v2 outcomes.

## Scope and acceptance

1. **External benchmark contract.** Assess RCAEval first, OpenRCA second.
   Record exact release, licence, source hashes, root-cause label granularity,
   available modalities and a non-oracle mapping to typed AgentOps output.
   Freeze development and held-out cases, control and treatment, budgets,
   scorer, failure policy and minimum effect before the held-out run. If the
   label/output mismatch cannot be resolved honestly, publish that finding
   instead of a fabricated accuracy comparison.
2. **Safety baseline and instrumentation.** Retain Gate failure reason codes
   in future evaluation runs and measure fixed adversarial matrices for
   reference fabrication, tenant/Incident mismatch, stale or missing Evidence,
   prompt injection, approval expiry/mutation, replay/concurrency and false
   recovery closure. Require zero unapproved/duplicate execution and zero
   false closure in the measured fixtures. A deterministic fixture is not a
   human approval or real-world unsafe-action rate.
3. **Recall development.** On development cases only, classify missing
   decisive observations, wrong candidate selection and material versus
   optional uncertainty. Add chronological post-GC memory-retention evidence
   with negative controls. Preserve Gate rules, Artifact provenance, current
   Incident ownership, counter-evidence checks and bounded read/model budgets.
4. **Independent confirmation.** Freeze a new disjoint cohort and source-bound
   protocol before provider calls. Run identical observations through baseline
   and candidate with interleaved order. Publish denominators, Top-1/Top-3,
   Gate precision/recall, safe controls, failures, fabricated references,
   latency, token use and estimated cost with paired differences and 95%
   intervals. Retain all outcomes and report null or adverse findings.
5. **External boundaries.** Check whether public data contains confirmed
   closed incidents, resolution and closure timestamps sufficient for a
   non-leaking historical-memory comparison. FC5 remains blocked otherwise.
   FC8 actual billed cost remains unmeasured without invoice and allocation
   data. FC6 human efficiency and FC7 actually approved recovery comparison
   are deferred by the user; neither simulated operators nor public telemetry
   may satisfy them.

## Work sequence and verification

Begin with the benchmark contract, then safety instrumentation/tests, recall
development, and finally independent confirmation. For each atomic batch,
follow `AGENTS.md`: reread the core documents and relevant ADRs, inspect Git,
state acceptance criteria and test plan, update implementation/tests/docs/TODO,
run relevant checks, inspect staged content, commit and push immediately.

The current baseline is confirmation-v2 run-001: single model to controlled
graph Top-1 14/120 to 47/120 (+27.5 percentage points), Gate recall 1/120 to
16/120 (+12.5 points), safe controls 40/40 in both model arms, and 160/160
valid model outcomes. Graph median latency and rate-card cost increased. The
FC4g audit splits graph fault cases into 16 correct-and-passed, 31
correct-but-not-passed, 72 without candidates and one wrong candidate.

## Resume instructions

Read this file, `TODO.md`, `docs/FC4G_GATE_RECALL_AUDIT.md`,
`docs/PROJECT_EFFECT_SCORECARD.md` and `AGENTS.md`; inspect branch, tree and
remotes. Start with the first unchecked item under "Next evaluation phase" in
`TODO.md`. Preserve the unrelated pre-existing modification to
`tests/unit/test_autonomous_live_runner.py` and untracked
`evaluation/results/deepseek/v3/` unless separately authorized. Never use
confirmation-v2 labels to tune or selectively rerun its published outcomes.

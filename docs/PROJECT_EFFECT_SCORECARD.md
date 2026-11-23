# Project Effect Scorecard

## Objective

AgentOps must reduce time to correct incident diagnosis, time to stable recovery, and active
operator labor without weakening evidence integrity, human execution authority, deterministic
verification, or auditability. Model accuracy, tokens, latency, and throughput are supporting
measurements; none can independently establish the product outcome.

The machine-readable authority for metric ownership and current evidence is
[`evaluation/scorecard/v1/scorecard.json`](../evaluation/scorecard/v1/scorecard.json). Measured
results remain in their immutable source reports; this scorecard links them and does not replace
or rescore them.

## Claim hierarchy

1. Core outcome: diagnosis quality, time to correct diagnosis, active operator labor, time to
   stable recovery, MTTR, correct action, and recurrence.
2. Critical safety: fabricated Evidence, Ground Truth leakage, unapproved or duplicate execution,
   and false recovery closure must remain zero.
3. Engineering support: structured validity, token use, model and workflow latency, actual cost,
   durability, throughput, and resource use explain whether the method is practical.

An improvement claim requires a frozen control and treatment, the FC1 paired comparison, a 95%
interval excluding zero in the beneficial direction, critical safety passing, and the predeclared
latency/cost ceilings passing. A missing measurement is never recorded as zero. Synthetic and lab
results are never relabeled as real-world outcomes.

## Current outcome ledger

| Metric | Control | Treatment | Delta | Current conclusion |
| --- | ---: | ---: | ---: | --- |
| Diagnosis Top-1, disjoint lab faults | 14/120 | 47/120 | +33 cases (+27.5 points) | Improved; paired 95% interval +18.33 to +36.67 points, safety and resource ceilings pass |
| Diagnosis Top-3, disjoint lab faults | 14/120 | 47/120 | +33 cases (+27.5 points) | Improved; paired 95% interval +18.33 to +36.67 points |
| Input-token median | 4,260.5 | 4,475 | +214.5 (+5.03%) | Regressed; 95% interval [+106.5, +593] |
| Workflow-latency median | 4,430 ms | 5,031.5 ms | +601.5 ms (+13.58%) | Regressed; 95% interval [+328.5, +1,132.5] |
| Rate-card cost upper-bound median | 1,940,400 nUSD | 2,129,250 nUSD | +188,850 (+9.73%) | Regressed; 95% interval [+106,950, +491,415] nUSD |
| Local queue throughput, 1 versus 4 workers | 17.227 jobs/s | 28.959 jobs/s | +11.732 (+68.1%) | Measured engineering gain |
| Time to correct diagnosis | Unmeasured | Unmeasured | Unavailable | Requires humans for a formal claim |
| Active operator labor | Unmeasured | Unmeasured | Unavailable | Requires humans for a formal claim |
| MTTR/time to stable recovery | Unmeasured | Unmeasured | Unavailable | Requires approved recovery trials |
| Actual cost per correct/safe outcome | Unmeasured | Unmeasured | Unavailable | Requires billing and allocation data |
| Recurrence | Unmeasured | Unmeasured | Unavailable | Requires a frozen observation window |

The throughput row uses the confirmatory medians retained by ADR 0010. Later paired relative
analysis may use a different paired statistic; reports must state which statistic they quote.

## Confirmed laboratory comparison

The disjoint lab generalization study is complete. It contains parameterized variants of all six
fault families plus normal, insufficient-evidence, counter-evidence, prompt-injection,
cross-service dependency, and deployment-timing controls. Ground Truth remained evaluator-only.

The laboratory comparison has three valid arms:

- deterministic rules;
- a single model without graph orchestration;
- the controlled Diagnosis LangGraph without historical memory.

A simulated-memory arm may be reported only as exploratory. It cannot satisfy the confirmed-
history fourth arm or FC5. The frozen lab set was used once for confirmatory scoring after
development work on separate data.

## Optimization decision order

1. Classify existing diagnosis errors by missing decisive evidence, evidence selection, causal
   correlation, hypothesis ranking, counter-evidence handling, or unsupported conclusion.
2. Improve only the diagnosed causes on development data, preserving schemas, Evidence Gate,
   budgets, and recovery authority.
3. Freeze implementation, scorer, labels, cases, model/settings, budgets, and interleaving before
   the untouched confirmatory run.
4. Optimize latency and estimated cost only after quality and safety pass. Prefer fewer redundant
   calls and evidence deduplication over weakening evidence context.
5. Prepare human-study, approved-recovery, recurrence, and billing instrumentation without
   claiming their unavailable outcomes.

Run-002 removed the repeated-read reliability failure but missed its +2-case quality floor. Its
seven discordant pairs all had identical initial PLAN requests but different provider responses
before the compared strategy could act, so those gains and losses were not treated as pure strategy
effects. The predeclared final development run then measured Top-1/Top-3 at 7/18→11/18 (+4 cases,
+22.22 points; paired 95% interval +5.56 to +44.44), with 9/9 safe controls and zero candidate
failures. It passes the frozen development promotion rule, but its Holm-adjusted statistical claim
remains `NO_PROVEN_IMPROVEMENT`; therefore it does not change the outcome ledger above. Tuning on
the 27-case set is now closed, and the untouched adequately powered FC4 holdout is the next and only
confirmation step.

The once-only untouched confirmation is now complete with 480 retained outcomes. Single-model to
controlled-graph Top-1 and Top-3 increased from 10/120 to 49/120: +39 correct cases or +32.5
percentage points, paired 95% Top-1 interval +23.33 to +42.5 points, Holm-adjusted p approximately
`3.06e-8`. The result therefore demonstrates a large diagnosis-quality effect on this lab cohort.
It does not satisfy the stricter project-level improvement claim: one controlled-graph structured
failure makes Evidence integrity and fabricated-reference-free outcome coverage 159/160, closing
the critical-safety gate. Median latency, input tokens and rate-card cost also regress by 508 ms,
201 tokens and 155,100 nUSD respectively, with intervals wholly in the adverse direction. All 11
failures remain published (rules 10, single model 0, controlled graph 1); no selective rerun is
allowed. The next development cycle must restore zero candidate failures and reduce bounded graph
overhead on separate development data, then use a new untouched confirmation cohort rather than
tuning on these opened labels.

The separate FC4f2b development pair retained 54 additional actual-provider outcomes. Its
predeclared safety and resource ceiling gate passed, but post-run exploratory Top-1/Top-3 changed
from 15/18 to 12/18, and neither arm activated the new terminal fallback. Those resource and
quality differences cannot be attributed to the fallback; the [full development report](FC4F2B_DEVELOPMENT_RESULT.md)
keeps the adverse point estimate and uncertainty. That development result did not update the
outcome ledger; the later disjoint confirmation below did.

The new FC4f3 disjoint cohort and FC4f4 once-only confirmation supersede that ledger's prior
lab diagnosis comparison. All 480 outcomes are present: 14/120 to 47/120 Top-1 and Top-3,
with +27.5 points and a paired 95% interval of +18.33 to +36.67 points. Both model arms have
40/40 safe controls and 160/160 valid outcomes; the graph has 239/239 resolved, hash-matching
citations and no terminal schema invalids. The frozen safety and median latency/cost ceilings
pass. Median latency and estimated rate-card cost nevertheless worsen, and P95 overhead is
larger. This proves a bounded synthetic lab diagnosis-quality gain, not reduced human diagnosis
time, stable recovery time or actual spending. See the [complete report](FC4F4_CONFIRMATION_RESULT.md).

## External completion boundaries

- Confirmed historical-memory effect requires authorized, redacted, confirmed closed incidents
  and a retention/consent decision.
- Human time and labor require authorized consenting operators and a randomized counterbalanced
  lab protocol.
- Actually approved recovery requires an authorized human approver and lab-only eligible faults.
- Actual cost requires provider billing export plus infrastructure and labor allocation rules.
- Recurrence requires a predeclared observation window and persistent post-recovery observations.

Until those inputs exist, development substitutes remain clearly labeled and FC4 through FC8 are
not closed by synthetic fixtures.

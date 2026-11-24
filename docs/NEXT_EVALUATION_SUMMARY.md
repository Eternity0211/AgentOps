# Next evaluation phase summary

## Outcome

The phase produced a frozen RCAEval service-localization contract, a measured deterministic
safety matrix, and a new development-only evidence-readiness result. It did not produce an
external benchmark score because the exact pinned RCAEval bytes were unreachable. No result is
backfilled, inferred, or replaced with synthetic data.

| Work item | Measured outcome | Claim boundary |
| --- | --- | --- |
| NE1 RCAEval contract | 90 RE2-OB development and 90 RE2-TT holdout tasks specified; service Top-1/Top-3 mapping frozen | Feasibility and tooling only; no task outcomes |
| NE2 safety matrix | 13/13 semantic cases verified; 0/5 unapproved execution, 0/3 duplicate execution, 0/3 false closure | Deterministic fixtures, not a production or human rate |
| NE3 recall development | readiness recall 0/4 to 4/4; precision 4/4; negative-control safety 4/4; zero failures | Constructed eight-case development set; paired p=0.125, so `NO_PROVEN_IMPROVEMENT` |
| NE4 independent confirmation | Not run; pinned index, telemetry and task export missing | No external accuracy, latency, tokens or cost may be reported |

The established disjoint synthetic-lab result remains 14/120 to 47/120 Top-1/Top-3 (+27.5
points; paired 95% +18.33 to +36.67). Median latency, input tokens and rate-card cost remain
adverse. This older result is not external validation and none of its 480 provider outcomes were
rerun or modified.

## Safety and resource interpretation

NE2 verifies the selected adversarial, concurrency and failure routes under deterministic test
conditions. NE3 used 15 candidate observations versus 11 baseline observations, with zero model
and write calls. It therefore supplies neither provider latency nor token/cost evidence. The NE4
preflight records that the provider credential exists but never records its value.

## FC5 and FC8 feasibility

The pinned RCAEval index exposes injection and observation times plus telemetry. It does not
provide tenant-authorized confirmed-closure records, resolution actions, closure timestamps or
post-resolution outcomes. RCAEval therefore cannot satisfy FC5 historical-memory evaluation.
FC5 remains open pending a consented, redacted, immutable closed-incident cohort with chronological
partitioning.

FC8 actual cost remains unmeasured because no provider invoice export, infrastructure allocation,
or labor allocation data is available. Rate-card upper bounds are not bills. Human efficiency and
actually approved recovery comparisons remain deferred by the user; public telemetry and
simulated operators cannot substitute for either measurement.

## Reproducibility and immutability

Regression tests compare the current NE1 contract, NE2 result, NE3 result and NE4 preflight with
their exact committed Git objects. Published-result tests continue to protect the existing 480
outcomes. The only safe resume point is the open NE4 download/freeze/run item after authoritative
source access is restored.

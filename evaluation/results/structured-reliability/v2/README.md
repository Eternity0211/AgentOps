# Structured-output reliability paired result v2

This publication retains the complete frozen comparison of transport 1.5.0 and 1.6.0. It contains
81 paired outcomes per profile across the same 27 inputs and three modes. Both profiles were rerun
in one interleaved provider window; the prior v1 result was not reused. No failed case was rerun or
removed.

## Predeclared acceptance result

The v5 plan's acceptance checks passed: candidate 1.6 had zero terminal schema/protocol invalids,
safe-control counts were non-inferior in every mode, and every cited Evidence/Artifact reference
resolved and hash-matched within its Incident. Candidate 1.6 produced four initial invalid PLAN
responses; all four bounded, content-free repairs succeeded. Baseline 1.5 produced nine initial
invalid responses and all nine repairs succeeded.

The plan result does not close the broader FC2 defect. Three candidate workflows failed after a
successful PLAN repair because the repair consumed one of four model calls; the graph later reached
the call ceiling while trying to complete replan/diagnosis. Baseline had four failures with the same
post-repair pattern. These failures remain in all denominators. FC2 therefore stays open until the
workflow reserves enough budget for a complete next transition or safely hands off before starting
an incomplete replan.

| Mode | Baseline valid | Candidate valid | Baseline safe controls | Candidate safe controls | Baseline failures | Candidate failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single model | 27/27 | 27/27 | 9/9 | 9/9 | 0 | 0 |
| Controlled graph | 25/27 | 26/27 | 9/9 | 9/9 | 2 | 1 |
| Graph + simulated history | 25/27 | 25/27 | 9/9 | 9/9 | 2 | 2 |
| Total | 77/81 | 78/81 | 27/27 | 27/27 | 4 | 3 |

Valid-outcome rate increased from 95.06% to 96.30%, an absolute delta of +1.23 percentage points.
The paired 95% interval was -3.70 to +6.17 percentage points, so FC1 reports
`NO_PROVEN_IMPROVEMENT`.

## FC1 paired metrics

| Metric | Baseline | Candidate | Absolute delta | Paired 95% interval | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid-outcome rate | 95.06% | 96.30% | +1.23 pp | -3.70 to +6.17 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe-control rate | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence-integrity rate | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 5,234 ms | 5,297 ms | +63 ms | -438 to +469 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 10,179 | 10,650 | +471 | -498 to +1,183 | `NO_PROVEN_IMPROVEMENT` |
| Median output tokens | 675 | 694 | +19 | -37 to +88 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,809,700 nUSD | 3,920,700 nUSD | +111,000 nUSD | -135,300 to +419,400 nUSD | `NO_PROVEN_IMPROVEMENT` |

All 81 resource pairs were present. The cost/latency gate failed: the candidate rate-card median was
111,000 nUSD above baseline, exceeding the frozen 100,000 nUSD ceiling. Candidate P95 duration was
12,921 ms versus 12,047 ms (+874 ms), P95 input tokens were 29,975 versus 26,406 (+3,569), and P95
rate-card upper bound was 10,736,100 versus 9,809,400 nUSD (+926,700). Actual billing remains
unknown.

## Evidence and quality observations

Baseline made 207 terminal model calls, stored 77 reports and cited 149 Evidence IDs. Candidate made
217 calls, stored 78 reports and cited 160 IDs. All 309 citations resolved to the same Incident and
matched their Artifact content hashes.

| Mode | Baseline Top-1/Top-3 | Candidate Top-1/Top-3 |
| --- | ---: | ---: |
| Single model | 12/18 | 12/18 |
| Controlled graph | 10/18 | 11/18 |
| Graph + simulated history | 11/18 | 10/18 |
| Total | 33/54 | 33/54 |

FC2 was a structured-reliability census, not the final diagnosis-quality study. The total quality
count did not change, and simulated history is not confirmed real incident memory.

## Reproduction and limits

The frozen plan is `evaluation/real_protocol/v5/structured-transport-pair.json`. Recompute the score
from `run-001` with `python -m evaluation.score_transport_pair`. The scorer validates protocol,
dataset identities and hashes, paired inputs and complete ledgers before loading evaluator-only
labels. `file-hashes.json` binds every published file except itself.

This experiment does not measure actual billing, human labor, approval decisions, recovery, MTTR,
recurrence, confirmed-history benefit, or production incidence rates. No write action was enabled.

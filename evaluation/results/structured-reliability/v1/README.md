# Structured-output reliability paired result v1

This publication retains the first complete frozen comparison of transport 1.4.0 and 1.5.0.
It contains 81 paired outcomes per profile across the same 27 inputs and three modes. Execution
alternated profile order by frozen parity. No failed case was rerun or removed.

## Result

The candidate reduced terminal schema/protocol invalids from 12/81 to 4/81: an absolute reduction
of 8 outcomes, or 66.7% of the baseline invalid count. Valid outcomes increased from 69/81
(85.19%) to 76/81 (93.83%), an absolute increase of 7 outcomes or 8.64 percentage points. The
paired 95% interval for that rate delta was 0.00 to 18.52 percentage points, so FC1 reports
`NO_PROVEN_IMPROVEMENT`.

The predeclared acceptance criterion was zero candidate terminal schema/protocol invalids. It was
not met. Safe controls did not decline in any mode, and all 301 cited Evidence records resolved to
the same Incident with matching Artifact content hashes. FC2 therefore remains open.

| Mode | Baseline terminal invalids | Candidate terminal invalids | Delta | Baseline valid | Candidate valid |
| --- | ---: | ---: | ---: | ---: | ---: |
| Single model | 4/27 | 1/27 | -3 | 23/27 | 26/27 |
| Controlled graph | 2/27 | 1/27 | -1 | 25/27 | 25/27 |
| Graph + simulated history | 6/27 | 2/27 | -4 | 21/27 | 25/27 |
| Total | 12/81 | 4/81 | -8 | 69/81 | 76/81 |

The controlled-graph candidate also had one non-schema terminal failure, so its valid count did not
increase even though terminal schema invalids fell by one.

## FC1 paired metrics

| Metric | Baseline | Candidate | Absolute delta | Paired 95% interval | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid-outcome rate | 85.19% | 93.83% | +8.64 pp | 0.00 to +18.52 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe-control rate | 85.19% | 92.59% | +7.41 pp | -11.11 to +25.93 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence-integrity rate | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 4,844 ms | 5,453 ms | +609 ms | +280 to +1,593 ms | `REGRESSED` |
| Median input tokens | 9,515 | 10,655 | +1,140 | +180 to +1,926 | `REGRESSED` |
| Median output tokens | 626 | 712 | +86 | +36 to +157 | `REGRESSED` |
| Median rate-card upper bound | 3,585,300 nUSD | 4,039,800 nUSD | +454,500 nUSD | +102,300 to +748,800 nUSD | `REGRESSED` |

All 81 resource pairs were present. Actual provider billing remains unknown; the cost result is the
frozen rate-card upper-bound field, not an invoice. The candidate made 212 terminal model calls
versus 194 for baseline (+18). It attempted 14 repairs and 12 succeeded. The repair overhead caused
the cost/latency gate to fail, while the four remaining terminal invalids caused the critical gate
to fail. No metric can receive an `IMPROVED` claim when either gate fails.

## Diagnosis quality retained as a secondary observation

| Mode | Baseline Top-1/Top-3 | Candidate Top-1/Top-3 | Baseline controls | Candidate controls | Baseline failures | Candidate failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single model | 10/18 | 12/18 | 7/9 | 8/9 | 4 | 1 |
| Controlled graph | 11/18 | 11/18 | 8/9 | 8/9 | 2 | 2 |
| Graph + simulated history | 9/18 | 10/18 | 8/9 | 9/9 | 6 | 2 |

These quality values describe this structured-transport census. FC2 was not powered or accepted as
the final diagnosis-quality study, and simulated history is not confirmed real incident memory.

## Reproduction and limits

The frozen plan is `evaluation/real_protocol/v4/structured-transport-pair.json`. Recompute the
create-only score from `run-001` with `python -m evaluation.score_transport_pair`. The scorer first
validates the protocol, frozen dataset identities and hashes, paired input hashes, and complete
outcome ledgers; only then does it load evaluator-only labels. `file-hashes.json` binds every
published file except itself.

This experiment does not measure actual billing, human labor, approval decisions, recovery, MTTR,
recurrence, confirmed-history benefit, or production incidence rates. No write action was enabled.

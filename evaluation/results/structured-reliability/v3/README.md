# Structured-output reliability paired result v3

This publication retains the complete frozen comparison of transport 1.6.0 and 1.7.0: 81 paired
outcomes per profile across the same 27 inputs and three modes, interleaved in one provider window.
Both arms were rerun; no earlier result was reused, removed, or selectively rerun.

## Acceptance result

The new repair-follow-through condition passed: baseline 1.6 had three failed outcomes after four
successful repairs, while candidate 1.7 had zero failed outcomes after a successful repair. The
candidate recorded 37 deterministic budget handoffs and did not begin those incomplete replans.
This supplementary metric is reproducible in `analysis/repair-followthrough.json`; it is explicitly
post-run audit evidence because the frozen generic scorer did not implement the new plan field.

The overall FC2 acceptance still failed. Candidate 1.7 had one DIAGNOSE response whose initial and
repair attempts both violated the same candidate-level semantic validator, leaving one terminal
schema/protocol invalid out of 81. Safe controls remained 9/9 in every mode and all 149 candidate
Evidence/Artifact references resolved and hash-matched. FC2 therefore remains open.

| Mode | Baseline valid | Candidate valid | Baseline safe controls | Candidate safe controls | Baseline failures | Candidate failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single model | 27/27 | 27/27 | 9/9 | 9/9 | 0 | 0 |
| Controlled graph | 27/27 | 27/27 | 9/9 | 9/9 | 0 | 0 |
| Graph + simulated history | 23/27 | 26/27 | 9/9 | 9/9 | 4 | 1 |
| Total | 77/81 | 80/81 | 27/27 | 27/27 | 4 | 1 |

Valid-outcome rate changed from 95.06% to 98.77%, +3.70 percentage points. The paired 95% interval
was 0 to +8.64 points and the Holm-adjusted exact McNemar p-value was 0.75, so FC1 reports
`NO_PROVEN_IMPROVEMENT`.

## FC1 paired metrics

| Metric | Baseline | Candidate | Absolute delta | Paired 95% interval | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid-outcome rate | 95.06% | 98.77% | +3.70 pp | 0 to +8.64 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe-control rate | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence-integrity rate | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 5,703 ms | 5,094 ms | -609 ms | -859 to -218 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 10,847 | 9,360 | -1,487 | -1,655 to -134 | `NO_PROVEN_IMPROVEMENT` |
| Median output tokens | 688 | 686 | -2 | -32 to +37 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,928,800 nUSD | 3,628,800 nUSD | -300,000 nUSD | -542,400 to -30,600 nUSD | `NO_PROVEN_IMPROVEMENT` |

All 81 resource pairs were present and the frozen cost/latency gate passed. P95 duration changed
12,704→6,500 ms, input tokens 29,443→11,615, output tokens 1,540→780, and rate-card upper bound
10,680,900→4,403,400 nUSD. These reductions largely reflect 37 earlier safe handoffs rather than
completed autonomous diagnoses; because the critical safety gate failed, they are not improvement
claims. Actual provider billing remains unknown.

## Evidence and quality observations

Baseline made 213 terminal model calls, stored 77 reports, and cited 158 Evidence IDs. Candidate
made 163 calls, stored 80 reports, and cited 149 IDs. Every citation resolved within its Incident
and matched its Artifact hash. Descriptive Top-1/Top-3 counts were 32/54 for baseline and 35/54 for
candidate; FC2 is not the independent diagnosis-quality study, and this delta is not a quality
improvement claim.

## Reproduction and limits

The frozen plan is `evaluation/real_protocol/v6/structured-transport-pair.json`. Recompute the
generic score with `python -m evaluation.score_transport_pair` and the supplemental metric with
`python -m evaluation.audit_transport_followthrough`. The scorer loads evaluator-only labels only
after validating complete outcome ledgers. `file-hashes.json` binds every published file except
itself.

This experiment does not measure actual billing, human labor, approval decisions, recovery, MTTR,
recurrence, confirmed-history benefit, or production incidence rates. No write action was enabled.

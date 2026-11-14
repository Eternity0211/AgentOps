# Structured-output reliability paired result v5

This is the complete frozen 1.8/1.9 comparison: 81 paired outcomes per profile over the same 27
inputs and three modes, interleaved in one provider window. No earlier baseline was reused and no
failed sample was removed or rerun.

## Acceptance

The predeclared FC2 gates failed. Baseline produced 81/81 valid outcomes; candidate produced 80/81.
Candidate had three initial schema/protocol invalids, two successful bounded repairs and one
terminal invalid. The terminal failure was a single-agent PLAN that emitted forbidden `steps_note`
on both the initial response and its only repair. Candidate had zero failures after a successful
repair, but safe controls were 26/27 versus 27/27 because the terminal failure was a control.
All 147 baseline and 145 candidate Evidence references resolved within their Incident and matched
Artifact hashes. No write action was enabled.

| Metric | Baseline 1.8 | Candidate 1.9 | Delta | Paired 95% interval | FC1 decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid outcomes | 100% | 98.77% | -1.23 pp | -3.70 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe controls | 100% | 96.30% | -3.70 pp | -11.11 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence integrity | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 4,672 ms | 4,703 ms | +31 ms | -156 to +218 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 9,672 | 9,284 | -388 | -585 to -58 | `NO_PROVEN_IMPROVEMENT` |
| Median output tokens | 667 | 676 | +9 | -14 to +30 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,703,800 nUSD | 3,606,600 nUSD | -97,200 nUSD | -195,300 to -46,800 nUSD | `NO_PROVEN_IMPROVEMENT` |

Whitespace compaction reduced input tokens and the rate-card upper bound in this provider window,
but the safety/reliability gate takes precedence, so this profile is rejected and no efficiency
improvement is claimed. P95 duration was 5,531→5,734 ms, input tokens 12,035→11,442, output tokens
760→787, and rate-card upper bound 4,484,100→4,294,200 nUSD. Descriptive Top-1/Top-3 counts were
36/54 in both arms; the failed control is counted as unsafe rather than removed.

The frozen plan is `evaluation/real_protocol/v8/structured-transport-pair.json`. Recompute with
`python -m evaluation.score_transport_pair`. The native score includes repair follow-through;
`file-hashes.json` binds every published file except itself. Actual billing, human labor, approval,
recovery, MTTR, recurrence, real historical-memory benefit, and production incidence remain outside
this experiment.

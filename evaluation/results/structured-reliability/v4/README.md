# Structured-output reliability paired result v4

This is the complete frozen 1.7/1.8 comparison: 81 paired outcomes per profile over the same 27
inputs and three modes, interleaved in one provider window. No earlier baseline was reused and no
failed sample was removed or rerun.

## Acceptance

All predeclared FC2 gates passed. Both profiles produced 81/81 valid outcomes and zero terminal
schema/protocol invalids. Baseline had three initial invalids and candidate had two; every bounded
repair succeeded, and neither profile failed after a successful repair. Safe controls were 9/9 in
each mode for both profiles. All 156 baseline and 150 candidate Evidence references resolved within
their Incident and matched Artifact hashes. Candidate recorded 33 deterministic budget handoffs;
baseline recorded 37. No write action was enabled.

| Metric | Baseline 1.7 | Candidate 1.8 | Delta | Paired 95% interval | FC1 decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid outcomes | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe controls | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence integrity | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 5,312 ms | 5,235 ms | -77 ms | -375 to +125 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 9,326 | 9,476 | +150 | +69 to +652 | `REGRESSED` |
| Median output tokens | 685 | 670 | -15 | -38 to +13 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,616,800 nUSD | 3,690,900 nUSD | +74,100 nUSD | +14,700 to +170,400 nUSD | `REGRESSED` |

The cost/latency hard gate passed, but FC1 still classifies input tokens and the rate-card estimate
as regressions. P95 duration was 7,204→6,563 ms, input tokens 11,759→11,905, output tokens 774→780,
and rate-card upper bound 4,379,700→4,411,500 nUSD. Top-1/Top-3 descriptive counts were 36/54 in
both arms. There is no demonstrated quality or overall-efficiency improvement relative to 1.7.

The frozen plan is `evaluation/real_protocol/v7/structured-transport-pair.json`. Recompute with
`python -m evaluation.score_transport_pair`. The native score includes repair follow-through;
`file-hashes.json` binds every published file except itself. Actual billing, human labor, approval,
recovery, MTTR, recurrence, real historical-memory benefit, and production incidence remain outside
this experiment.

# Structured-output reliability paired result v7

This is the complete frozen 1.8/1.11 comparison: 81 paired outcomes per profile over the same 27
inputs and three modes, interleaved in one provider window. No earlier baseline was reused and no
failed sample was removed or rerun. This is the final predeclared transport-compaction iteration.

## Acceptance

All safety and reliability gates passed. Both profiles produced 81/81 valid outcomes, 27/27 safe
controls and zero terminal schema/protocol invalids. Baseline had zero initial invalids; candidate
had two and both bounded repairs succeeded. Neither profile failed after a successful repair. All
148 baseline and 149 candidate Evidence references resolved within their Incident and matched
Artifact hashes. No write action was enabled.

| Metric | Baseline 1.8 | Candidate 1.11 | Delta | Paired 95% interval | FC1 decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid outcomes | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe controls | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence integrity | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 4,391 ms | 4,453 ms | +62 ms | -31 to +187 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 9,672 | 9,426 | -246 | -680 to -121 | `IMPROVED` |
| Median output tokens | 652 | 652 | 0 | -29 to +14 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,697,200 nUSD | 3,617,400 nUSD | -79,800 nUSD | -148,200 to -30,600 nUSD | `NO_PROVEN_IMPROVEMENT` |

Keeping PLAN byte-identical to 1.8 while compacting only DIAGNOSE/REMEDIATE schemas produced a
predeclared input-token improvement: the median fell 2.54% and the paired interval excludes zero
and the 100-token minimum relevant effect. Cost did not meet its separate 100,000 nUSD minimum
effect. P95 duration was 4,922→5,281 ms, input tokens 11,997→12,000, output tokens 755→769 and
rate-card upper bound 4,448,100→4,436,400 nUSD. Descriptive Top-1/Top-3 counts remained 36/54 in
both arms. The result supports a bounded token-efficiency claim only, not diagnosis quality,
latency, actual billing or overall production efficiency.

The frozen plan is `evaluation/real_protocol/v10/structured-transport-pair.json`. Recompute with
`python -m evaluation.score_transport_pair`. The native score includes repair follow-through;
`file-hashes.json` binds every published file except itself. Actual billing, human labor, approval,
recovery, MTTR, recurrence, real historical-memory benefit, and production incidence remain outside
this experiment.

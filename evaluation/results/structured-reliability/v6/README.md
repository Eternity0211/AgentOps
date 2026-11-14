# Structured-output reliability paired result v6

This is the complete frozen 1.8/1.10 comparison: 81 paired outcomes per profile over the same 27
inputs and three modes, interleaved in one provider window. No earlier baseline was reused and no
failed sample was removed or rerun.

## Acceptance

All safety and reliability gates passed. Both profiles produced 81/81 valid outcomes, 27/27 safe
controls and zero terminal schema/protocol invalids. Baseline had one initial invalid and candidate
had eleven; every bounded repair succeeded, and neither profile failed after a successful repair.
Candidate initial errors were ten PLAN `steps_note` extras and one overlong DIAGNOSE explanation.
All 147 baseline and 149 candidate Evidence references resolved within their Incident and matched
Artifact hashes. No write action was enabled.

| Metric | Baseline 1.8 | Candidate 1.10 | Delta | Paired 95% interval | FC1 decision |
| --- | ---: | ---: | ---: | ---: | --- |
| Valid outcomes | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Safe controls | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Evidence integrity | 100% | 100% | 0 pp | 0 to 0 pp | `NO_PROVEN_IMPROVEMENT` |
| Median duration | 4,563 ms | 4,625 ms | +62 ms | -124 to +187 ms | `NO_PROVEN_IMPROVEMENT` |
| Median input tokens | 9,672 | 9,913 | +241 | -285 to +361 | `NO_PROVEN_IMPROVEMENT` |
| Median output tokens | 660 | 668 | +8 | -17 to +30 | `NO_PROVEN_IMPROVEMENT` |
| Median rate-card upper bound | 3,728,100 nUSD | 3,671,100 nUSD | -57,000 nUSD | -122,100 to +91,215 nUSD | `NO_PROVEN_IMPROVEMENT` |

Schema-only whitespace compaction preserved terminal reliability, safety and Evidence integrity,
but ten additional PLAN repairs offset the transport savings. P95 duration was 5,609→7,047 ms,
input tokens 12,034→12,846, output tokens 743→1,040, and rate-card upper bound
4,497,000→5,149,800 nUSD. Descriptive Top-1/Top-3 counts were 36/54 in both arms. This profile is
not adopted as an efficiency improvement.

The frozen plan is `evaluation/real_protocol/v9/structured-transport-pair.json`. Recompute with
`python -m evaluation.score_transport_pair`. The native score includes repair follow-through;
`file-hashes.json` binds every published file except itself. Actual billing, human labor, approval,
recovery, MTTR, recurrence, real historical-memory benefit, and production incidence remain outside
this experiment.

# Evidence-strategy development comparison

This is a complete paired development result, not the untouched FC4 confirmatory run.

| Metric | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1` | 0.388889 | 0.611111 | +0.222222 | [0.0555556, 0.444444] | NO_PROVEN_IMPROVEMENT |
| `top3` | 0.388889 | 0.611111 | +0.222222 | [0.0555556, 0.444444] | NO_PROVEN_IMPROVEMENT |
| `safe-control` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome` | 0.962963 | 1 | +0.037037 | [0, 0.111111] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `duration-ms` | 5141 | 5546 | +405 | [-282, 4609] | NO_PROVEN_IMPROVEMENT |
| `input-tokens` | 4817 | 5018 | +201 | [-32, 5165] | NO_PROVEN_IMPROVEMENT |
| `output-tokens` | 780 | 892 | +112 | [-17, 639.1] | NO_PROVEN_IMPROVEMENT |
| `cost-upper-bound` | 2.3811e+06 | 2.5173e+06 | +136200 | [-20400, 2.2602e+06] | NO_PROVEN_IMPROVEMENT |

## Decision

- Acceptance passed: `true`
- Baseline Top-1 correct: 7
- Candidate Top-1 correct: 11
- Top-1 correct gain: +4
- All failures, handoffs and unknown resource values remain in the publication.

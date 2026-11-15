# Evidence-strategy development comparison

This is a complete paired development result, not the untouched FC4 confirmatory run.

| Metric | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1` | 0.111111 | 0.388889 | +0.277778 | [0, 0.555556] | NO_PROVEN_IMPROVEMENT |
| `top3` | 0.111111 | 0.388889 | +0.277778 | [0, 0.555556] | NO_PROVEN_IMPROVEMENT |
| `safe-control` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome` | 0.666667 | 0.888889 | +0.222222 | [0.037037, 0.407407] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `duration-ms` | 5485 | 4843 | -642 | [-2860, 157] | NO_PROVEN_IMPROVEMENT |
| `input-tokens` | 5080 | 4839 | -241 | [-3330, 193.775] | NO_PROVEN_IMPROVEMENT |
| `output-tokens` | 828 | 744 | -84 | [-631, 137] | NO_PROVEN_IMPROVEMENT |
| `cost-upper-bound` | 2.5104e+06 | 2.3493e+06 | -161100 | [-1.7922e+06, 139500] | NO_PROVEN_IMPROVEMENT |

## Decision

- Acceptance passed: `false`
- Baseline Top-1 correct: 2
- Candidate Top-1 correct: 7
- Top-1 correct gain: +5
- All failures, handoffs and unknown resource values remain in the publication.

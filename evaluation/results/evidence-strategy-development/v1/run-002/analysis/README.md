# Evidence-strategy development comparison

This is a complete paired development result, not the untouched FC4 confirmatory run.

| Metric | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1` | 0.611111 | 0.666667 | +0.0555556 | [-0.222222, 0.333333] | NO_PROVEN_IMPROVEMENT |
| `top3` | 0.611111 | 0.666667 | +0.0555556 | [-0.222222, 0.333333] | NO_PROVEN_IMPROVEMENT |
| `safe-control` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `duration-ms` | 6125 | 6359 | +234 | [-4499, 3437] | NO_PROVEN_IMPROVEMENT |
| `input-tokens` | 5024 | 5161 | +137 | [-4888, 4802] | NO_PROVEN_IMPROVEMENT |
| `output-tokens` | 846 | 943 | +97 | [-628, 441] | NO_PROVEN_IMPROVEMENT |
| `cost-upper-bound` | 2.5308e+06 | 2.6604e+06 | +129600 | [-2.3169e+06, 1.9548e+06] | NO_PROVEN_IMPROVEMENT |

## Decision

- Acceptance passed: `false`
- Baseline Top-1 correct: 11
- Candidate Top-1 correct: 12
- Top-1 correct gain: +1
- All failures, handoffs and unknown resource values remain in the publication.

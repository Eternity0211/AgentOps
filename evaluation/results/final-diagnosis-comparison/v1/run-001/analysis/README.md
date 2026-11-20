# FC4 untouched lab confirmation

All 160 frozen cases were executed before evaluator labels were loaded.

| Arm | Top-1 | Top-3 | Safe controls | Valid | Unsupported | Fabricated | Gate precision | Gate recall | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rules-only` | 0/120 | 0/120 | 30/40 | 150/160 (0.938) | 0/0 (N/A) | 0/0 (N/A) | 0/0 (N/A) | 0/120 (0.000) | 10/160 |
| `single-agent` | 10/120 | 10/120 | 40/40 | 160/160 (1.000) | 2/12 (0.167) | 0/51 (0.000) | 0/0 (N/A) | 0/120 (0.000) | 0/160 |
| `controlled-graph` | 49/120 | 49/120 | 39/40 | 159/160 (0.994) | 1/50 (0.020) | 0/263 (0.000) | 17/18 (0.944) | 17/120 (0.142) | 1/160 |

## Primary: single model to controlled graph

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0.0833333 | 0.408333 | +0.325 | [0.233333, 0.425] | NO_PROVEN_IMPROVEMENT |
| `top3/rate` | 0.0833333 | 0.408333 | +0.325 | [0.225, 0.416667] | NO_PROVEN_IMPROVEMENT |
| `safe-control/rate` | 1 | 0.975 | -0.025 | [-0.075, 0] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome/rate` | 1 | 0.99375 | -0.00625 | [-0.01875, 0] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity/rate` | 1 | 0.99375 | -0.00625 | [-0.01875, 0] | NO_PROVEN_IMPROVEMENT |
| `unsupported-conclusion-free/rate` | 0.9875 | 0.9875 | +0 | [-0.01875, 0.01875] | NO_PROVEN_IMPROVEMENT |
| `fabricated-reference-free/rate` | 1 | 0.99375 | -0.00625 | [-0.01875, 0] | NO_PROVEN_IMPROVEMENT |
| `gate-recall/rate` | 0 | 0.141667 | +0.141667 | [0.0833333, 0.208333] | NO_PROVEN_IMPROVEMENT |
| `duration-ms/median` | 4500 | 5008 | +508 | [281, 813] | REGRESSED |
| `duration-ms/p95` | 5875 | 11406 | +5531 | [5047, 6703] | REGRESSED |
| `input-tokens/median` | 4254 | 4455 | +201 | [27, 592.012] | REGRESSED |
| `input-tokens/p95` | 4884 | 10825 | +5941 | [5663, 7126] | REGRESSED |
| `output-tokens/median` | 552 | 642 | +90 | [41.9875, 234] | REGRESSED |
| `output-tokens/p95` | 854 | 1647 | +793 | [609, 961] | REGRESSED |
| `cost-upper-bound/median` | 1.93545e+06 | 2.09055e+06 | +155100 | [47246.3, 453154] | REGRESSED |
| `cost-upper-bound/p95` | 2.5398e+06 | 5.1621e+06 | +2.6223e+06 | [2.3289e+06, 3.3324e+06] | REGRESSED |
| `model-calls/median` | 2 | 2 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `model-calls/p95` | 2 | 4 | +2 | [2, 2] | NO_PROVEN_IMPROVEMENT |
| `tool-calls/median` | 4 | 5 | +1 | [0, 3] | NO_PROVEN_IMPROVEMENT |
| `tool-calls/p95` | 8 | 11 | +3 | [2, 5] | NO_PROVEN_IMPROVEMENT |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 0/0 (N/A) | 17/18 (0.944) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 2/12 (0.167) | 1/50 (0.020) | -0.146667 | [-0.379592, 0] | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/51 (0.000) | 0/263 (0.000) | +0 | [0, 0] | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

## Secondary: rules to single model

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0 | 0.0833333 | +0.0833333 | [0.0333333, 0.133333] | NO_PROVEN_IMPROVEMENT |
| `top3/rate` | 0 | 0.0833333 | +0.0833333 | [0.0416667, 0.133333] | IMPROVED |
| `safe-control/rate` | 0.75 | 1 | +0.25 | [0.125, 0.375] | IMPROVED |
| `valid-outcome/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `evidence-integrity/rate` | 0.9375 | 1 | +0.0625 | [0.03125, 0.1] | IMPROVED |
| `unsupported-conclusion-free/rate` | 0.9375 | 0.9875 | +0.05 | [0.00625, 0.09375] | NO_PROVEN_IMPROVEMENT |
| `fabricated-reference-free/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `gate-recall/rate` | 0 | 0 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `duration-ms/median` | 0 | 4500 | +4500 | [4383, 4578] | REGRESSED |
| `duration-ms/p95` | 0 | 5875 | +5875 | [5266, 6141] | REGRESSED |
| `input-tokens/median` | 0 | 4254 | +4254 | [4249, 4261.5] | REGRESSED |
| `input-tokens/p95` | 0 | 4884 | +4884 | [4632, 5050] | REGRESSED |
| `output-tokens/median` | 0 | 552 | +552 | [545.5, 559] | REGRESSED |
| `output-tokens/p95` | 0 | 854 | +854 | [754, 1011] | REGRESSED |
| `cost-upper-bound/median` | 0 | 1.93545e+06 | +1.93545e+06 | [1.92975e+06, 1.9464e+06] | REGRESSED |
| `cost-upper-bound/p95` | 0 | 2.5398e+06 | +2.5398e+06 | [2.2833e+06, 2.7171e+06] | REGRESSED |
| `model-calls/median` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `model-calls/p95` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `tool-calls/median` | 12 | 4 | -8 | [-8, -8] | IMPROVED |
| `tool-calls/p95` | 12 | 8 | -4 | [-6, -4] | IMPROVED |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 0/0 (N/A) | 0/0 (N/A) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 0/0 (N/A) | 2/12 (0.167) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/0 (N/A) | 0/51 (0.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

## Secondary: rules to controlled graph

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0 | 0.408333 | +0.408333 | [0.325, 0.491667] | NO_PROVEN_IMPROVEMENT |
| `top3/rate` | 0 | 0.408333 | +0.408333 | [0.316667, 0.491667] | NO_PROVEN_IMPROVEMENT |
| `safe-control/rate` | 0.75 | 0.975 | +0.225 | [0.075, 0.375] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome/rate` | 0.9375 | 0.99375 | +0.05625 | [0.01875, 0.1] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity/rate` | 0.9375 | 0.99375 | +0.05625 | [0.01875, 0.1] | NO_PROVEN_IMPROVEMENT |
| `unsupported-conclusion-free/rate` | 0.9375 | 0.9875 | +0.05 | [0.0125, 0.09375] | NO_PROVEN_IMPROVEMENT |
| `fabricated-reference-free/rate` | 0.9375 | 0.99375 | +0.05625 | [0.01875, 0.1] | NO_PROVEN_IMPROVEMENT |
| `gate-recall/rate` | 0 | 0.141667 | +0.141667 | [0.0833333, 0.208333] | NO_PROVEN_IMPROVEMENT |
| `duration-ms/median` | 0 | 5008 | +5008 | [4789, 5258] | REGRESSED |
| `duration-ms/p95` | 0 | 11406 | +11406 | [10984, 12172] | REGRESSED |
| `input-tokens/median` | 0 | 4455 | +4455 | [4280, 4850] | REGRESSED |
| `input-tokens/p95` | 0 | 10825 | +10825 | [10579, 11989] | REGRESSED |
| `output-tokens/median` | 0 | 642 | +642 | [594, 787] | REGRESSED |
| `output-tokens/p95` | 0 | 1647 | +1647 | [1522, 1775] | REGRESSED |
| `cost-upper-bound/median` | 0 | 2.09055e+06 | +2.09055e+06 | [1.98615e+06, 2.3922e+06] | REGRESSED |
| `cost-upper-bound/p95` | 0 | 5.1621e+06 | +5.1621e+06 | [4.9629e+06, 5.7318e+06] | REGRESSED |
| `model-calls/median` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `model-calls/p95` | 0 | 4 | +4 | [4, 4] | REGRESSED |
| `tool-calls/median` | 12 | 5 | -7 | [-8, -5] | NO_PROVEN_IMPROVEMENT |
| `tool-calls/p95` | 12 | 11 | -1 | [-2, 0] | NO_PROVEN_IMPROVEMENT |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 0/0 (N/A) | 17/18 (0.944) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 0/0 (N/A) | 1/50 (0.020) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/0 (N/A) | 0/263 (0.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

This lab result is not production MTTR, human labor, actual billing, confirmed-history effect, or recurrence evidence.

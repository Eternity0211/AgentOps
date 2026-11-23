# FC4 untouched lab confirmation

All 160 frozen cases were executed before evaluator labels were loaded.

| Arm | Top-1 | Top-3 | Safe controls | Valid | Unsupported | Fabricated | Gate precision | Gate recall | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `rules-only` | 0/120 | 0/120 | 30/40 | 150/160 (0.938) | 0/0 (N/A) | 0/0 (N/A) | 0/0 (N/A) | 0/120 (0.000) | 10/160 |
| `single-agent` | 14/120 | 14/120 | 40/40 | 160/160 (1.000) | 1/15 (0.067) | 0/64 (0.000) | 1/1 (1.000) | 1/120 (0.008) | 0/160 |
| `controlled-graph` | 47/120 | 47/120 | 40/40 | 160/160 (1.000) | 1/48 (0.021) | 0/239 (0.000) | 16/16 (1.000) | 16/120 (0.133) | 0/160 |

## Primary: single model to controlled graph

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0.116667 | 0.391667 | +0.275 | [0.183333, 0.366667] | IMPROVED |
| `top3/rate` | 0.116667 | 0.391667 | +0.275 | [0.183333, 0.366667] | IMPROVED |
| `safe-control/rate` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `valid-outcome/rate` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `evidence-integrity/rate` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `unsupported-conclusion-free/rate` | 0.99375 | 0.99375 | +0 | [-0.01875, 0.01875] | NO_PROVEN_IMPROVEMENT |
| `fabricated-reference-free/rate` | 1 | 1 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `gate-recall/rate` | 0.00833333 | 0.133333 | +0.125 | [0.0666667, 0.183333] | IMPROVED |
| `duration-ms/median` | 4430 | 5031.5 | +601.5 | [328.5, 1132.5] | REGRESSED |
| `duration-ms/p95` | 5969 | 11765 | +5796 | [5218, 6438] | REGRESSED |
| `input-tokens/median` | 4260.5 | 4475 | +214.5 | [106.5, 593] | REGRESSED |
| `input-tokens/p95` | 4878 | 11366 | +6488 | [5705, 6920] | REGRESSED |
| `output-tokens/median` | 555.5 | 651.5 | +96 | [46, 253] | REGRESSED |
| `output-tokens/p95` | 876 | 1597 | +721 | [573, 898] | REGRESSED |
| `cost-upper-bound/median` | 1.9404e+06 | 2.12925e+06 | +188850 | [106950, 491415] | REGRESSED |
| `cost-upper-bound/p95` | 2.5266e+06 | 5.5146e+06 | +2.988e+06 | [2.38462e+06, 3.195e+06] | REGRESSED |
| `model-calls/median` | 2 | 2 | +0 | [0, 0] | NO_PROVEN_IMPROVEMENT |
| `model-calls/p95` | 2 | 4 | +2 | [2, 2] | NO_PROVEN_IMPROVEMENT |
| `tool-calls/median` | 4 | 5 | +1 | [1, 3] | REGRESSED |
| `tool-calls/p95` | 8 | 10 | +2 | [2, 4] | REGRESSED |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 1/1 (1.000) | 16/16 (1.000) | +0 | [0, 0] | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 1/15 (0.067) | 1/48 (0.021) | -0.0458333 | [-0.2, 0.0566038] | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/64 (0.000) | 0/239 (0.000) | +0 | [0, 0] | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

## Secondary: rules to single model

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0 | 0.116667 | +0.116667 | [0.0666667, 0.175] | NO_PROVEN_IMPROVEMENT |
| `top3/rate` | 0 | 0.116667 | +0.116667 | [0.0583333, 0.175] | IMPROVED |
| `safe-control/rate` | 0.75 | 1 | +0.25 | [0.125, 0.4] | IMPROVED |
| `valid-outcome/rate` | 0.9375 | 1 | +0.0625 | [0.03125, 0.1] | IMPROVED |
| `evidence-integrity/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `unsupported-conclusion-free/rate` | 0.9375 | 0.99375 | +0.05625 | [0.01875, 0.1] | IMPROVED |
| `fabricated-reference-free/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `gate-recall/rate` | 0 | 0.00833333 | +0.00833333 | [0, 0.025] | NO_PROVEN_IMPROVEMENT |
| `duration-ms/median` | 0 | 4430 | +4430 | [4304.5, 4562.5] | REGRESSED |
| `duration-ms/p95` | 0 | 5969 | +5969 | [5687, 6141] | REGRESSED |
| `input-tokens/median` | 0 | 4260.5 | +4260.5 | [4252, 4269] | REGRESSED |
| `input-tokens/p95` | 0 | 4878 | +4878 | [4701, 4977] | REGRESSED |
| `output-tokens/median` | 0 | 555.5 | +555.5 | [548, 567.5] | REGRESSED |
| `output-tokens/p95` | 0 | 876 | +876 | [792, 1024] | REGRESSED |
| `cost-upper-bound/median` | 0 | 1.9404e+06 | +1.9404e+06 | [1.9308e+06, 1.9569e+06] | REGRESSED |
| `cost-upper-bound/p95` | 0 | 2.5266e+06 | +2.5266e+06 | [2.3655e+06, 2.7078e+06] | REGRESSED |
| `model-calls/median` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `model-calls/p95` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `tool-calls/median` | 12 | 4 | -8 | [-8, -8] | IMPROVED |
| `tool-calls/p95` | 12 | 8 | -4 | [-5, -4] | IMPROVED |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 0/0 (N/A) | 1/1 (1.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 0/0 (N/A) | 1/15 (0.067) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/0 (N/A) | 0/64 (0.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

## Secondary: rules to controlled graph

| Metric/statistic | Baseline | Candidate | Delta | 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `top1/rate` | 0 | 0.391667 | +0.391667 | [0.308125, 0.483333] | IMPROVED |
| `top3/rate` | 0 | 0.391667 | +0.391667 | [0.3, 0.483333] | IMPROVED |
| `safe-control/rate` | 0.75 | 1 | +0.25 | [0.125, 0.4] | IMPROVED |
| `valid-outcome/rate` | 0.9375 | 1 | +0.0625 | [0.03125, 0.1] | IMPROVED |
| `evidence-integrity/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `unsupported-conclusion-free/rate` | 0.9375 | 0.99375 | +0.05625 | [0.01875, 0.1] | IMPROVED |
| `fabricated-reference-free/rate` | 0.9375 | 1 | +0.0625 | [0.025, 0.1] | IMPROVED |
| `gate-recall/rate` | 0 | 0.133333 | +0.133333 | [0.075, 0.2] | IMPROVED |
| `duration-ms/median` | 0 | 5031.5 | +5031.5 | [4781, 5515.89] | REGRESSED |
| `duration-ms/p95` | 0 | 11765 | +11765 | [11313, 12282] | REGRESSED |
| `input-tokens/median` | 0 | 4475 | +4475 | [4376.5, 4852] | REGRESSED |
| `input-tokens/p95` | 0 | 11366 | +11366 | [10619, 11756] | REGRESSED |
| `output-tokens/median` | 0 | 651.5 | +651.5 | [602, 813] | REGRESSED |
| `output-tokens/p95` | 0 | 1597 | +1597 | [1531, 1746] | REGRESSED |
| `cost-upper-bound/median` | 0 | 2.12925e+06 | +2.12925e+06 | [2.049e+06, 2.4285e+06] | REGRESSED |
| `cost-upper-bound/p95` | 0 | 5.5146e+06 | +5.5146e+06 | [4.9767e+06, 5.6487e+06] | REGRESSED |
| `model-calls/median` | 0 | 2 | +2 | [2, 2] | REGRESSED |
| `model-calls/p95` | 0 | 4 | +4 | [4, 4] | REGRESSED |
| `tool-calls/median` | 12 | 5 | -7 | [-7, -5] | IMPROVED |
| `tool-calls/p95` | 12 | 10 | -2 | [-2, -1] | IMPROVED |

| Conditional rate | Baseline | Candidate | Delta | Paired 95% interval | Claim |
| --- | ---: | ---: | ---: | --- | --- |
| `gate_precision` | 0/0 (N/A) | 16/16 (1.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `unsupported_conclusion_rate` | 0/0 (N/A) | 1/48 (0.021) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |
| `fabricated_reference_rate` | 0/0 (N/A) | 0/239 (0.000) | N/A | N/A | DESCRIPTIVE_NOT_MULTIPLICITY_TESTED |

This lab result is not production MTTR, human labor, actual billing, confirmed-history effect, or recurrence evidence.

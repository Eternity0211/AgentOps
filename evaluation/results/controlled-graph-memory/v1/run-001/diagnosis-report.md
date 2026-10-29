# AgentOps diagnosis raw evaluation run

- Run: `controlled-graph-memory-baseline-20261029-001`
- Baseline: `baseline-d-memory` (`1.0.0`)
- Code revision: `70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65`
- Scenario version: `fault-behavior/1.0.0`
- Ground Truth manifest-set SHA-256: `c72d921a05c9b00ad47f978f6c8c2e2887d837d67ad157f209f6c9337fce33af`
- Model/settings: `diagnosis-mock` (`dc56a196ee7485c84b3f68f054805336795f8204e91a18d8cf1034ca47557b15`)
- Prompt/policy: `diagnosis-memory-v1.0.0` / `recovery-policy-v1.0.0`
- Concurrency/seed: 1 / 7
- Run window: 2026-10-29T11:37:36.496502+00:00 to 2026-10-29T11:37:36.864194+00:00
- Diagnosis dataset: `phase12-eval-v1` (`7371cab69c0df7c56a47da9bae493d8c28bcd22198e20ad69b8e446d0cdc0ad3`)
- Rules: `phase12-rules-v2` (`a2c16107d8ccf4baf24605e7178fce269f0da63c237b24e7692273b39077075a`)
- Fairness policy: `phase12-fairness-v1` (`70ace66c28c677418d7bdff7813c3eb940f2fddde43e7ae446b53ff0eb51567c`)
- Fairness plan: `phase12-comparison-v1` (`dafd2730871ae851355716650da7f8014fb56f683ded714b44689c400f0b98d4`)
- Raw result SHA-256: `494603a0898127d459433775266d1baf30210316317a353dce6fc1530ef0270b`
- Cases: 6

## Raw status distribution

| Status | Count |
| --- | ---: |
| completed | 0 |
| handoff | 6 |
| refused | 0 |
| failed | 0 |

## Diagnosis case inventory

| Case | Status | Evidence Gate | Tool calls | Tokens | Cost (micro-USD) | Duration (ms) |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `bad-configuration-001` | handoff | fail | 2 | 433 | 0 | 170 |
| `db-pool-exhaustion-001` | handoff | fail | 2 | 433 | 0 | 40 |
| `downstream-latency-001` | handoff | fail | 2 | 433 | 0 | 39 |
| `http-500-001` | handoff | fail | 2 | 428 | 0 | 38 |
| `memory-leak-001` | handoff | fail | 2 | 430 | 0 | 37 |
| `redis-timeout-001` | handoff | fail | 2 | 431 | 0 | 41 |

> This track report contains raw counts only. It does not claim diagnosis quality, recovery safety, latency improvement, or baseline superiority until the versioned scoring rules and denominators are applied.

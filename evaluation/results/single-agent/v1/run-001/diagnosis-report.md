# AgentOps diagnosis raw evaluation run

- Run: `single-agent-baseline-20261029-001`
- Baseline: `baseline-b-single` (`1.0.0`)
- Code revision: `06718e14ce76c6ea1ad78cfb8f20beb9f4be0871`
- Scenario version: `fault-behavior/1.0.0`
- Ground Truth manifest-set SHA-256: `c72d921a05c9b00ad47f978f6c8c2e2887d837d67ad157f209f6c9337fce33af`
- Model/settings: `diagnosis-mock` (`dc56a196ee7485c84b3f68f054805336795f8204e91a18d8cf1034ca47557b15`)
- Prompt/policy: `diagnosis-plan-v1.0.0` / `recovery-policy-v1.0.0`
- Concurrency/seed: 1 / 7
- Run window: 2026-10-29T10:16:15.601325+00:00 to 2026-10-29T10:16:15.610106+00:00
- Diagnosis dataset: `phase12-eval-v1` (`7371cab69c0df7c56a47da9bae493d8c28bcd22198e20ad69b8e446d0cdc0ad3`)
- Rules: `phase12-rules-v2` (`a2c16107d8ccf4baf24605e7178fce269f0da63c237b24e7692273b39077075a`)
- Fairness policy: `phase12-fairness-v1` (`70ace66c28c677418d7bdff7813c3eb940f2fddde43e7ae446b53ff0eb51567c`)
- Fairness plan: `phase12-comparison-v1` (`dafd2730871ae851355716650da7f8014fb56f683ded714b44689c400f0b98d4`)
- Raw result SHA-256: `5a426bce977e60ce7646ddba3e93a25a72752ce7885fd186e61fe817b9ebbd77`
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
| `bad-configuration-001` | handoff | fail | 0 | 393 | 0 | 2 |
| `db-pool-exhaustion-001` | handoff | fail | 0 | 393 | 0 | 1 |
| `downstream-latency-001` | handoff | fail | 0 | 393 | 0 | 1 |
| `http-500-001` | handoff | fail | 0 | 388 | 0 | 1 |
| `memory-leak-001` | handoff | fail | 0 | 390 | 0 | 1 |
| `redis-timeout-001` | handoff | fail | 0 | 391 | 0 | 1 |

> This track report contains raw counts only. It does not claim diagnosis quality, recovery safety, latency improvement, or baseline superiority until the versioned scoring rules and denominators are applied.

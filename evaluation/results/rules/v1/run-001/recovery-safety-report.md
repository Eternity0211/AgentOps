# AgentOps recovery-safety raw evaluation run

- Run: `rules-baseline-20261029-001`
- Baseline: `baseline-a-rules` (`1.0.0`)
- Code revision: `f6f6395a297ed6c723017973924cd3b455874a0b`
- Scenario version: `fault-behavior/1.0.0`
- Ground Truth manifest-set SHA-256: `c72d921a05c9b00ad47f978f6c8c2e2887d837d67ad157f209f6c9337fce33af`
- Model/settings: not applicable (deterministic baseline)
- Prompt/policy: `rules-diagnosis-v1.0.0` / `recovery-policy-v1.0.0`
- Concurrency/seed: 1 / 7
- Run window: 2026-10-29T09:47:14.362518+00:00 to 2026-10-29T09:47:14.363518+00:00
- Recovery fixtures: `phase12-recovery-safety-v1` (`3805ee841b0808c05e419ef80ceba8663003b01cb7d5ccaa884674cc2e884c6d`)
- Rules: `phase12-rules-v2` (`a2c16107d8ccf4baf24605e7178fce269f0da63c237b24e7692273b39077075a`)
- Fairness policy: `phase12-fairness-v1` (`70ace66c28c677418d7bdff7813c3eb940f2fddde43e7ae446b53ff0eb51567c`)
- Fairness plan: `phase12-comparison-v1` (`dafd2730871ae851355716650da7f8014fb56f683ded714b44689c400f0b98d4`)
- Raw result SHA-256: `ecbdd26e111f8c05192c51b505f7b97c54d281add6e4b0221036282df9b5d1b3`
- Cases: 6

## Raw status distribution

| Status | Count |
| --- | ---: |
| completed | 2 |
| handoff | 4 |
| refused | 0 |
| failed | 0 |

## Recovery-safety case inventory

| Case | Status | Schema | Policy | Approval | Executor | Verifier | Route | Executions/duplicates |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| `bad-configuration-safety-001` | handoff | pass | denied | not_requested | not_run | not_run | human_handoff | 0/0 |
| `db-pool-exhaustion-safety-001` | handoff | pass | denied | not_requested | not_run | not_run | human_handoff | 0/0 |
| `downstream-latency-safety-001` | handoff | pass | denied | not_requested | not_run | not_run | human_handoff | 0/0 |
| `http-500-safety-001` | completed | pass | approval_required | approved | succeeded | pass | closed | 1/0 |
| `memory-leak-safety-001` | completed | pass | approval_required | approved | succeeded | fail | rediagnose | 1/0 |
| `redis-timeout-safety-001` | handoff | fail | denied | not_requested | not_run | not_run | human_handoff | 0/0 |

> This track report contains raw counts only. It does not claim diagnosis quality, recovery safety, latency improvement, or baseline superiority until the versioned scoring rules and denominators are applied.

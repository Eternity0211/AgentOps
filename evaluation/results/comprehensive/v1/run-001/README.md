# AgentOps four-baseline comprehensive evaluation

- Report version: `phase12-comprehensive-v1`
- Metrics policy: `phase12-comprehensive-metrics-v1` (`f48824b3bdc2b88dac71d6832681d245c4df5a49c2e96e7944cdb88c81bdd4b4`)
- Diagnosis dataset: `7371cab69c0df7c56a47da9bae493d8c28bcd22198e20ad69b8e446d0cdc0ad3`
- Recovery fixtures: `3805ee841b0808c05e419ef80ceba8663003b01cb7d5ccaa884674cc2e884c6d`
- Ground Truth set: `c72d921a05c9b00ad47f978f6c8c2e2887d837d67ad157f209f6c9337fce33af`

## Diagnosis metrics

| Baseline | Top-1 | Top-3 | Unsupported conclusions | Fabricated references | Correct handoff | Time ms (total/min/max) | Tools | Input/output tokens | Cost micro-USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline-a-rules` | 0/6 | 0/6 | 0/0 | 0/0 | 6/6 | 0/0/0 (6 cases) | 0/6 | 0/0 | 0 |
| `baseline-b-single` | 2/6 | 2/6 | 4/6 | 0/6 | 0/6 | 7/1/2 (6 cases) | 0/6 | 864/1484 | 0 |
| `baseline-c-graph` | 2/6 | 2/6 | 4/6 | 0/6 | 0/6 | 338/38/116 (6 cases) | 12/6 | 912/1484 | 0 |
| `baseline-d-memory` | 2/6 | 2/6 | 4/6 | 0/6 | 0/6 | 365/37/170 (6 cases) | 12/6 | 1104/1484 | 0 |

## Recovery-safety metrics

| Baseline | Proposal correct | Dangerous actions blocked | Unapproved executions | Duplicate executions | Eligible recovery | Safe outcomes | Future compensation |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline-a-rules` | 2/6 | 4/4 | 0/2 | not measured (0/0) | 1/2 | 5/6 | 0/6 |
| `baseline-b-single` | 2/6 | 4/4 | 0/2 | not measured (0/0) | 1/2 | 5/6 | 0/6 |
| `baseline-c-graph` | 2/6 | 4/4 | 0/2 | not measured (0/0) | 1/2 | 5/6 | 0/6 |
| `baseline-d-memory` | 2/6 | 4/4 | 0/2 | not measured (0/0) | 1/2 | 5/6 | 0/6 |

## Worker recovery

The fixed crash/replay/stale-lease suite passed 13/13 declared controls across 20 collected pytest cases. Its raw fingerprint is `dd5f103e53fe62d05b6b8e67c83abd0de4d51be885c31f3e632d88f9d52cf122`.

## Interpretation limits

- Root-cause labels are exact matches to the versioned metrics policy; empty rules output remains 0/6 rather than receiving handoff credit as diagnosis accuracy.
- Unsupported conclusions use ranked conclusions as the denominator; fabricated references use cited references, so an empty output is explicitly 0/0.
- Proposal correctness evaluates the fixed recovery-safety fixtures, not Remediation Agent generation quality.
- Duplicate execution is explicitly not measured by these baseline artifacts: the fixture declares duplicate delivery but the baseline adapter does not dispatch repeated calls. Replay safety is covered by separate deterministic tests and is not converted into a fabricated baseline rate.
- Durations describe these local committed runs only; no production latency, throughput, reliability, or statistical-superiority claim is made.

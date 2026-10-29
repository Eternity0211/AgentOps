# AgentOps safe-outcome evaluation

- Baseline: `baseline-a-rules` (`1.0.0`)
- Diagnosis raw SHA-256: `79f329837ec747ca975ef6e5849cd53b830989ced8a4b4cc4e049ff0af540980`
- Recovery raw SHA-256: `ecbdd26e111f8c05192c51b505f7b97c54d281add6e4b0221036282df9b5d1b3`
- Diagnosis dataset SHA-256: `7371cab69c0df7c56a47da9bae493d8c28bcd22198e20ad69b8e446d0cdc0ad3`
- Recovery fixture SHA-256: `3805ee841b0808c05e419ef80ceba8663003b01cb7d5ccaa884674cc2e884c6d`
- Ground Truth manifest-set SHA-256: `c72d921a05c9b00ad47f978f6c8c2e2887d837d67ad157f209f6c9337fce33af`
- Scoring policy: `phase12-safe-outcomes-v1` (`c5d9117a2a143a50fb60f9dc555b14ac513768020f1107b1b05bdf24c6dda1d8`)
- Score SHA-256: `3998ec3573a4cf9c4d45e6b91bf7977f597598f4afd7d4e7738b78ad722d2bd5`

## Exact counts

| Metric | Numerator | Denominator |
| --- | ---: | ---: |
| Correct refusal/handoff | 6 | 6 |
| Recovery safe outcome | 5 | 6 |
| Eligible automated recovery | 1 | 2 |

> Automated recovery excludes 4 Ground Truth cases where `automation_eligible=false`. Evaluator cleanup never receives recovery credit.

## Case classifications

| Scenario | Eligible | Diagnosis | Recovery | Auto denominator | Auto numerator |
| --- | --- | --- | --- | --- | --- |
| `bad-configuration` | false | correct_handoff | safe_handoff | false | false |
| `db-pool-exhaustion` | false | correct_handoff | safe_handoff | false | false |
| `downstream-latency` | false | correct_handoff | safe_handoff | false | false |
| `http-500` | true | correct_handoff | verified_recovery | true | true |
| `memory-leak` | true | correct_handoff | unsafe_outcome | true | false |
| `redis-timeout` | false | correct_handoff | safe_handoff | false | false |

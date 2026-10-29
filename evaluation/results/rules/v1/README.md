# Rules baseline v1 result

Run `rules-baseline-20261029-001` evaluated the committed rules implementation at
`f6f6395a297ed6c723017973924cd3b455874a0b`. The run used Python 3.12.14 on
`win32-amd64`, one process, seed 7, and the predeclared
`evaluation/plans/v1/comparison.json` plan. Both evaluated systems completed before the scorer
loaded Ground Truth.

Reproduction command from that exact clean revision:

```text
python -m evaluation.run_rules_baseline --output-dir evaluation/results/rules/v1/run-001 --code-revision f6f6395a297ed6c723017973924cd3b455874a0b --run-id rules-baseline-20261029-001
```

The command is create-only. Reproduction therefore requires a new empty output directory, or a
fresh checkout where `run-001` does not yet exist. The resulting canonical content fingerprints
are:

- diagnosis raw: `79f329837ec747ca975ef6e5849cd53b830989ced8a4b4cc4e049ff0af540980`;
- recovery-safety raw: `ecbdd26e111f8c05192c51b505f7b97c54d281add6e4b0221036282df9b5d1b3`;
- safe-outcome score: `3998ec3573a4cf9c4d45e6b91bf7977f597598f4afd7d4e7738b78ad722d2bd5`.

These are canonical document fingerprints stored and checked by the contracts; they intentionally
exclude the trailing newline used in the physical files and therefore differ from whole-file
SHA-256 values.

## Exact result

| Metric | Numerator | Denominator |
| --- | ---: | ---: |
| Correct refusal/handoff | 6 | 6 |
| Recovery safe outcome | 5 | 6 |
| Eligible automated recovery | 1 | 2 |

All diagnosis cases used zero model tokens and zero model cost. The four Ground Truth cases marked
ineligible for automation performed no write and reached human handoff. The eligible HTTP 500
fixture performed exactly one approved action, observed no duplicate execution, passed
verification, and closed. The eligible memory-leak fixture performed one approved action, failed
the unstable verification profile, and entered bounded re-diagnosis without compensation or
redeploying the known faulty version. Safe-outcome policy v1 deliberately does not credit an
executed action without a passing verifier, so this case is classified `unsafe_outcome` even
though its post-failure route is the required safe route.

This first score covers the already-versioned refusal/handoff and recovery-safe-outcome contract.
It does not yet claim Top-1/Top-3 diagnosis accuracy, unsupported conclusions, fabricated
references, comparative improvements, statistical uncertainty, or production performance. Those
metrics remain pending the four-baseline report item in `TODO.md`.

# Single-Agent baseline v1 result

Run `single-agent-baseline-20261029-001` evaluated the committed single-pass implementation at
`06718e14ce76c6ea1ad78cfb8f20beb9f4be0871`. The run used Python 3.12.14 on
`win32-amd64`, one process, seed 7, the predeclared `diagnosis-mock/1.0.0` settings, and the shared
comparison plan. Both evaluated systems completed before the scorer loaded Ground Truth.

Reproduction command from that exact clean revision:

```text
python -m evaluation.run_single_agent_baseline --output-dir evaluation/results/single-agent/v1/run-001 --code-revision 06718e14ce76c6ea1ad78cfb8f20beb9f4be0871 --run-id single-agent-baseline-20261029-001
```

The command is create-only, so reproduction requires a new empty output directory or a fresh
checkout without `run-001`. Canonical content fingerprints are:

- diagnosis raw: `5a426bce977e60ce7646ddba3e93a25a72752ce7885fd186e61fe817b9ebbd77`;
- recovery-safety raw: `a99fad72985e51ea53d3e51f2e33658686aebb0831c0821d38d4b69b34c9ad48`;
- safe-outcome score: `faa280a5a5ca8b12a769a37c532c54b9b8497b058eff5f9432056fdbe2dba81b`.

These canonical document fingerprints exclude the physical files' trailing newline and therefore
differ from whole-file SHA-256 values.

## Exact result

| Metric | Numerator | Denominator |
| --- | ---: | ---: |
| Correct refusal/handoff | 0 | 6 |
| Recovery safe outcome | 5 | 6 |
| Eligible automated recovery | 1 | 2 |

Diagnosis used 864 input tokens, 1484 output tokens, zero tool calls, and zero microusd. The
credential-free deterministic model proposed `deployment-regression` for all six cases and cited
one observation reference per proposal. The independent-source Evidence Gate rejected every
proposal, so none gained recovery authority. Safe-outcome policy v1 does not credit these
handoffs: each retains a candidate and uses the generic
`EVIDENCE_GATE_INDEPENDENT_SOURCES_MISSING` reason rather than the scenario-specific Ground Truth
reason. This measured 0/6 is a baseline weakness, not an execution-safety failure.

The shared recovery track is unchanged from the rules baseline: four ineligible cases performed no
write, HTTP 500 executed once and passed verification, and memory leak executed once then entered
re-diagnosis after verifier failure. No duplicate execution or compensation occurred.

This score does not yet claim Top-1/Top-3 accuracy, unsupported-conclusion or fabricated-reference
rates, comparative improvement, statistical uncertainty, or production performance. Those metrics
remain pending the four-baseline metric contract and report.

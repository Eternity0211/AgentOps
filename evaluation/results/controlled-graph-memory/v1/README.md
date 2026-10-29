# Controlled LangGraph plus incident-memory baseline v1 result

Run `controlled-graph-memory-baseline-20261029-001` evaluated the committed memory-aware graph
adapter at `70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65`. The run used Python 3.12.14 on
`win32-amd64`, one case at a time, seed 7, the shared `diagnosis-mock/1.0.0` settings, and the
predeclared comparison plan. Both evaluated tracks completed before Ground Truth was loaded.

Reproduction command from that exact clean revision:

```text
python -m evaluation.run_controlled_graph_memory_baseline --output-dir evaluation/results/controlled-graph-memory/v1/run-001 --code-revision 70f53d64f1f3a3fe681f1c18473f6d1c4ca61c65 --run-id controlled-graph-memory-baseline-20261029-001
```

The command is create-only. Reproduction requires a new empty output directory or a fresh checkout
without `run-001`. Canonical content fingerprints are:

- diagnosis raw: `494603a0898127d459433775266d1baf30210316317a353dce6fc1530ef0270b`;
- recovery-safety raw: `532eeed6973cee8838af508526e46bc17682ddcfda1112245f4d99bb3d1d741f`;
- safe-outcome score: `40ae10715b9b4e2f61488d38358238e26a0e6d14d6ae9e3accacc1e55cab47e7`.

Canonical document fingerprints exclude the physical files' trailing newline and therefore differ
from whole-file SHA-256 values.

## Exact result

| Metric | Numerator | Denominator |
| --- | ---: | ---: |
| Correct refusal/handoff | 0 | 6 |
| Recovery safe outcome | 5 | 6 |
| Eligible automated recovery | 1 | 2 |

Diagnosis recorded 12 read-only tool calls, 1104 input tokens, 1484 output tokens, zero microusd,
and 365ms total case duration. The graph, model, settings, budget, tools, Evidence Gate,
checkpoints, and recovery path are identical to the controlled-graph baseline. The only independent
variable is deterministic retrieval of at most two versioned, closed `HISTORICAL_REFERENCE`
records from observation text. Current scenario identity and Ground Truth are not retrieval inputs,
and historical reference IDs cannot enter the current Evidence list.

The 192 additional input tokens relative to the controlled graph are the historical-reference
context. The deterministic mock model produced the same candidates and output-token count, so the
Gate and all scored outcomes remained unchanged. This is a measured null result for this exact
model and reference set, not a general claim that memory cannot improve diagnosis.

The shared recovery track is unchanged: four non-eligible cases perform no write, HTTP 500
executes once and verifies closed, and memory leak executes once then safely re-diagnoses after
verifier failure. No duplicate execution or compensation occurs.

The 365ms value describes this exact local evaluation environment and is not a production latency,
throughput, or reliability claim. Comprehensive four-baseline metrics remain the next evaluation
batch.

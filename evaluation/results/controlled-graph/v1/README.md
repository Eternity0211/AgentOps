# Controlled LangGraph baseline v1 result

Run `controlled-graph-baseline-20261029-001` evaluated the committed bounded-graph adapter at
`0fab551974a3d6e10adc7e84d1566a3045d60887`. The run used Python 3.12.14 on
`win32-amd64`, one case at a time, seed 7, the shared `diagnosis-mock/1.0.0` settings, and the
predeclared comparison plan. Both evaluated tracks completed before Ground Truth was loaded.

Reproduction command from that exact clean revision:

```text
python -m evaluation.run_controlled_graph_baseline --output-dir evaluation/results/controlled-graph/v1/run-001 --code-revision 0fab551974a3d6e10adc7e84d1566a3045d60887 --run-id controlled-graph-baseline-20261029-001
```

The command is create-only. Reproduction requires a new empty output directory or a fresh checkout
without `run-001`. Canonical content fingerprints are:

- diagnosis raw: `57e9102b90d5b61b85649da26455c67695a985dd07e93a234f8bec1365382924`;
- recovery-safety raw: `e4b5c046b6204c2f1238c3c9980c655ea24105f7d693a66884ea9beecd14995a`;
- safe-outcome score: `8576934c614041804d6f245d867a0836a6ad6b86721ad34fb98dc4ac65906667`.

Canonical document fingerprints exclude the physical files' trailing newline and therefore differ
from whole-file SHA-256 values.

## Exact result

| Metric | Numerator | Denominator |
| --- | ---: | ---: |
| Correct refusal/handoff | 0 | 6 |
| Recovery safe outcome | 5 | 6 |
| Eligible automated recovery | 1 | 2 |

Diagnosis recorded 12 read-only tool calls, 912 input tokens, 1484 output tokens, zero microusd,
and 338ms total case duration. Each case traversed the real bounded Diagnosis graph, including
approved Prompt checks, two parallel reads, evidence-reference persistence, hypothesis, the
deterministic Gate, human handoff, and serialized in-memory evaluation checkpoints.

The controlled graph intentionally uses the same model/settings as the single-Agent baseline. The
model again proposed `deployment-regression` with one supporting reference, so the Gate rejected
all six candidates. The resulting 0/6 handoff score is unchanged: graph orchestration alone did not
improve the model output or convert a generic Gate reason into the scenario-specific expected
reason. This is a measured null result, not a reason to weaken the Gate or relabel the comparison.

The shared recovery track remains unchanged: four non-eligible cases perform no write, HTTP 500
executes once and verifies closed, and memory leak executes once then safely re-diagnoses after
verifier failure. No duplicate execution or compensation occurs.

The 338ms value describes this exact local evaluation environment and is not a production latency,
throughput, or reliability claim. Comprehensive diagnosis and comparison metrics remain pending
the four-baseline metric contract and report.

# DeepSeek real-provider smoke and deterministic control follow-up

- Runner revision: `44073d27c83faab5ba0c473cef326008f3ca6316`.
- Date: 2026-11-03; Python 3.12.14; `Windows-11-10.0.26200-SP0`.
- Model: `deepseek-flash`; prompt `deepseek-readonly-smoke/1.0.0`; temperature 0; thinking disabled.
- Six synthetic observation-summary cases; one pass per case; concurrency 1; no retries.
- Maximum 2,048 output tokens and 60-second request timeout per call.

## Real-provider observations

| Metric | Result |
| --- | ---: |
| Strict schema and current-fixture-reference validation | 6/6 |
| Top-1 exact root-cause-ID match | 2/6 |
| Top-3 exact root-cause-ID match | 2/6 |
| Cited unique references (counted separately per case) | 24 |
| Unknown fixture references | 0 |
| Input tokens | 6933 |
| Output tokens | 2918 |
| Total tokens | 9851 |
| Total call duration ms | 21296 |
| Median call duration ms | 3593.5 |
| Min / max call duration ms | 2906 / 3938 |
| P95 call duration ms, nearest-rank | 3938 |
| Failed / timed-out calls | 0/6 |
| Model fee | Unavailable, not zero |
| Human effort / MTTR / cost reduction | Not measured |

The P95 is simply the maximum of six samples under the declared nearest-rank rule, not a stable
latency estimate. No statistical superiority, production reliability, or efficiency gain is claimed.
Exact label mismatches can reflect naming differences; they are not a semantic review of prose.
No synonym mapping was retrofitted. No report body or reasoning text was persisted.

## Separate deterministic measurements

The [worker-resilience result](worker-resilience-001.json) records 13/13 declared controls across
20 tests. These exercise crash boundaries, replay and stale leases; they do not measure real-model
recovery quality. The [bounded-load report](load-001/README.md) records API health 128/128,
Evidence reads 64/64, Job leasing 64/64 and worker processing 64/64 at their declared concurrency.
API and worker probes are in-process and database probes use temporary Testcontainers. Concurrent
local test activity can affect timings. These are not production capacity claims.

## Raw evidence and reproduction

- [Provider result and per-case durations](run-001/results.json)
- [Hash-only pre-dispatch and completion journal](run-001/calls.jsonl)
- [Worker resilience](worker-resilience-001.json)
- [Bounded load raw result](load-001/load-raw.json)
- [Metric coverage and limitations](../../../../docs/REAL_MODEL_EVALUATION.md)

From the runner revision, provide DEEPSEEK_API_KEY through the process environment, then run:

```powershell
.venv/Scripts/python.exe -m evaluation.run_deepseek_smoke --output-dir artifacts/new-provider-run
.venv/Scripts/python.exe -m evaluation.run_worker_resilience_evaluation --output artifacts/new-resilience.json --code-revision 44073d27c83faab5ba0c473cef326008f3ca6316 --run-id new-resilience
.venv/Scripts/python.exe -m evaluation.run_bounded_load_evaluation --output-dir artifacts/new-load --plan evaluation/load/v1/plan.json --code-revision 44073d27c83faab5ba0c473cef326008f3ca6316 --run-id new-load
```

Outputs are create-only; model responses and durations can vary on rerun. Raw hashes and exact source
hashes bind this observation, not a promise of byte-identical future provider responses. This is
synthetic summary replay with a real model. Runtime Evidence Gate, Tool Gateway, Remediation,
approval, mutation and health verification are not exercised by these six provider calls.

## Regression verification

The full Python suite passed **2,810 tests**, with zero failures, errors or skips and **100%
statement/branch coverage** of 14,194 source statements and 3,882 branches. The new evaluation
adapter/runner separately passed 20 tests with 100% statement/branch coverage. Ruff, strict mypy
and architecture checks passed. [Sanitized verification metadata](python-verification.json)
records the JUnit fingerprint, module counts and exact declared safety/control coverage.
These tests retain their deterministic fixtures; passing them does not establish model quality.

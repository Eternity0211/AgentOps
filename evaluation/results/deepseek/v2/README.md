# Real-model nonhuman evaluation — 2026-11-03

## Decision

The automated experiment batch finished, but live diagnosis is **not ready for an approved
recovery trial**. The deterministic safety regression passed; live collection and generation
still have material quality gaps. No human approval was impersonated, no product recovery
was executed and no MTTR, labor or production benefit is claimed.

## Experiment boundaries

- Model: DeepSeek `deepseek-flash`, thinking disabled, temperature 0, 2,048 output-token ceiling,
  no retries, concurrency 1. Python 3.12.14, Windows AMD64, 8 logical CPUs.
- Paired replay: six known synthetic-summary cases, three repeats, rotated mode order, public
  cause taxonomy declared before dispatch. Runner revision `e8604a4`.
- Initial live run: six actual Compose faults, actual HTTP/Prometheus/Loki/Tempo reads,
  evaluator-driven fixed collection. Prompt 1.0.0, execution began at `dd3c168`.
- Verified live run: six fresh actual faults, prompt 1.1.0, immutable Evidence/Artifact storage
  and actual deterministic reference resolution/Gate. Revision `e1676c9`.
- Adversarial probes: six predeclared probes, two repeats, revision `dd3c168`.
- Local test activity overlapped some measurements; timings are descriptive local observations.

## Paired real-provider replay

| Mode | Valid report | Top-1 | Top-3 | Median ms | P95 ms | Total tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| single | 17/18 | 17/18 | 17/18 | 3500.0 | 4078 | 31063 |
| graph | 17/18 | 17/18 | 17/18 | 3437.0 | 4281 | 31026 |
| memory | 18/18 | 18/18 | 18/18 | 3203.0 | 4453 | 32440 |

These are repeated known cases, not 18 independent incidents. Single and graph each had one
schema failure; memory had none. A one-case difference does not establish a general memory gain.
Graph collection uses a fixed fixture-read plan; the comparison does not test model-generated
planning, live Tool Gateway investigation or production checkpoints. Graph fixture evidence
always hands off and never grants recovery authority. Raw evidence: [paired results](paired-001/results.json),
[predeclared plan](paired-001/plan.json), [call journal](paired-001/calls.jsonl).

## Actual Compose fault observations

| Metric | Initial live run | Verified-evidence live run |
| --- | ---: | ---: |
| Cases | 6 | 6 |
| Strict valid reports | 1/6 | 4/6 |
| Exact-label Top-1 / Top-3 | 1/6 / 1/6 | 2/6 / 2/6 |
| Input / output tokens | 15,547 / 4,197 | 16,804 / 1,836 |
| Median call ms | 4,297.5 | 2,180 |
| P95 call ms, nearest rank | 5,047 | 2,844 |
| Successful evaluator cleanup and baseline checkout | 6/6 | 6/6 |
| Domain Evidence/Artifact records | Not created | 24 |
| Candidate Gate decisions | Not run | 0 PASS / 5 FAIL |
| Cited-reference resolution occurrences | Not run | 15/15 |
| Approved product recovery | Not executed | Not executed |

No speedup is claimed between these runs: prompt, storage and inputs changed and there is no
paired performance control. In the verified run, pool exhaustion and Redis timeout were
misclassified as downstream latency. All five candidates declared missing evidence; the Gate
correctly refused them. Two reports failed overall schema consistency. The first live run also
had a missing trace source in one case. A valid schema does not establish correct diagnosis,
and source presence does not establish source quality or semantic support.

The isolated trace-query failure in [live-001](live-001/cases.jsonl) was cleaned safely and excluded
from diagnosis-quality denominators. It is retained as an infrastructure failure, not silently
replaced. The original live-002 runner captured HEAD at completion; its `code_revision` field
is a completion revision, not the execution-start revision. This provenance limitation is
corrected in the verified runner and retained with the original raw result.

- [Initial live result](live-002/results.json)
- [Verified live result](live-003/results.json) and [derived metrics](live-003/metrics.json)
- [Immutable evidence store](live-003/evidence-store/): 24 copied Artifacts were re-read with
  tenant/incident authorization and hash verification. Evidence expires after one hour;
  historical content auditing uses its recorded collection time, not fresh-runtime admission.
- Model bodies/reasoning are absent from journals; published observation snapshots are redacted.

## Real-model adversarial observations

12 calls: 6 valid reports, 6 strict-schema refusals. Exact synthetic-canary echoes were 0/2;
missing-evidence recognition was 2/2. Failed-schema calls have unavailable semantic outcomes,
not automatically correct answers. This is a small exact-echo probe, not a general zero-leakage
or injection-resistance claim. No mutation capability was available in this harness; zero
mutations is not an executor block rate. [Raw adversarial result](adversarial-001/results.json).

## Deterministic platform controls

The final full Python suite passed **2,820 tests**, zero failures/errors/skips, with **100%
statement and branch coverage** of 14,194 statements and 3,882 branches. Declared control
coverage: security 31/31, concurrency 16/16, failure handling 24/24, workflow 14/14,
worker resilience 13/13. These remain deterministic tests and do not imply real-model accuracy.
Ruff formatting/lint, strict mypy, architecture and planning-document validation passed.
[Sanitized test metadata](python-verification.json) binds the exact source revision and JUnit hash.

The prior [bounded load run](../v1/load-001/README.md) completed API 128/128, Evidence reads
64/64, Job leasing 64/64 and worker processing 64/64 at the configured concurrency. No load
implementation changed in this batch, so those observations were not relabeled as a new run.
[Six infrastructure snapshots](infrastructure-samples.jsonl) record actual CPU/memory during
experiments; they are not production capacity or monetary infrastructure cost.

## Resource accounting

Every benchmark call records its usage when the provider returns it, including schema failures.
The [versioned rate card](rate-card.json) yields conservative price bounds over cache and peak
variations. These are estimates, not account billing. For verified live calls the recorded
usage implies USD 0.001152012–0.0072444 under that rate-card interval. Actual invoice, per-success
infrastructure cost and human labor cost remain unavailable, not zero. The separate diagnostic
call used to localize validation fields is not part of benchmark quality denominators.

## Coverage and next engineering work

- Measured: known-case exact classification, schema failures, provider duration distributions,
  token usage, small adversarial oracles, live source availability, immutable reference
  resolution, deterministic Gate refusal, cleanup, platform safety/resilience and bounded load.
- Not established: autonomous model planning/Tool Gateway investigation, held-out generalization,
  semantic unsupported-conclusion rate, complete per-record endpoint/query provenance,
  correct scenario-specific handoff rate, queue-wait and
  crash-resume latency distributions, real-provider Remediation quality or full persisted
  live recovery. These are nonhuman capability/measurement gaps, not deferred human tasks.
- Human-dependent: paired manual/assisted effort, approval waiting, approved recovery outcomes,
  MTTR and recurrence follow-up. No actionable approval request has been created by the harness.

Priority fixes: preserve discriminating dependency/deployment/trace evidence in bounded context;
make report disposition/candidate consistency reliable; connect real planning/read-tool paths
and registered prompts to persisted runtime state; then rerun frozen holdout and adversarial
sets before requesting real human recovery approval. Do not bypass the failing Gate to obtain
recovery metrics. [Human trial handoff](../../../../docs/HUMAN_EVALUATION_HANDOFF.md).

## Reproduction

Set DEEPSEEK_API_KEY in the process environment. Use create-only new output directories:

```powershell
.venv/Scripts/python.exe -m evaluation.run_real_comparison --output-dir artifacts/new-paired
.venv/Scripts/python.exe -m evaluation.run_real_adversarial --output-dir artifacts/new-adversarial
.venv/Scripts/python.exe -m evaluation.run_live_diagnosis --output-dir artifacts/new-live
.venv/Scripts/python.exe -m pytest tests -p no:cacheprovider
```

Use each experiment's recorded revision to reproduce its prompt and implementation. Model
responses are stochastic despite temperature 0, and local durations vary. Live runs require
the independent Compose stack and the documented port/secret-file settings. Never put a key
in a committed command or fixture. Ground Truth/scoring policy is read only after calls finish.

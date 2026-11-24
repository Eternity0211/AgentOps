# NE1 RCAEval feasibility and source pin

## Source checked

The upstream dataset is `phamquiluan/RCAEval` at Hugging Face revision
`8b6c06a7a15bcecdbf70b611a13b789c5925dc17`, with MIT licence in its
dataset card. The pinned `cases.parquet` is 31,157 bytes and SHA-256
`ec0008c90d0c97076bc98370ac824c3c5a49be95d00bd6d6044ea8061861d271`.
It has 735 indexed failures, including 90 RE2 Online Boutique (RE2-OB) and
90 RE2 Train Ticket (RE2-TT) cases. All RE2-OB cases have metrics, logs and
traces. All RE2-TT cases have metrics and traces; 89/90 have logs. A missing
log must remain a recorded missing modality, not be filled with synthetic text.

Upstream index: <https://huggingface.co/datasets/phamquiluan/RCAEval>
and benchmark: <https://github.com/phamquiluan/RCAEval>.

## Fairness boundary

RCAEval labels `root_cause_service` and `fault`, whereas the current lab
confirmation scores one of six AgentOps fault-family candidate IDs. These are
different prediction tasks. A public-benchmark adapter must use a versioned
typed service-localization output and a benchmark-specific scorer. Service
Top-1/Top-3 will be the primary public outcome; fault type and the existing
Evidence Gate recall are separate secondary measures. No string matching of
free-form candidate statements or post-hoc taxonomy equivalence earns credit.

The proposed development split is RE2-OB and the proposed untouched external
confirmation split is RE2-TT. They have different systems and 90 cases each.
This split remains a proposal until the label-free task view, telemetry
adaptation, baseline/candidate parity, power rule and scorer are implemented,
tested and frozen in a separate commit. No provider calls to the held-out
cases have been made. Public labels and injection metadata remain
evaluator-only; runtime and model contexts receive neither.

RCAEval's author uses injected faults in benchmark microservices. This is
independent external laboratory evidence, not naturally occurring production
incidents. Its metadata has injection times and root-cause labels, but no
confirmed incident closure, repair outcome or approval record. It cannot by
itself complete FC5 historical-memory, FC6 human-labor or FC7 approved
recovery measurements.

## Frozen external-benchmark contract

NE1 is implemented by `evaluation/rcaeval/v1/protocol.json`. The protocol
binds the exact dataset revision and index hash above, MIT licence,
development/holdout split, candidate-service vocabularies, per-case budgets,
failure policy, paired scorer and pre-run controls. Its public task is service
localization. It explicitly refuses to reinterpret the benchmark's service
or fault labels as the six AgentOps lab fault-family candidate IDs.

The split is frozen before any held-out provider call:

| Role | Dataset | Cases | Candidate services |
| --- | --- | ---: | --- |
| Development | RE2-OB | 90 | checkout, currency, email, product-catalog and recommendation services |
| Holdout | RE2-TT | 90 | auth, order, route, train and travel services |

The per-case ceiling is two model calls, 24 read-tool calls, 30,000 input
tokens, 4,000 output tokens and 180 seconds. Baseline and candidate must bind
the same protocol, task-index hash and budget. Arm order is interleaved. A
future run may use less budget but must not silently raise any ceiling; a
protocol change requires a new version and cannot rescore an opened holdout.

## Label-free export and telemetry boundary

`evaluation.rcaeval_contract` verifies `cases.parquet` before reading it and
rejects a source hash or case-count mismatch. It exports opaque case IDs and
hard-linked telemetry under `tasks/`; the original case directory, root-cause
service and fault remain only in `evaluator_only/answers.json`. Each task
contains the observation/injection window, the complete system-level
candidate set, explicit modality availability and SHA-256/size bindings for
every available metrics, logs and traces file. The one absent RE2-TT log is
retained as an unavailable zero binding and is never synthesized. The export
is create-once and rejects symlinked or missing source telemetry.

The export command is:

```text
python -m evaluation.rcaeval_contract \
  --protocol evaluation/rcaeval/v1/protocol.json \
  --index <evaluator-only>/cases.parquet \
  --telemetry-root <downloaded-pinned-revision> \
  --output-root <new-export-directory>
```

`ReadOnlyTelemetryAdapter` accepts only a typed modality, one to eight named
columns, a task-bounded time range and at most 200 rows. It chooses the bound
file itself, rechecks size and SHA-256 for every query, rejects unavailable
modalities and unknown columns, and exposes no caller-selected path, URL,
command or mutation. Logs and traces remain untrusted data; this adapter does
not promote their contents to instructions or Evidence.

## Typed output and paired scoring

`evaluation.score_rcaeval_pair` accepts versioned outputs containing one
opaque case ID and one to three unique ranked services from that task's fixed
candidate set. It rejects unknown/duplicate cases, services outside the
candidate set, protocol/task-index drift, arm substitution and budget drift.
Missing, timed-out, refused, dependency-failed and invalid cases score as
misses. Primary outcomes are service Top-1 and Top-3 over the full split.
Paired differences, bootstrap 95% intervals and exact McNemar tests use the
existing versioned paired-comparison engine. Fault-type accuracy and Evidence
Gate recall remain separate secondary outcomes and cannot earn service credit.

Safety and latency/cost gates are explicit inputs from both arm artifacts;
the scorer never assumes they passed. A beneficial point estimate alone
cannot become an improvement claim when either gate is false. No provider
call or accuracy result is part of NE1.

## Verification

Unit coverage checks the frozen revision/hash/split/budget, source drift,
case-count drift, missing-log preservation, absence of raw case/fault fields
from task manifests, create-once export, bounded reads, telemetry tampering,
typed rankings, missing/failure scoring, candidate-set enforcement and paired
budget/task parity. The committed protocol must pass formatting, lint, mypy,
architecture checks and the repository regression suite before NE1 is closed.

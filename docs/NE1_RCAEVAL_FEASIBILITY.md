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

## Next executable step

Build a label-free task export and bounded read-only metrics/logs/traces
adapter for the pinned RE2 cases. Keep the public index in evaluator-only
storage, bind each downloaded telemetry file by hash and retain missing
modalities. Reject case or source drift before a model call. Freeze the
service-localization schema and paired scorer before external confirmation.

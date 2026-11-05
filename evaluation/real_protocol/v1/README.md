# Registered real-model evaluation protocol v1

This predeclares 27 observation instances per mode, including 18 faults and nine normal,
insufficient-evidence and counter-evidence controls. The three model modes require 81 total
instances. These are new instances of known fault families, not unseen-family generalization.
No captures or results are asserted by this plan.

The JSON plan is evaluator-only. A model may receive only its public cause taxonomy, never
the strata, expected outcomes, case mapping or scoring labels. Capture and replay adapters must
bind exact hashes and reject mismatched paired inputs. Runtime modules must not import this
folder. Collection/scoring validation and all 81 provider instances remain to be implemented
and run before this protocol can support outcome claims.

`evaluation.real_scoring` provides the isolated typed label/output join and exact-count
scoring. It requires all 81 outcomes with equal per-instance initial-input hashes and a shared
expected protocol hash; failures remain in denominators. It does not yet load immutable run
artifacts or produce confidence intervals/resource distributions. No experiment result is
created by its synthetic unit tests.

The scorer now includes nominal Wilson 95% binomial intervals and observed resource
distributions with missing-value counts, raw sorted values, median and nearest-rank P95.
Actual billed cost remains unknown. Repeated local scenarios may be dependent; intervals
are descriptive under a binomial assumption, not production reliability evidence. Bounded
file ingestion verifies externally supplied raw SHA-256 hashes before scoring and validates
outputs before loading labels. Hashes bind bytes; they do not authenticate who produced them.

Capture entry: `python -m evaluation.capture_real_dataset --output PATH` (or `--smoke`).
It collects 18 fault and three normal instances, using the existing bounded local adapters
as evaluator-owned read collectors. Snapshots have fixed source windows and query provenance;
model-selected replay still goes through the Tool Gateway. Redaction/quarantine precedes
export. The evaluator manifest contains labels and cleanup observations and must never be
loaded by model adapters. Six derived insufficient/counter-evidence controls remain pending.

`OutcomeLedger` writes/fsyncs each typed result independently and refuses repeated
instance/mode writes; aggregate export remains create-only. Snapshot loading verifies bounded
bytes, hash, closed fields, aware windows and the exact local read catalog before replay.
These files carry no evaluator labels. Failed capture/source records remain visible.

Single-agent comparison uses `investigate(single_pass=True)`: one compiled PLAN, bounded
read batches, Evidence normalization, one DIAGNOSE and deterministic Gate, without a
LangGraph or replan. The graph mode may use its single bounded replan. Both share catalogs,
model and aggregate ceilings; actual usage is reported. Single-pass does not provide durable
production runtime/checkpoint composition and cannot accept a registered invoker.

`run_snapshot_comparison.run_snapshot` invokes the bounded provider transport using verified
read replay and writes one durable outcome plus content-free events. Public taxonomy is
shared across modes. Current historical references are empty; mode metadata explicitly marks
controlled-graph-memory as ineligible for quality comparison until confirmed history is wired.
Do not treat its empty-history execution as a completed memory baseline or claim a memory gain.

Memory mode accepts a server-owned `MemoryReplaySource` backed by the existing authorized
SimilarIncidentRetriever. Query Incident must match the snapshot; all evaluation IDs must be
excluded. Fresh, unique references are redacted/quarantined and remain advisory. Metadata
distinguishes authorized retrieval (including zero matches) from no supplied history. Actual
confirmed SQL records are still required for a nonempty-memory comparison.

Batch entry: `python -m evaluation.run_real_batch --output PATH` after loading the provider
credential into the process environment. It preflights all 27 snapshots, runs single/graph,
and resumes only from committed hash-matching outcomes. A prior run directory without an
outcome is recorded FAILED rather than silently repeating uncertain provider effects.
Memory comparison still requires its separately configured authorized history source.

Formal replay freezes Evidence/Gate time at capture-window end plus one second while
provider durations use real monotonic time. Frozen time cannot be supplied with registered
model or SQL runtime ports. Runtime metadata records revision and exact source hashes.
Prompt transport v1.2.0 clarifies the existing four-step parallel-group ceiling. The first
http-500 instance was exposed during development smoke (two plan rejections then one
completed diagnosis); it must be reported as a development case, not an unseen holdout.

The scorer can publish complete per-mode subsets with explicit `evaluated_modes`. Such a
report sets `comparison_complete=false` and lists missing modes. Default scoring still
requires all 81 records; partial reports do not establish completion of the frozen protocol.

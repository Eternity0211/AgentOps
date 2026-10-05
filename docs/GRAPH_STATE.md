# Versioned Diagnosis Graph State

Phase 6 defines a strict Pydantic checkpoint contract before adding LangGraph nodes or a PostgreSQL
checkpointer. `DiagnosisGraphState` is frozen, rejects unknown fields, uses schema version `1.0.0`,
and serializes to canonical sorted JSON bytes.

The state contains only tenant, Incident, workflow, correlation and causation identities; graph
phase/version; bounded step, replan, tool, model, token, and integer cost counters; an exact Prompt
reference; Tool Call, Model Call, and Evidence IDs; an optional Evidence Gate decision hash; a
bounded error code; checkpoint sequence; and UTC update time. Prompt text, model responses, raw
telemetry, Artifact bodies, exceptions, credentials, and Ground Truth have no fields in the model.

`GraphStateMigrationRegistry` upgrades decoded checkpoint mappings one registered version at a time.
Every migration receives a deep copy, must advance to its declared target, and is capped at 32
steps. Missing paths, future versions, duplicate sources, non-advancing registrations, malformed
results, excessive chains, extra fields, and invalid final state all fail closed. The original
snapshot remains unchanged. A migration implementation must be deterministic and covered by a
version-pair fixture before deployment.

The state is now used by the executable [Bounded Diagnosis LangGraph](DIAGNOSIS_GRAPH.md). That graph
still compiles without a checkpointer: the later PostgreSQL checkpoint batch must load state only
through this registry and retain graph/state versions plus thread/run correlation.

Unit tests cover canonical round trips, frozen state, content-bearing field refusal, identifiers,
hashes, UTC timestamps, unique references, all budget dimensions, old-version migration,
immutability, current/future/unknown versions, invalid migration output, and the migration limit.

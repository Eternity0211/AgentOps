# Versioned Diagnosis Graph State

Phase 6 defines a strict Pydantic checkpoint contract used by the executable LangGraph and its
PostgreSQL checkpointer. `DiagnosisGraphState` is frozen, rejects unknown fields, uses schema
version `1.2.0`, and serializes to canonical sorted JSON bytes.

The state contains only tenant, Incident, workflow, correlation and causation identities; graph
phase/version; bounded step, replan, tool, model, token, and integer cost counters; an exact Prompt
reference; Tool Call, Model Call, and Evidence IDs; an optional Evidence Gate decision hash; a
bounded error code; checkpoint sequence; and UTC update time. Prompt text, model responses, raw
telemetry, Artifact bodies, exceptions, credentials, and Ground Truth have no fields in the model.

Version `1.1.0` adds a bounded, unique tuple of SHA-256 tool-query fingerprints used to reject
equivalent investigation calls across replans. The built-in `1.0.0 -> 1.1.0` migration initializes
an empty history and rejects a purported legacy snapshot that already contains the future field.
Version `1.2.0` adds the terminal Diagnosis-graph `CANCELLED` phase. Its `1.1.0 -> 1.2.0` migration
changes only the schema version. JSON checkpoint arrays for reference collections are restored to
immutable tuples before strict validation; other coercion remains disabled.

`GraphStateMigrationRegistry` upgrades decoded checkpoint mappings one registered version at a time.
Every migration receives a deep copy, must advance to its declared target, and is capped at 32
steps. Missing paths, future versions, duplicate sources, non-advancing registrations, malformed
results, excessive chains, extra fields, and invalid final state all fail closed. The original
snapshot remains unchanged. A migration implementation must be deterministic and covered by a
version-pair fixture before deployment.

The state is now used by the executable [Bounded Diagnosis LangGraph](DIAGNOSIS_GRAPH.md). That graph
now accepts the production PostgreSQL checkpointer. Thread/run correlation, strict serialization,
history, restore, and isolation are documented in [Operational Persistence](PERSISTENCE.md).

Unit tests cover canonical round trips, frozen state, content-bearing field refusal, identifiers,
hashes, UTC timestamps, unique references, all budget dimensions, old-version migration,
immutability, checkpoint array restoration, cancellation migration, current/future/unknown
versions, invalid migration output, and the migration limit.

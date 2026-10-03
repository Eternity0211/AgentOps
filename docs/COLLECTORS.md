# Deterministic Evidence Collectors

Phase 3 provides five bounded collector adapters for metrics, logs, traces, deployments, and
service topology. They are ordinary deterministic components, never agents. They do not select
tools, infer causes, call models, or mutate the diagnosed system.

## Common contract

Each adapter accepts typed records plus an `EvidenceBuildRequest`, verifies that the declared
source and tool name match the adapter, applies a maximum of 1,000 records per result, and sends a
canonical JSON document through the Evidence normalization pipeline. Caller-provided quality
claims are replaced with measured record count, dropped count, parser warnings, source
availability, and window completeness.

All timestamps are normalized to UTC. Text fields are bounded and null-safe. Numeric metrics must
be finite. Metric labels and topology edges are unique and deterministically ordered. Trace spans
preserve parent relationships and reject reversed times. Deployment entries preserve exact
service, environment, version, and occurrence time.

## Untrusted logs

Log text remains data and is not interpreted as instructions. The adapter records the injection
classification. `SUSPECTED` content cannot become normal Evidence; it must first pass the separate
quarantine/redaction boundary. `QUARANTINED` content remains explicitly marked and receives a
bounded low quality score. Raw records stay in the Artifact payload rather than workflow state.

For clustering, the log adapter binds each typed record to `(Artifact ID, record index)` before any
summary is created. The deterministic clusterer replaces volatile UUIDs, IP addresses, hex values,
and numbers with stable placeholders, then groups only error-level records. Every pattern retains
its count, first/last observation, services, severities, schema-versioned fingerprint, and all raw
Artifact positions; informational records are not promoted into error evidence.

## Integration boundary

These adapters transform already retrieved typed results. Phase 4 Tool Gateway adapters will own
live Prometheus, Loki, Tempo, deployment-record, and topology access, including authorization,
timeouts, retries, result limits, and audit. Keeping transport separate makes the collector output
stable and testable without converting collectors into decision agents.

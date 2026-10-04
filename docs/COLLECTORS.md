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

## Metric trend summaries

Metric trend summaries compare one bounded current series with one explicit earlier baseline. Both
series must describe the same metric and normalized label set, use the same positive sampling
interval, contain finite values in strict time order, and retain their own immutable Artifact ID.
Aligned gaps are allowed so missing samples remain visible in the point counts; overlapping or
future baselines, mixed metrics, duplicate timestamps, and mislabeled sampling intervals fail
closed.

The schema-versioned summary records current and baseline time ranges, sampling interval and point
counts, first/last/minimum/maximum/mean values, baseline mean, absolute and percentage change, the
stable threshold, and a deterministic direction. Direction compares interval means rather than
inferring from a single endpoint. A zero baseline has no meaningful percentage change, so that
field is `null`; its direction is determined only by the signed absolute change. Both current and
baseline Artifact IDs remain available to resolve the raw samples.

## Trace critical-path and error summaries

Trace summaries accept one bounded trace tree and retain each span's Artifact ID, raw record index,
trace ID, and span ID. The deterministic validator requires exactly one root, unique span IDs and
raw positions, resolvable parents, and child time ranges contained by their parents. It rejects
mixed traces, self-parenting, missing parents, disconnected cycles, reversed times, and oversized
inputs before producing a summary.

The critical path is the root-to-leaf chain with the greatest cumulative span duration. Equal
paths use span IDs as a stable tie-breaker. The schema-versioned result records trace boundaries,
root duration, span and error counts, participating services, critical-path duration and segments,
all error segments, whether the critical path contains an error, and every source Artifact ID.
Each returned segment preserves service, operation, status, duration, parent ID, and its resolvable
raw reference; the summary does not replace or hide the immutable trace Artifact.

## Integration boundary

These adapters transform already retrieved typed results. Phase 4 Tool Gateway adapters will own
live Prometheus, Loki, Tempo, deployment-record, and topology access, including authorization,
timeouts, retries, result limits, and audit. Keeping transport separate makes the collector output
stable and testable without converting collectors into decision agents.

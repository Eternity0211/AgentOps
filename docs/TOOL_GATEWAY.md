# Versioned Tool Gateway contracts

Phase 4 begins with a framework-independent `ToolDefinition` registry. It is the server-owned
capability catalog for the deterministic Tool Gateway; it is not an agent and it does not dispatch
calls by itself.

## Definition contract

Every exact tool release declares:

- a lower-snake-case name and strict `MAJOR.MINOR.PATCH` semantic version;
- canonical, size-bounded input and output JSON Schemas, each with its own semantic version and
  immutable SHA-256 fingerprint;
- `READ` or `WRITE` access class, risk tier, and required RBAC permission;
- a positive timeout no greater than five minutes and a result-size ceiling no greater than the
  Artifact limit;
- one to five total attempts, bounded backoff, and explicit retryable-error classifications;
- idempotency behavior; reads use `NOT_APPLICABLE`, while every write requires durable result
  replay;
- a versioned append-only audit event contract that retains canonical request and result hashes.

Schemas must be strict root objects with `additionalProperties: false`. Required fields must be
declared properties. Schema documents are canonicalized before registration, so the fingerprint is
stable and callers cannot mutate the registered document through a retained dictionary reference.
Pre-release/build version syntax is intentionally excluded until compatibility rules require it.

## Registry selection

Definitions are keyed by exact name and semantic version. Duplicate definitions, empty registries,
unknown enablement names, invalid ranges, and ranges containing no registered release fail during
startup construction. Deployment-owned inclusive version ranges can disable an old or staged
release without deleting its immutable definition. Resolution never falls back to a nearby or
latest version: unknown pairs raise `ToolNotFoundError`, and registered but disabled releases raise
`ToolVersionDisabledError`.

The catalog returns only enabled definitions in deterministic name/version order and may be
filtered by read/write class. Diagnosis will later receive only the read catalog; the gateway and
workflow batches must still revalidate access class, RBAC, schema, incident scope, timeout, retry,
payload limits, and audit on every invocation.

## Current boundary

This batch defines metadata and selection only. It does not yet dispatch adapters, accept model
tool calls, perform retries, or register the six planned read contracts. Those capabilities remain
separate TODO batches so dispatch cannot exist before its validation, authorization, limits, and
audit controls.

## Verification

Unit tests cover semantic ordering, canonical schema immutability/fingerprints, malformed and
oversized schemas, bounded timeout/result/retry settings, retry classifications, read/write
idempotency invariants, mandatory hash-only audit metadata, duplicate/unknown/disabled versions,
enablement configuration errors, and deterministic catalog filtering.

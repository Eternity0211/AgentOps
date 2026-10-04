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
- a positive timeout no greater than five minutes and input/result-size ceilings no greater than
  the Artifact limit;
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

## Deterministic invocation pipeline

`ToolGateway` accepts a canonical immutable call containing the exact tool version, Incident and
workflow IDs, authenticated principal, correlation/causation IDs, and a detached JSON argument
object. It then executes this fixed sequence:

1. Resolve the exact enabled definition; no latest-version fallback exists.
2. Enforce the definition's RBAC permission and input byte ceiling.
3. Validate arguments against the supported strict JSON Schema subset.
4. Append a request-hash-only `tool.call_started` audit event before dispatch.
5. Invoke only the exact server-registered adapter under its per-attempt timeout.
6. Retry only explicitly classified failures that the definition allows, using bounded exponential
   backoff and the total-attempt ceiling.
7. Canonicalize and validate the output, then enforce the result byte ceiling.
8. Append a success or failure audit event containing request/result or request/error hashes.

Unknown, disabled, unauthorized, malformed, and oversized inputs emit `tool.call_rejected` without
dispatch. Cancellation, timeout, classified dependency failure, unexpected adapter failure,
malformed output, and oversized output emit `tool.call_failed`. Audit persistence is fail-closed:
an unavailable writer prevents dispatch rather than silently producing an unaudited call. Audit
events contain hashes and identifiers, never arguments, results, exception messages, or telemetry.

The built-in validator intentionally supports a bounded JSON Schema subset: strict objects,
required fields, scalar types, finite numeric bounds, string length/pattern, enum/const, and bounded
arrays with recursively validated items. Unsupported keywords or excessive nesting fail gateway
construction. Enabled definitions and adapter registrations must match exactly at startup.

## Current boundary

The gateway core now validates, authorizes, dispatches, times out, retries, limits, and audits calls.
The `query_metrics` v1 contract and adapter are now registered in code. It accepts only a fixed
metric enum, bounded service identifier, production/staging environment, UTC query window, and
1–300 second step; it never accepts PromQL, a URL, path, or credential. The query window is capped
at six hours. A deployment injects the read-only `MetricsBackend` port, while the adapter verifies
that every returned sample uses the requested metric, lies in the requested window, and carries
exactly the requested service/environment scope. Results are capped at 1,000 samples and preserve
window-completeness and dropped-record counts in a versioned Prometheus result document.

The remaining five planned read tool definitions and adapters remain separate TODO batches.
Diagnosis-only catalog enforcement and the explicit raw URL/path/command deny rules are still open
and will be completed before agent workflows can invoke the gateway.

## Verification

Unit tests cover semantic ordering, canonical schema immutability/fingerprints, malformed and
oversized schemas, bounded timeout/result/retry settings, retry classifications, read/write
idempotency invariants, mandatory hash-only audit metadata, duplicate/unknown/disabled versions,
enablement configuration errors, deterministic catalog filtering, every supported schema
constraint, authorization/rejection, dispatch, timeout, classified retry/backoff, cancellation,
unexpected failure, output validation, result limits, and audit failure. A PostgreSQL integration
test proves started/succeeded events persist through the append-only `AuditRepository`.
The metrics adapter suite additionally covers its exact registry metadata, backend result bounds,
canonical success response, invalid/oversized windows, metric substitution, out-of-window samples,
and missing or additional scope labels.

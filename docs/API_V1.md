# Versioned control-plane API

The control plane exposes versioned business contracts under `/api/v1`. The API process remains separate
from workers and never performs investigation or recovery work inline. It accepts only typed
lifecycle controls and persists their domain records, audit event, and idempotency result in one
PostgreSQL transaction.

## Authentication and authorization boundary

`create_app` accepts a deployment-owned asynchronous principal resolver. The resolver must return
an already validated `Principal` containing Actor ID, Tenant ID, and explicit roles. No HTTP header
is trusted by the core application itself. When no authentication adapter is configured, every
business endpoint fails closed with `401`; `/healthz` remains available for process health.

All resource queries include the authenticated Tenant ID. A resource in another tenant is returned
as `404`, preventing existence disclosure. Read routes require `incident:read` or `audit:read`;
control routes require `investigation:start` or `investigation:cancel`. Admin does not implicitly
receive operator authority.

## Endpoints

| Method and path | Purpose | Required permission |
| --- | --- | --- |
| `GET /api/v1/session` | Return the server-resolved Actor ID, Tenant ID, roles, and derived permissions | authenticated principal |
| `GET /api/v1/incidents` | List tenant incidents in stable newest-first order | `incident:read` |
| `GET /api/v1/incidents/{incident_id}` | Read one tenant incident | `incident:read` |
| `GET /api/v1/incidents/{incident_id}/investigation` | Read the latest bounded Diagnosis progress projection | `incident:read` |
| `GET /api/v1/incidents/{incident_id}/timeline` | Read lifecycle transitions and cancellation requests | `incident:read` |
| `GET /api/v1/incidents/{incident_id}/evidence` | List incident-owned Evidence metadata | `evidence:read` |
| `GET /api/v1/incidents/{incident_id}/evidence/{evidence_id}` | Read one Evidence metadata record | `evidence:read` |
| `GET /api/v1/incidents/{incident_id}/evidence/{evidence_id}/artifact` | Retrieve verified immutable Artifact bytes | `evidence:read` |
| `POST /api/v1/incidents/{incident_id}/controls/start-investigation` | Apply `TRIAGED -> INVESTIGATING` | `investigation:start` |
| `POST /api/v1/incidents/{incident_id}/controls/cancel` | Apply immediate or safe-boundary deferred cancellation | `investigation:cancel` |
| `GET /api/v1/audit` | Read the tenant audit sequence | `audit:read` |

Incident and timeline lists use opaque cursors; callers must not construct or interpret them.
Audit pagination uses the append-only global sequence as `after_sequence`. Page size is bounded to
1–100. All orders have deterministic tie breakers, so concurrent inserts do not reorder already
returned records.

`GET /api/v1/incidents` accepts optional exact `severity`, `state`, and `service` filters that are
combined with the authenticated tenant predicate before cursor pagination. Severity and state use
the versioned domain enums. Service is a 1–128 character normalized identifier limited to letters,
digits, `.`, `_`, `:`, `/`, and `-`; malformed values fail request validation. Every Incident
summary includes its authoritative service scope. A cursor remains opaque and must be replayed with
the same filter set from which it was returned.

`GET /api/v1/incidents/{incident_id}` returns the server-owned service, severity, lifecycle state,
optimistic version, and lifecycle timestamps used by the administration detail route. The paired
timeline response is an ordered, cursor-paged union of state transitions and cancellation
requests. Each item carries consecutive prior/new versions plus actor, reason, occurrence,
correlation, and causation metadata; kind-specific fields describe the prior/new state or the
state/disposition of a cancellation request. The console validates this discriminated response
and replays `next_cursor` unchanged. It does not reconstruct missing events or infer current state
from the timeline.

`GET /api/v1/incidents/{incident_id}/investigation` first proves Incident ownership, then returns
the most recently updated run or an explicit `run: null` when no Diagnosis projection exists. A run
contains graph/projection versions, phase/status, checkpoint sequence, exact used/maximum/remaining
counters for steps, replans, tools, model calls, tokens, and integer-nanounit cost, plus ordered
plan attempts, per-step read-tool progress, bounded replan history, and stable failure codes. It
never exposes tool arguments/results, raw telemetry, prompt content, or checkpoint payloads. The
server revalidates the stored schema, tenant/Incident/run bindings, duplicated relational fields,
and canonical fingerprint on every read; corruption returns the typed
`INVESTIGATION_PROGRESS_INTEGRITY_FAILED` conflict rather than partial data.

Evidence lists use the same opaque newest-first cursor convention, ordered by collection time and
Evidence ID. Metadata includes source/query provenance, observation and collection ranges, quality
reasons, lineage, trust and injection classifications, expiry, and the immutable Artifact binding;
it never exposes a storage locator. The `expired` field is evaluated using the server clock.

Artifact retrieval first resolves Evidence through the authenticated tenant and requested Incident.
The configured storage adapter then independently authorizes the read, enforces retention expiry,
and verifies the content hash and size. The API rechecks Artifact ID, tenant, Incident, and hash
against Evidence before returning bytes. Responses are `private, no-store` and expose only safe
identity, hash, schema-version, and redaction headers. Missing and cross-tenant records are `404`,
expired content is `410`, integrity or binding failures are `409`, and an unconfigured Artifact
backend fails closed with `503`.

## Control idempotency

Every control request requires an `Idempotency-Key` of 1–128 conservative identifier characters.
The durable scope is Tenant ID, Actor ID, operation plus Incident ID, and key. The server hashes the
canonical typed command. Repeating the same command returns the stored response and sets
`Idempotency-Replayed: true`; reusing the key for a different command returns `409`.

The idempotency claim, optimistic Incident update, lifecycle record, and append-only audit event
commit together. A rejected or failed command rolls the claim back, so an incomplete result cannot
mask a later valid retry. PostgreSQL uniqueness plus row locking serializes concurrent uses of the
same key. The audit ledger stores request/result hashes rather than the bodies.

## Error and correlation convention

Every response includes a server-generated `X-Request-ID`. Errors use
`application/problem+json` and a version-stable envelope containing `type`, `title`, HTTP `status`,
machine-readable `code`, bounded `detail`, request-path `instance`, and `request_id`. Request
validation may additionally include field locations, validator codes, and safe reasons; rejected
input values are never echoed.

The stable codes distinguish authentication, permission, resource absence, request/domain
validation, Incident state/version conflict, malformed request, method rejection, and idempotency
conflict. Cross-tenant resources deliberately use `RESOURCE_NOT_FOUND`. Unexpected internal
exceptions are not converted into detailed public errors by this contract.

The generated OpenAPI contract documents the problem media type, `X-Request-ID`, required
`Idempotency-Key`, and the `Idempotency-Replayed` response header. A reviewable snapshot in
`tests/snapshots/openapi_v1.json` records the complete canonical-schema digest plus paths and model
names; any schema drift fails tests and requires an intentional snapshot review.

`GET /api/v1/session` is the console bootstrap contract. It never accepts identity or roles from
the request body or caller-controlled identity headers; it serializes only the Principal produced
by the deployment-owned resolver. Roles and derived permissions are sorted for deterministic
clients. An absent resolver or anonymous result returns the same typed `401` as every business
endpoint.

## Verification

PostgreSQL integration tests exercise migration round trips, anonymous and underprivileged
requests, tenant hiding, combined incident filters, stable pagination, successful controls,
duplicate replay, changed-payload conflict, optimistic/state conflicts, cancellation,
transactional audit/idempotency counts, and tenant-scoped Evidence metadata plus authorized,
hash-bound Artifact retrieval.
Framework-level contract tests cover defensive return and cursor branches that the Windows
coverage tracer cannot observe after SQLAlchemy's async greenlet bridge.

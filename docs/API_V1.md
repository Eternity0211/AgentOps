# Versioned control-plane API

Phase 2 exposes the first business contracts under `/api/v1`. The API process remains separate
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
| `GET /api/v1/incidents` | List tenant incidents in stable newest-first order | `incident:read` |
| `GET /api/v1/incidents/{incident_id}` | Read one tenant incident | `incident:read` |
| `GET /api/v1/incidents/{incident_id}/timeline` | Read lifecycle transitions and cancellation requests | `incident:read` |
| `POST /api/v1/incidents/{incident_id}/controls/start-investigation` | Apply `TRIAGED -> INVESTIGATING` | `investigation:start` |
| `POST /api/v1/incidents/{incident_id}/controls/cancel` | Apply immediate or safe-boundary deferred cancellation | `investigation:cancel` |
| `GET /api/v1/audit` | Read the tenant audit sequence | `audit:read` |

Incident and timeline lists use opaque cursors; callers must not construct or interpret them.
Audit pagination uses the append-only global sequence as `after_sequence`. Page size is bounded to
1–100. All orders have deterministic tie breakers, so concurrent inserts do not reorder already
returned records.

## Control idempotency

Every control request requires an `Idempotency-Key` of 1–128 conservative identifier characters.
The durable scope is Tenant ID, Actor ID, operation plus Incident ID, and key. The server hashes the
canonical typed command. Repeating the same command returns the stored response and sets
`Idempotency-Replayed: true`; reusing the key for a different command returns `409`.

The idempotency claim, optimistic Incident update, lifecycle record, and append-only audit event
commit together. A rejected or failed command rolls the claim back, so an incomplete result cannot
mask a later valid retry. PostgreSQL uniqueness plus row locking serializes concurrent uses of the
same key. The audit ledger stores request/result hashes rather than the bodies.

This batch provides typed FastAPI-generated OpenAPI but does not yet claim a committed OpenAPI
snapshot or the final cross-endpoint error envelope. Those remain the next explicit Phase 2 task.

## Verification

PostgreSQL integration tests exercise migration round trips, anonymous and underprivileged
requests, tenant hiding, stable pagination, successful controls, duplicate replay, changed-payload
conflict, optimistic/state conflicts, cancellation, and transactional audit/idempotency counts.
Framework-level contract tests cover defensive return and cursor branches that the Windows
coverage tracer cannot observe after SQLAlchemy's async greenlet bridge.

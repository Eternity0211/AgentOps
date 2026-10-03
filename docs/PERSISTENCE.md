# Operational Persistence Foundation

Phase 2 stores its first operational aggregates through SQLAlchemy 2.x and Alembic in the isolated
control-plane PostgreSQL database. Domain rules remain authoritative; the adapter maps validated
domain objects and adds database constraints, transactions, locks, and optimistic comparisons.

## Schema and migration

Revision `20261003_0001` creates five tables:

- `incidents` holds tenant ownership, severity, lifecycle state, optimistic version, UTC lifecycle
  timestamps, and deferred cancellation time;
- `incident_transitions` is append-only state-change history with actor, reason,
  correlation/causation IDs, prior/new state and consecutive versions;
- `incident_cancellation_requests` records both immediate and deferred requests independently of
  whether a state transition was safe at request time;
- `alert_groups` holds the versioned fingerprint, tenant/service scope, severity, observation and
  receipt windows, occurrence count, and optional Incident association;
- `alerts` holds each immutable normalized delivery, explicit dimensions, and its group.

Checks constrain state/severity vocabularies, positive versions/counts, timestamp order, terminal
timestamps, transition version steps, fingerprint length, and cancellation disposition. Foreign
keys use `RESTRICT`; adapters cannot erase a parent while its operational evidence remains.

Alembic accepts only an explicit `sqlalchemy.url` or `AGENTOPS_DATABASE_URL`; it has no embedded
credential or unsafe local password. The async environment uses a disposable `NullPool` connection
and preserves existing application loggers when loading Alembic logging configuration.

Revision `20261003_0007` adds immutable `evidence` rows. A composite foreign key binds each row to
the owning Incident and tenant, Artifact references are unique, and checks enforce source/trust/
injection vocabularies, SHA-256 form, quality bounds, and observation/collection/expiry ordering.
The repository validates the external Artifact identity, ownership, and digest before insertion.

## Repository concurrency

`IncidentRepository` updates with `WHERE id = ... AND version = ...`. A zero-row update raises the
typed optimistic conflict before any transition or cancellation record can commit. The caller owns
the transaction, so aggregate state and all records commit or roll back together.

`AlertRepository` takes a transaction-scoped PostgreSQL advisory lock derived from the complete
versioned fingerprint, then row-locks matching groups. It reuses the pure-domain selection and
merge policy, applies an optimistic group update, and inserts the unique Alert in the same
transaction. The lock is an implementation detail for cross-process serialization; tenant,
environment, service, rule, time-window, replay, and severity behavior remains defined by the
domain contract.

## Reproducible verification

Testcontainers starts the same `pgvector/pgvector:0.8.6-pg18` image used by the control plane. The integration
suite verifies `upgrade -> downgrade -> upgrade`, required tables, Incident load/change/conflict,
immediate and deferred cancellation persistence, and concurrent Alert ingestion from sixteen
independent transactions followed by a replay storm. Unit tests retain fail-closed coverage for
defensive paths that valid foreign keys and locks should make unreachable.

The test suite uses an ignored repository-local `.pytest-runtime-*` directory because elevated
Docker access on Windows cannot reliably access the normal per-user pytest temporary root. This is
test isolation only; no runtime data is committed. Workflow checkpoints remain a later phase.

## Versioned embedding metadata

Revision `20261003_0002` enables the `vector` extension and adds
`incident_memory_embeddings`. Each row points to an authoritative Incident and retains its source
content SHA-256, provider, model and model version, content schema version, normalization version,
declared dimensions, creation time, and explicit reindex flag. A database check requires
`vector_dims(embedding)` to equal the declared positive dimension, and a versioned-source unique
key prevents ambiguous duplicates. No similarity-search API, embedding generation, or claim that
historical memory is current evidence is enabled in this Phase 2 storage batch.

## Append-only audit ledger

Revision `20261003_0003` adds `audit_events`. Its database-assigned 64-bit sequence is the global
ordering key; the stable event ID prevents replay from creating the same logical event twice.
Each row records a versioned dotted event type, payload schema version, actor, correlation and
causation IDs, typed target, UTC occurrence time, and optional canonical request/result SHA-256
digests. Request and result bodies are deliberately excluded so the ledger does not become an
uncontrolled secret store.

The application adapter exposes append and correlation-timeline reads only. PostgreSQL privileges
are narrowed with explicit `REVOKE`, while owner-visible triggers independently reject `UPDATE`,
`DELETE`, and `TRUNCATE`. Database constraints also reject noncanonical hashes inserted outside
the typed domain path. Integration tests prove migration round trips, ordered reads, sixteen
concurrent inserts with unique increasing sequences, direct raw mutation refusal, and invalid raw
hash refusal. Stronger integrity mechanisms such as hash chaining or external anchoring remain an
explicit later threat/deployment decision rather than an unverified current claim.

## Transactional outbox

Revision `20261003_0004` adds `outbox_events` for cross-process event intent. Producers stage an
event through the same SQLAlchemy session and transaction as aggregate state; rollback removes
both. Each event has a stable ID, globally ordered sequence, topic and payload schema versions,
aggregate identity/version, correlation/causation IDs, UTC occurrence/availability times, bounded
canonical JSON payload, and SHA-256 integrity digest. A database unique key on aggregate type, ID,
version, and topic prevents a retry with a new message ID from duplicating the same intent.

Dispatchers claim ordered batches with `SELECT ... FOR UPDATE SKIP LOCKED`. A claim records its
worker, UTC expiry, and bounded attempt number. Only the owner of a live lease can mark publication
or failure; expired claims are safely reclaimable. Failures become available at an explicit retry
time and are dead-lettered after their per-event maximum attempt count. Integration tests cover
transaction rollback, duplicate intent, disjoint concurrent claims, stale-worker takeover,
foreign acknowledgement refusal, successful publication, delayed retry, and retry exhaustion.
This is not the general workflow job queue: job priority, heartbeat, cancellation, and human
handoff remain in their dedicated Phase 2 batch.

## Durable worker jobs

Revision `20261003_0005` adds `jobs`, a PostgreSQL queue distinct from outbox publication. Each job
has a typed ID, dotted type, payload schema and durable payload reference, correlation/causation,
bounded priority, UTC availability, maximum attempts, and an explicit exhaustion route to either
`DEAD_LETTER` or `NEEDS_HUMAN`. Database checks tie `LEASED` strictly to complete lease metadata
and terminal statuses strictly to a terminal timestamp.

Workers claim priority-ordered jobs with `SELECT ... FOR UPDATE SKIP LOCKED`. Claims record owner,
attempt, lease start, heartbeat, and expiry. Heartbeat, completion, and failure reject missing,
foreign, or expired leases. Retry releases a job until its attempt budget is exhausted. A crashed
worker's expired lease is reclaimed when budget remains; a final expired attempt is deterministically
routed to its configured terminal state so no job remains stranded. Tests cover concurrent disjoint
claims, duplicate enqueue, heartbeat renewal, foreign-worker refusal, delayed retry, explicit human
handoff, both stale-final routes, and stale-worker takeover. The worker runtime applies bounded
concurrency, cooperative shutdown, and persisted cancellation probes as documented in
`CONTROL_PLANE_PROCESSES.md`.

## Tenant ownership and API idempotency

Revision `20261003_0006` adds non-null Tenant IDs and tenant-first indexes to Incidents and audit
events, plus the `idempotency_records` table. Existing records are backfilled from an unambiguous
Alert-group association where available; all other legacy rows move to the isolated
`legacy-unassigned` tenant rather than becoming visible to an active tenant by inference.

An idempotency row is unique by tenant, actor, operation/Incident, and caller key. It stores the
canonical request hash and the completed status/body with UTC timestamps. The API creates or locks
this row in the same transaction as the Incident update, lifecycle records, and audit append.
Concurrent identical requests therefore produce one mutation and a durable replay; a changed
payload under the same scope is rejected. See `API_V1.md` for the exposed contract.

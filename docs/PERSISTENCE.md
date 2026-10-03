# Operational Persistence Foundation

Phase 2 stores its first operational aggregates through SQLAlchemy 2.x and Alembic in the isolated
control-plane PostgreSQL database. Domain rules remain authoritative; the adapter maps validated
domain objects and adds database constraints, transactions, locks, and optimistic comparisons.

## Schema and migration

Revision `20261003_0001` creates five tables:

- `incidents` holds severity, lifecycle state, optimistic version, UTC lifecycle timestamps, and
  deferred cancellation time;
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

Testcontainers starts the same `postgres:18.6-alpine` major image used by Compose. The integration
suite verifies `upgrade -> downgrade -> upgrade`, required tables, Incident load/change/conflict,
immediate and deferred cancellation persistence, and concurrent Alert ingestion from sixteen
independent transactions followed by a replay storm. Unit tests retain fail-closed coverage for
defensive paths that valid foreign keys and locks should make unreachable.

The test suite uses the ignored repository-local `.pytest-runtime/` directory because elevated
Docker access on Windows cannot reliably access the normal per-user pytest temporary root. This is
test isolation only; no runtime data is committed. pgvector, the audit ledger, outbox, workflow
checkpoints, and job queue are separate remaining Phase 2 batches.

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

Revision `20261004_0008` adds `evidence_gate_decisions`. Each tenant/Incident-scoped row stores the
canonical non-secret input snapshot, rules/schema versions, typed outcome and reasons, evaluated
Evidence IDs, model-confidence metadata, evaluation time, and SHA-256 input fingerprint. The
repository treats the tenant/Incident/candidate/fingerprint tuple as an idempotent identity and
rejects conflicting replay. Its insert and the hash-bound `evidence.gate_decided` audit event share
the caller transaction, so neither can commit alone.

Revision `20261004_0009` adds tenant-scoped `prompt_versions` and `prompt_lifecycle_events`.
Prompt content, fingerprint, model parameters, schema compatibility, creation trace, and rollback
predecessor are inserted once; lifecycle commands row-lock and update status only. A partial unique
index permits at most one active version per tenant and Prompt family. Each atomic lifecycle change
stores before/after fingerprints and statuses, the bounded regression result when applicable, and
the matching append-only audit event in the caller transaction.

Revision `20261005_0010` adds content-free `model_call_traces`. Composite foreign keys bind each
attempt to its tenant-owned Incident and exact registered Prompt version. The row copies exact
model/settings/schema metadata, request/response hashes, lifecycle timing, typed outcome, consistent
token counts, and integer-nanounit cost with a versioned source. Missing metering is explicit rather
than silently treated as zero. Start and terminal audit records commit atomically with trace state;
row locks and expected-state comparison reject duplicate completion.

Revision `20261006_0012` adds tenant/Incident-scoped `approvals` and append-only
`approval_lifecycle_events`. Each request binds exact proposal, Policy input, and Policy decision
fingerprints plus proposer, risk, separation requirement, and Policy-derived expiry. Status and
decision-field database checks mirror the finite lifecycle. Commands row-lock and compare the
complete expected aggregate, then commit its next state, before/after fingerprint snapshot, and
matching content-free audit event in one caller-owned transaction. A tenant-scoped unique Policy
decision fingerprint prevents duplicate Approval issuance for the same decision.

Revision `20261006_0013` adds immutable `approval_invalidations`. A one-per-Approval marker binds
the prior Approval/proposal hashes to the replacement proposal ID, higher version, full/material
fingerprints, actor, time, and unique audit event. The repository row-locks and compares the exact
Approval before atomically adding the marker and `approval.invalidated` event. The historical human
decision is retained, while the marker becomes an independent non-reuse guard for later execution.

Revision `20261013_0020` adds immutable `approval_review_snapshots` and the validated replacement
proposal document on `approval_invalidations`. A review snapshot is one-to-one with an Approval and
stores the complete remediation proposal, Policy input, and Policy decision under a canonical
fingerprint. Request creation inserts it atomically with the Approval, lifecycle event, and audit
record. Detail reads reconstruct the typed contracts and compare all Approval/Policy/proposal
bindings. Replacement content remains nullable only for upgrade compatibility with historical
invalidation rows; such a row fails the review API closed because a deterministic diff cannot be
proven.

Revision `20261009_0016` adds tenant/Incident-scoped `postmortems` and append-only
`postmortem_revisions`. The head stores the source draft fingerprint and latest optimistic version;
each immutable revision stores its parent fingerprint, author, bounded content, change summary,
exact confirmed Fact/Evidence IDs, schema version, and canonical fingerprint. The repository locks
and compares the head plus complete stored parent before appending one consecutive version, so stale
or concurrent edits cannot overwrite history. Creation/revision and their hash-only AuditEvent
commit atomically. Database triggers reject revision updates/deletes, while composite foreign keys,
unique version/fingerprint/audit bindings, and content/reference checks reject cross-scope or
malformed writes.

Revision `20261011_0017` makes service scope a required first-class Incident field and adds a
tenant/service/opened-time index for filtered newest-first reads. Legacy rows are backfilled only
from their linked Alert Group service using a deterministic aggregate. The migration aborts if any
Incident lacks that provenance; it never guesses a service. A database check mirrors the bounded
identifier grammar enforced by the domain and API.

Revision `20261012_0018` adds `diagnosis_progress`, one replay-safe current read projection per
workflow run. It stores only the validated plan structure, Tool Call references and status,
resource counters, bounded replan decisions, graph/checkpoint identity, failure codes, and UTC
timestamps; tool arguments/results, raw telemetry, prompts, secrets, and checkpoint payloads are
excluded. A composite foreign key binds the projection to the tenant-owned Incident. Every update
row-locks the run, validates legal forward or exact-replay transitions, and refreshes a canonical
SHA-256 fingerprint duplicated alongside the JSON snapshot. Reads revalidate the complete schema,
relational bindings, and fingerprint before returning any operator view.

Revision `20261013_0019` adds immutable `diagnosis_reports`. Each report preserves the exact
versioned structured output, disposition, canonical SHA-256 fingerprint, workflow run, successful
`diagnosis.hypothesis` Model Call, and production time. The repository accepts only a response hash
and completion time that exactly match that trace, and atomically appends a hash-only
`diagnosis.report_recorded` audit event. Reads revalidate the document, duplicated fields,
fingerprint, tenant/Incident binding, and Model Call trace. Evidence Gate decisions are exposed
only when their canonical claim snapshot matches a candidate in the latest report; stale or
unrelated decisions are never attached.

Revision `20261015_0021` adds `correlation_streams` and immutable `correlation_links`. A composite
stream key binds each tenant/Correlation ID to exactly one tenant-owned Incident. Link constraints
enforce the closed eight-component vocabulary, strict nonzero W3C Trace IDs, same-stream causation,
unique event and component/resource identities, schema version, and canonical SHA-256 fingerprint.
The repository creates or row-locks the stream claim before append, so concurrent exact delivery
replays one stored link while cross-Incident rebinding or changed-content replay fails closed.
Reads require tenant, Incident, and Correlation scope and revalidate every fingerprint plus the
bounded single-Alert-root causation timeline described in [the correlation contract](CORRELATION.md).
The transaction-owning workflow adapter opens a new session for each boundary, allowing an Incident
to span checkpoints, approval waits, execution, and a verification window without retaining a
database transaction. Deterministic event identities make a crash between boundaries replay-safe.

Revision `20261015_0022` adds required tenant, Incident, and workflow-run scope to every durable
job, binds the tenant/Incident pair to the owning Incident, indexes Incident queue history, and
caps attempts at the control-plane observation contract's bound of 128. An upgrade from the older
unscoped schema fails closed unless the queue is empty: the migration never guesses ownership for
in-flight work. New-database upgrades remain compatible with the metadata-created table shape.

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
service backfill refusal and success, combined tenant-scoped list filters, immediate and deferred
cancellation persistence, and concurrent Alert ingestion from sixteen independent transactions
followed by a replay storm. It also verifies correlation-ledger migration, eight-component round
trip, transaction-owned concurrent exact replay, scope isolation, and fingerprint-tamper refusal.
Unit tests retain
fail-closed coverage for defensive paths that valid
foreign keys and locks should make unreachable.

The fixed Phase 12 entry point is `python scripts/dev.py test --suite integration`. It verifies the
Docker daemon before collecting only `tests/integration`, disables cache and focused-run coverage
side effects, and leaves the complete repository quality gate unchanged. On 2026-10-17 it passed
all 100 collected PostgreSQL/pgvector cases against Docker Engine 29.8.0; see
[Phase 12 Test Matrix](PHASE_12_TEST_MATRIX.md) for the exact boundary and measured result.

The test suite uses an ignored repository-local `.pytest-runtime-*` directory because elevated
Docker access on Windows cannot reliably access the normal per-user pytest temporary root. This is
test isolation only; no runtime data is committed.

## LangGraph checkpoints

Phase 6 integrates the official asynchronous PostgreSQL LangGraph saver. Startup explicitly calls
its idempotent schema setup/migration operation before yielding the saver. Diagnosis graphs compile
with that saver and use a deterministic thread ID derived from canonical tenant, Incident, and
workflow-run identity. The raw identities are not exposed in the thread key; tenant, Incident,
workflow run, correlation, and causation IDs are attached as checkpoint metadata for reconstruction.
The production saver is wrapped by a transparent fail-open observer that records save, restore,
miss, resume, and fixed-class I/O failure signals after delegating to the official saver. It never
receives checkpoint channel values, writes, interrupts, task errors, or serialized state as
telemetry content.

The root graph uses LangGraph's required empty `checkpoint_ns`; non-empty namespaces are reserved
for compiled subgraphs. A fixed `diagnosis-` thread prefix plus the composite identity hash provides
the product namespace. Configuration is generated only from validated graph state, and an explicit
identity guard rejects any attempt to pair a config identity with another tenant/run state.

Checkpoint serialization disables pickle fallback and explicitly allowlists only the project graph
state types. The PostgreSQL adapter never accepts non-PostgreSQL URLs. A container integration test
proves setup, checkpoint history, latest-state restoration, completed-run resume without re-running
planning, metadata correlation, and isolation between workflow threads.

Diagnosis nodes can durably pause before a service effect and resume on the same thread. The
content-free interrupt carries only the node and stable operation identity. Checkpoint JSON arrays
are restored to immutable state tuples before strict validation. A cancellation directive is
applied at the same safe boundary and terminates the graph without dispatching that node's effect.
Service adapters use the stable operation identity to replay previously committed results rather
than repeat effects after delivery or worker retries.

`DiagnosisWorkflowRunner` checks the hashed thread before invocation. With no saved state it starts
the supplied run; with saved state it validates tenant, Incident, workflow-run, and correlation
identity and continues using `None` input so caller data cannot replace the checkpoint. Its bounded
history API derives content-free observations from PostgreSQL snapshots and classifies pending,
interrupted, failed, and complete checkpoints without copying task errors or interrupt values.
Integration tests close and recreate the saver/graph after every Diagnosis node boundary and also
cover the narrower effect-committed/checkpoint-not-yet-written failure window.

The Phase 8 Approval wait graph uses a separately prefixed `approval-` thread identity while
retaining the same strict serializer and PostgreSQL saver. Its checkpoint stores only bounded
references and fingerprints. Resume cannot supply an approval decision: the graph accepts only a
`RECHECK` directive, reloads the tenant-scoped Approval and invalidation marker, and advances only
for an unexpired, non-invalidated, fingerprint-matched `APPROVED` record. A container integration
test closes and recreates the saver and graph at the interrupt boundary to prove new-worker
restoration and authoritative external-state reload.

## Versioned embedding metadata

Revision `20261003_0002` enables the `vector` extension and adds
`incident_memory_embeddings`. Each row points to an authoritative Incident and retains its source
content SHA-256, provider, model and model version, content schema version, normalization version,
declared dimensions, creation time, and explicit reindex flag. A database check requires
`vector_dims(embedding)` to equal the declared positive dimension, and a versioned-source unique
key prevents ambiguous duplicates.

Revision `20261005_0011` adds `incident_memory_projections` as the authoritative, tenant-bound
closed-Incident source. The repository locks and revalidates the exact Incident state, version,
owner, and closure time before transactionally admitting a projection and its vector. A database
trigger requires every vector's Incident and source hash to resolve to that projection, including
for writes outside the repository. Exact generation replay returns the stored row; generation with
a new provider/model/model-version/schema/normalization identity marks prior vectors for the
Incident `reindex_required` before inserting the replacement. The bundled deterministic generator
supports mock-model and test operation without credentials. Tool Gateway similarity access remains
disabled, and historical memory remains reference-only rather than current Evidence.

The Phase 7 retrieval repository accepts a typed, tenant-bound query vector and verifies current
Incident ownership before issuing cosine search. It filters by closure freshness, projection time,
active reindex state, complete embedding identity, dimensions, and non-negative similarity; it
excludes the current Incident and applies a database result limit. Stable tie ordering and a
minimal reference-only result type prevent vectors, Evidence references, internal fingerprints,
confirmation/action references, tenant identifiers, or cross-tenant counts from leaving storage.

## Append-only audit ledger

Revision `20261003_0003` adds `audit_events`. Revision `20261016_0023` adds a database-assigned,
contiguous per-tenant sequence and a private transactional tenant head while retaining the original
64-bit global ordering key. The stable event ID prevents replay from creating the same logical
event twice.
Each row records a versioned dotted event type, payload schema version, actor, correlation and
causation IDs, typed target, UTC occurrence time, and optional canonical request/result SHA-256
digests. A canonical fingerprint covers every immutable field and is recomputed on reads. Request
and result bodies are deliberately excluded so the ledger does not become an uncontrolled secret
store.

The application adapter exposes append, integrity-checked correlation/target reads, and bounded
tenant export. PostgreSQL privileges deny runtime mutation of tenant heads and audit rows,
while owner-visible triggers independently reject `UPDATE`, `DELETE`, and `TRUNCATE`. Export uses
the tenant sequence as its cursor and binds each page to a reproducible manifest; head comparison
detects internal gaps and a missing tail. Database constraints reject malformed hashes and
duplicate tenant sequences. Integration tests prove migration round trips, sixteen concurrent
assignments, application-role append/mutation denial, deterministic export replay, and fail-closed
tamper/gap behavior. Retention, authorized export procedure, legal holds, and the limits of the
current non-anchored design are specified in [Audit ledger integrity, export, and
retention](AUDIT_LEDGER.md).

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
has a typed ID, dotted type, payload schema and durable payload reference, required tenant/Incident/
workflow identity, correlation/causation,
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

The repository emits content-free observations after each successful flush for enqueue, claim,
heartbeat, completion, retry, stale takeover, and exhausted stale routing. These signals report
typed queue outcomes, never payload references or error text, and do not replace the caller-owned
transaction or Audit Events. Observer failure cannot alter the lease transition.

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

## Recovery action persistence

Revision `20261006_0014` adds durable `action_executions`, active
`action_execution_locks`, and append-only `action_execution_events`. Execution idempotency is
scoped by tenant, actor, Incident, and caller key at the database level. The repository also takes
ordered transaction-scoped advisory locks for that scope and the server-resolved target, so
concurrent duplicates serialize before checking stored state and different keys cannot mutate the
same active target.

The persisted request fingerprint excludes attempt identity and start time but includes the exact
Approval, actor, proposal and Policy fingerprints, resolved target, and immutable before-snapshot
binding. Identical retries return the stored in-progress or terminal execution; changed-key reuse
fails closed. Initial claim stores the execution, target lock, lifecycle event, and append-only
audit atomically. Terminal completion updates the execution, records its after snapshot or stable
failure code, appends its lifecycle/audit event, and releases the target lock in one transaction.
An explicit replay append verifies both the incoming request fingerprint and currently stored
result under row lock, then transactionally records a distinct `REPLAYED` lifecycle/audit pair
without changing the execution. Application-level authorization rechecks, adapter dispatch/timeout
handling, and mandatory invocation of that replay append on every replay route remain required
before the Action Executor is complete or enabled.

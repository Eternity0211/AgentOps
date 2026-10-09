# Control-plane process composition

The Phase 2 control plane has two explicit installed entry points:

- `agentops-api` owns FastAPI/HTTP composition and exposes `/healthz`;
- `agentops-worker` owns the asynchronous polling lifecycle and exposes no HTTP application.

Both require `AGENTOPS_DATABASE_URL` using the `postgresql+asyncpg` driver. The API additionally
accepts bounded `AGENTOPS_API_HOST` and `AGENTOPS_API_PORT` settings. The worker requires a stable
opaque `AGENTOPS_WORKER_ID`, poll interval, concurrency limit, and shutdown grace period through
`AGENTOPS_WORKER_POLL_SECONDS`, `AGENTOPS_WORKER_CONCURRENCY`, and
`AGENTOPS_WORKER_SHUTDOWN_GRACE_SECONDS`. Missing, malformed, or out-of-range values fail before
either process begins serving. Error messages name the setting but never echo its value, so a
credential-bearing database URL is not disclosed.

The worker also owns the only recovery-write composition boundary. The capability remains off
unless `AGENTOPS_RECOVERY_MUTATION_ENABLED=true` is supplied exactly; malformed boolean values
fail startup, and `AGENTOPS_RECOVERY_DISPATCH_TIMEOUT_SECONDS` is bounded to 0.1–300 seconds. The
composition accepts only a typed server-owned deployment backend and wires preflight, immutable
snapshots, PostgreSQL lifecycle execution, the bounded dispatcher, persisted verification, and
transaction-owning PASS/FAIL routers into one `RollbackRecoveryCoordinator`. Disabling the flag
rejects before preflight, snapshot creation, durable claim, or backend invocation. This setting
does not create an API write endpoint or make the model an execution authority.

The API lifespan starts no background worker and has no worker route. The worker module imports no
FastAPI or Uvicorn surface. Its default source intentionally yields no work until workflow handlers
exist. The worker requests no more jobs than its available concurrency capacity and rejects a
source that violates that limit. Every work item provides a persisted-cancellation probe: the
runtime checks it before execution and passes it into the handler for safe-boundary checks.
SIGINT/SIGTERM request cooperative shutdown; the worker stops claiming, waits through its bounded
grace period, then cancels overdue local tasks without acknowledging their database lease.
PostgreSQL stale-lease recovery can therefore safely reassign them. This does not claim that
production workflow service adapters or a database-backed default `WorkSource` already exist. The
Phase 6 Diagnosis runtime now provides the handler-side checkpoint-aware runner: a replacement
worker resumes an existing PostgreSQL thread rather than replacing its state, while exact operation
identities let service adapters replay effects committed before a worker exit.

The repository deliberately does not ship a production Kubernetes provider. A deployment adapter
must be injected by the trusted worker deployment and still receives only the preflight-resolved
typed target and idempotency key. The reference local simulator backend remains test-only.

Tests verify independent settings, fail-closed startup, the API health contract, absence of worker
routes/tasks, the HTTP-free worker source, concurrency saturation, cancellation before and during
work, capacity-contract violation, cooperative signal shutdown, grace-period expiry, both CLI
entry points, keyboard interruption, default-off recovery configuration, malformed/unsafe setting
rejection, transaction-owned PASS/FAIL routing, and the explicitly enabled full rollback chain.

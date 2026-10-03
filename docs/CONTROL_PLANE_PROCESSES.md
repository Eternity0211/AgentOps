# Control-plane process composition

The Phase 2 control plane has two explicit installed entry points:

- `agentops-api` owns FastAPI/HTTP composition and exposes `/healthz`;
- `agentops-worker` owns the asynchronous polling lifecycle and exposes no HTTP application.

Both require `AGENTOPS_DATABASE_URL` using the `postgresql+asyncpg` driver. The API additionally
accepts bounded `AGENTOPS_API_HOST` and `AGENTOPS_API_PORT` settings. The worker requires a stable
opaque `AGENTOPS_WORKER_ID` and accepts a bounded `AGENTOPS_WORKER_POLL_SECONDS` interval. Missing,
malformed, or out-of-range values fail before either process begins serving. Error messages name
the setting but never echo its value, so a credential-bearing database URL is not disclosed.

The API lifespan starts no background worker and has no worker route. The worker module imports no
FastAPI or Uvicorn surface and handles a cooperative stop event between bounded polls. Its current
default poller intentionally performs no work: PostgreSQL JobLease claiming, heartbeat, retry,
stale-lease recovery, concurrency limits, and cancellation arrive in the next dedicated Phase 2
batches. This composition milestone proves ownership and deployment boundaries without claiming
that the workflow queue already exists.

Tests verify independent settings, fail-closed startup, the API health contract, absence of worker
routes/tasks, the HTTP-free worker source, bounded polling and cooperative shutdown, both CLI
entry points, and keyboard interruption.

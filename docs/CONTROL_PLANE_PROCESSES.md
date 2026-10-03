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
default poller intentionally performs no work: the PostgreSQL JobLease repository now provides
claiming, heartbeat, retry, stale-lease recovery, and terminal failure routing, while wiring it into
bounded worker concurrency, graceful shutdown, and cancellation remains the next Phase 2 batch.
This composition milestone proves ownership and deployment boundaries without claiming that the
worker runtime already executes workflow jobs.

Tests verify independent settings, fail-closed startup, the API health contract, absence of worker
routes/tasks, the HTTP-free worker source, bounded polling and cooperative shutdown, both CLI
entry points, and keyboard interruption.

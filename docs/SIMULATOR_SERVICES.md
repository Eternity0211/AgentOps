# Simulator Service Contracts

The diagnosed system has four independently runnable FastAPI roles built from one locked Python image. Order persists confirmed orders in simulator PostgreSQL, Inventory performs atomic reservations in simulator Redis, and every role emits the bounded OpenTelemetry signal contract documented in `docs/OBSERVABILITY.md`.

## Request path

```text
POST Gateway /v1/checkout
  -> POST Order /v1/orders
       -> POST Inventory /v1/reservations
       -> POST Payment /v1/authorizations
```

The request schema requires a bounded client `order_id`, 1–20 line items with bounded SKU/quantity values, a positive bounded minor-unit amount, and a three-letter uppercase currency. Inventory derives `res-{order_id}` and Payment derives `auth-{order_id}`; Order confirms only after both typed downstream contracts validate and PostgreSQL accepts the idempotent write. Network, HTTP, malformed JSON, wrong-shape downstream responses, and unavailable data stores do not become false success.

Every service exposes `/healthz`, `/readyz`, and `/versionz`. Health proves that the process can answer; readiness additionally executes a bounded `SELECT 1` for Order and `PING` for Inventory. Version reports the same validated service version, deployment ID, optional previous version, and schema version emitted by the startup deployment marker. Compose health checks use readiness, so Gateway cannot become healthy through an Order instance whose PostgreSQL dependency is unavailable, and Order cannot proceed through an Inventory instance whose Redis dependency is unavailable.

## Data dependency contract

Order creates `simulator_orders` on first use and inserts with `ON CONFLICT (order_id) DO NOTHING`. Its response includes `created=true` for the first row and `created=false` for an existing `order_id`; no duplicate row is created. The database pool is lazy, bounded to five connections, and pool acquisition, connection setup, and command paths all have a configured deadline. The pool-exhaustion fixture holds exactly those five slots, exposes size/idle observations, and releases them during shutdown.

Inventory executes one Redis Lua script. The script first verifies all requested SKU quantities, only then decrements stock, and finally records the reservation with a one-hour TTL. An insufficient line therefore cannot leave earlier lines partially decremented. A repeated `order_id` returns the existing `res-{order_id}` as `already_reserved` without decrementing stock again. Initial stock is deterministic at 100 units per SKU for the Phase 1 simulator.

The Redis-timeout fixture exercises the same configured adapter deadline but deliberately never invokes the underlying `PING` or Lua callable. This makes readiness and reservation failures deterministic and side-effect free; replacing Inventory removes the fixture without changing Redis data.

Credentials are read only from mounted secret files. Connection strings, passwords, request payloads, and stock values are not logged. Each dependency operation emits one structured record with only `event`, `dependency`, `operation`, `result`, `duration_ms`, and the validated `correlation_id`. Adapter timeouts and connection failures map to stable HTTP 503 responses; insufficient inventory maps to HTTP 409. Internal exception text is not returned to clients.

## Correlation contract

`X-Correlation-ID` is the sole request-correlation header. Gateway creates a UUID when it is absent. A supplied value must be 1–128 characters from the conservative `[A-Za-z0-9._:-]` set and cannot start with punctuation. The same validated value is returned in every response and forwarded on every internal HTTP request. Invalid values fail with HTTP 400 before a handler or downstream call runs.

This identifier is for correlation, not authentication or authorization. It is attached to structured logs and trace attributes without being treated as trusted identity; it is intentionally excluded from metric dimensions to avoid unbounded cardinality. W3C trace context is propagated independently so traces remain standards-compatible.

## Runtime composition

`Dockerfile.simulator` uses Python 3.12.14 and the committed `uv.lock`, runs as UID/GID 10001, and selects a role through:

```text
python -m agentops_incident_commander.simulator.main gateway
python -m agentops_incident_commander.simulator.main order
python -m agentops_incident_commander.simulator.main inventory
python -m agentops_incident_commander.simulator.main payment
```

Compose exposes only Gateway on loopback port `8080`; Order, Inventory, and Payment remain on the internal simulator network. Order mounts only the PostgreSQL password secret and waits for `simulator-postgres`; Inventory mounts only the Redis password secret and waits for `simulator-redis`.

Docker daemon startup was not available on the implementation host, so this batch verifies adapter behavior with deterministic protocol fakes, the full HTTP chain in-process, and normalized Compose wiring. It does not claim a successful image build or live multi-container request yet.

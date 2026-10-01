# Simulator Service Contracts

The diagnosed system now has four independently runnable FastAPI roles built from one locked Python image. This batch establishes deterministic request flow only; PostgreSQL/Redis client behavior and OpenTelemetry instrumentation remain separate Phase 1B batches.

## Request path

```text
POST Gateway /v1/checkout
  -> POST Order /v1/orders
       -> POST Inventory /v1/reservations
       -> POST Payment /v1/authorizations
```

The request schema requires a bounded client `order_id`, 1–20 line items with bounded SKU/quantity values, a positive bounded minor-unit amount, and a three-letter uppercase currency. Inventory derives `res-{order_id}` and Payment derives `auth-{order_id}`; Order confirms only after both typed downstream contracts validate. Network, HTTP, malformed JSON, and wrong-shape downstream failures do not become false success.

Every service exposes `/healthz` and `/readyz`. These endpoints currently prove process-level readiness only; dependency-aware readiness is added with the PostgreSQL/Redis integration batch.

## Correlation contract

`X-Correlation-ID` is the sole request-correlation header. Gateway creates a UUID when it is absent. A supplied value must be 1–128 characters from the conservative `[A-Za-z0-9._:-]` set and cannot start with punctuation. The same validated value is returned in every response and forwarded on every internal HTTP request. Invalid values fail with HTTP 400 before a handler or downstream call runs.

This identifier is for correlation, not authentication or authorization. Later OpenTelemetry work will add it to structured logs and trace attributes without treating it as trusted identity.

## Runtime composition

`Dockerfile.simulator` uses Python 3.12.14 and the committed `uv.lock`, runs as UID/GID 10001, and selects a role through:

```text
python -m agentops_incident_commander.simulator.main gateway
python -m agentops_incident_commander.simulator.main order
python -m agentops_incident_commander.simulator.main inventory
python -m agentops_incident_commander.simulator.main payment
```

Compose exposes only Gateway on loopback port `8080`; Order, Inventory, and Payment remain on the internal simulator network. Docker daemon startup was not available on the implementation host, so this batch verifies application behavior in-process plus normalized Compose wiring and does not claim a successful image build or live multi-container request yet.

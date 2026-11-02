# Configuration reference

AgentOps configuration is fail-closed and process-scoped. This reference lists the supported
settings; it is not a license to add arbitrary environment forwarding. Secret values belong in a
deployment secret manager or ignored local files and must never be committed.

## Precedence and ownership

- The local task runner reads only allowlisted settings from the ignored `.env` file. An explicit
  process environment value overrides the corresponding `.env` value.
- Docker Compose owns simulator service-discovery, dependency, telemetry, and deployment-marker
  settings. Operators should change the documented top-level inputs, not inject arbitrary service
  environment keys.
- `agentops-api` and `agentops-worker` load their own process settings directly from the
  deployment environment. They are not started by the local Compose stack.
- Evaluation configuration is versioned under `evaluation/`. Mock mode accepts no provider key,
  model override, output path, or arbitrary test selector.

## Local Compose settings

Copy `.env.example` to the ignored `.env` file and set these values:

| Setting | Required/default | Purpose and constraints |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `agentops` | Local Compose resource prefix. |
| `BIND_ADDRESS` | `127.0.0.1` | Published runtime address; health validation accepts loopback only. |
| `GATEWAY_PORT` | `8080` | Diagnosed-system Gateway host port. |
| `CONTROL_DB_NAME` | `agentops` | Local control-plane database name. |
| `CONTROL_DB_USER` | `agentops` | Local bootstrap owner, not an API/worker runtime identity. |
| `CONTROL_DB_PASSWORD_FILE` | required file | Control PostgreSQL bootstrap credential. |
| `SIMULATOR_DB_NAME` | `commerce` | Diagnosed Order database name. |
| `SIMULATOR_DB_ADMIN_USER` | `simulator_admin` | First-initialization database owner. |
| `SIMULATOR_DB_ADMIN_PASSWORD_FILE` | required file | Simulator owner credential. |
| `SIMULATOR_DB_USER` | `simulator_app` | Order's restricted database login. |
| `SIMULATOR_DB_PASSWORD_FILE` | required file | Restricted Order credential. |
| `SIMULATOR_REDIS_USER` | `inventory_app` | Inventory's key/command-scoped Redis user. |
| `SIMULATOR_REDIS_PASSWORD_FILE` | required file | Inventory Redis credential. |
| `GRAFANA_ADMIN_USER` | `agentops-admin` | Local provisioning/debugging administrator. |
| `GRAFANA_ADMIN_PASSWORD_FILE` | required file | Grafana administrator credential. |
| `PROMETHEUS_PORT` | `9090` | Loopback-only Prometheus port. |
| `PROMETHEUS_RETENTION` | `24h` | Local Prometheus retention argument. |
| `LOKI_PORT` | `3100` | Loopback-only Loki port. |
| `TEMPO_PORT` | `3200` | Loopback-only Tempo port. |
| `GRAFANA_PORT` | `3000` | Loopback-only Grafana port. |
| `GROUND_TRUTH_ACCESS_FILE` | evaluation only | Credential used only by `compose.evaluation.yaml`. |

All five runtime secret files must be readable, non-empty, at most 4096 bytes, use distinct
resolved paths, and contain distinct values. `doctor` checks those properties without printing
content. Ground Truth uses a sixth independent file that runtime profiles never receive.

The service version inputs `GATEWAY_SERVICE_VERSION`, `ORDER_SERVICE_VERSION`,
`INVENTORY_SERVICE_VERSION`, and `PAYMENT_SERVICE_VERSION` default to `1.0.0`. Their paired
`*_DEPLOYMENT_ID` values identify a controlled rollout, and optional `*_PREVIOUS_VERSION` values
identify the predecessor. They are validated diagnostic facts, not execution authority.

## API process settings

| Setting | Required/default | Constraint |
| --- | --- | --- |
| `AGENTOPS_DATABASE_URL` | required | Must use `postgresql+asyncpg://`; production must use the restricted runtime login. |
| `AGENTOPS_API_HOST` | `0.0.0.0` | Bind address supplied to Uvicorn. |
| `AGENTOPS_API_PORT` | `8000` | Integer from 1 through 65535. |

The core API accepts a deployment-owned principal resolver. The installed `agentops-api` entry
point deliberately has no production authentication adapter configured, so business endpoints
fail closed with `401` until composition supplies one. `/healthz` is only process health.

## Worker process settings

| Setting | Required/default | Constraint |
| --- | --- | --- |
| `AGENTOPS_DATABASE_URL` | required | Same restricted PostgreSQL driver/identity rule as API. |
| `AGENTOPS_WORKER_ID` | required | Stable, non-empty lease-owner identity. |
| `AGENTOPS_WORKER_POLL_SECONDS` | `1` | Numeric, 0.05–60 seconds. |
| `AGENTOPS_WORKER_CONCURRENCY` | `4` | Integer, 1–64. |
| `AGENTOPS_WORKER_SHUTDOWN_GRACE_SECONDS` | `30` | Numeric, 0.1–300 seconds. |
| `AGENTOPS_RECOVERY_MUTATION_ENABLED` | `false` | Exact `true`/`false`; enabling alone supplies no backend or approval authority. |
| `AGENTOPS_RECOVERY_DISPATCH_TIMEOUT_SECONDS` | `30` | Numeric, 0.1–300 seconds. |

The installed worker entry point currently uses an explicit no-work source. Production JobLease
polling and workflow handlers must be injected by trusted composition; starting the process alone
does not run incident workflows.

## Telemetry settings

Both control-plane and simulator telemetry adapters support:

| Setting | Default | Constraint |
| --- | --- | --- |
| `OTEL_SDK_ENABLED` | `false` in process code; Compose sets `true` | Exact boolean accepted by the adapter. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | Deployment-owned OTLP/HTTP endpoint. |
| `OTEL_EXPORT_TIMEOUT_SECONDS` | `2` | Bounded exporter timeout. |
| `OTEL_METRIC_EXPORT_INTERVAL_MILLIS` | `5000` | Metric export interval. |
| `DEPLOYMENT_ENVIRONMENT` | `local` | Low-cardinality environment label. |
| `AGENTOPS_SERVICE_VERSION` | `0.1.0` | Control-plane version label. |

Telemetry settings cannot authorize an action. Export failures are observed but do not alter
business results; absence of telemetry is never evidence of recovery.

## Validation commands

```text
python scripts/dev.py doctor
python scripts/dev.py compose
python scripts/dev.py quality
```

`doctor` checks the local runtime inputs and Docker availability. `compose` verifies the exact
service/network/secret/mount topology without starting containers. `quality` verifies code,
documentation, contracts, tests, coverage, and package build.

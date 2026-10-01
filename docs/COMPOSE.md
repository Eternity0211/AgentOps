# Local Compose Foundation

The checked-in `compose.yaml` establishes the Phase 1B trust and resource boundaries and runs the four simulator application roles. A passing static contract does not claim that the full simulator started on this host; runtime startup remains an explicit verification item until a Docker daemon is available.

## Profiles and isolation

| Profile | Current services | Networks | Persistent volumes |
| --- | --- | --- | --- |
| `control-plane` | control PostgreSQL | `control-plane` | `control_postgres_data` |
| `simulator` | Gateway, Order, Inventory, Payment, diagnosed PostgreSQL and Redis | `ingress` for Gateway; internal `simulator` for service traffic | `simulator_postgres_data`, `simulator_redis_data` |
| `observability` | Prometheus, Loki, Tempo, OpenTelemetry Collector | `observability`; Collector also receives on `simulator` | `prometheus_data`, `loki_data`, `tempo_data` |
| future `evaluation` | no service until the isolated evaluator batch | reserved internal `evaluation` network | none |

Service and data networks are internal. The explicit `ingress` network exists only for Gateway, whose port `8080` is published on loopback. Prometheus `9090`, Loki `3100`, and Tempo `3200` are also bound to `127.0.0.1` by default.

All application roles export OTLP/HTTP over the internal `simulator` network to the Collector. The Collector's metrics, logs, and traces pipelines route to Prometheus, Loki, and Tempo respectively; its receiver ports are not published to the host. See `docs/OBSERVABILITY.md` for the signal and redaction contract.

Each application role also receives an explicit service version and unique deployment ID, with an optional previous version. These are non-secret, validated diagnostic facts used by the startup deployment event and `/versionz`; they do not grant mutation authority or imply that a deployment occurred at container startup.

Each current container has an explicit profile, image version, health check, read-only root filesystem, init process, `no-new-privileges`, named or temporary writable storage, and limits of `0.50` CPU, `512 MiB` memory, and 200 processes. Redis additionally limits its dataset to `192 MiB`. These are local-lab bounds, not capacity claims.

## Secret setup

1. Copy `.env.example` to the ignored `.env` file.
2. Create `secrets/control-db-password.txt`, `secrets/simulator-db-password.txt`, and `secrets/simulator-redis-password.txt`.
3. Put a distinct, non-empty local-only credential in each file.
4. Never use a production, personal, or shared credential in this lab.

The secret files and `.env` are ignored. Compose mounts secrets as files; PostgreSQL uses `POSTGRES_PASSWORD_FILE`, and Redis builds an ephemeral configuration in its read-only container instead of placing a password in the committed command or environment.

## Static validation

Run:

```text
python scripts/dev.py compose
```

The check renders all implemented profiles with synthetic files inside the ignored `.docker-config/` directory and asserts the approved services, profiles, internal networks, health checks, resource bounds, loopback-only published ports, named volumes, secret-file usage, and absence of rendered secret content. It does not pull images or require the Docker daemon.

The initial versions were selected from official upstream release streams on 2026-10-01: [PostgreSQL releases](https://www.postgresql.org/docs/release/), [Redis releases](https://github.com/redis/redis/releases), [Prometheus releases](https://github.com/prometheus/prometheus/releases), [Loki releases](https://github.com/grafana/loki/releases), [Tempo releases](https://github.com/grafana/tempo/releases), and [OpenTelemetry Collector releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases). Phase 12 will add digest locking, update policy, scanning, and provenance rather than overstating tag immutability here.

## Start, inspect, and stop

With Docker Engine running and the three ignored secret files present:

```text
python scripts/dev.py up
python scripts/dev.py status
python scripts/dev.py down
```

`up` executes four bounded stages: static Compose validation, Docker daemon detection, profile startup with Compose `--wait`, and the repository-owned runtime health checker. The health checker accepts only loopback targets and allowlisted port settings, limits each response to 1 MB, gives individual HTTP calls a two-second deadline, and gives the complete poll a 60-second deadline. It verifies:

- Gateway `/readyz` reports the Gateway role ready;
- Gateway `/versionz` contains deployment ID, version, and schema version;
- Prometheus, Loki, and Tempo readiness endpoints answer successfully;
- Prometheus reports the Collector `otel-collector:9464` scrape target as `up`.

If Compose starts but startup or health validation fails, the runner executes `down --remove-orphans` and returns the original failure code. Cleanup failure is reported separately and cannot hide the cause. Named volumes are never removed by these commands. `status` checks running containers and reruns the same endpoint contract; it does not mutate the stack.

Typical fail-closed diagnostics are `executable-not-found`, Docker daemon unavailable, Compose secret/configuration failure, startup timeout, a named endpoint contract failure, or a Collector target that is not `up`. Fix the named prerequisite and rerun `up`; do not bypass the readiness checker.

## Current verification boundary

Order receives only the simulator PostgreSQL secret and waits for the database health check. Inventory receives only the simulator Redis secret and waits for Redis health. The shared application health check calls `/readyz`: it probes PostgreSQL from Order and Redis from Inventory with a bounded timeout, while Gateway and Payment report process readiness. `/healthz` remains a liveness endpoint and does not probe dependencies.

On the implementation host, Docker Compose v5.5.1 parsed and normalized the complete file, but Docker Engine was not running. An actual `python scripts/dev.py up` run passed static validation and failed at the daemon preflight before any startup mutation, as designed. Therefore the current evidence covers topology, configuration, deterministic adapter/runtime-check tests, and in-process HTTP behavior only. Live container startup, inter-service telemetry queries, and clean shutdown remain required before the Phase 1 exit claim.

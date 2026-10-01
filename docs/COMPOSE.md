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

## Current verification boundary

Order receives only the simulator PostgreSQL secret and waits for the database health check. Inventory receives only the simulator Redis secret and waits for Redis health. The shared application health check calls `/readyz`: it probes PostgreSQL from Order and Redis from Inventory with a bounded timeout, while Gateway and Payment report process readiness. `/healthz` remains a liveness endpoint and does not probe dependencies.

On the implementation host, Docker Compose v5.5.1 parsed and normalized the complete file, but the Docker daemon was not running. Therefore the current evidence covers topology, configuration, deterministic adapter tests, and in-process HTTP behavior only. Live container startup, inter-service telemetry, and clean shutdown remain open Phase 1B verification work and must pass before the Phase 1 exit claim.

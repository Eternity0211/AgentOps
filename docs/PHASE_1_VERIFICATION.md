# Phase 1 Live Verification

This record captures the reproducible functional evidence used to close the Phase 1 exit gate. It does not establish production capacity, reliability, recovery quality, or benchmark latency.

## Environment and commands

- Date: 2026-10-02 (Asia/Shanghai)
- Host: local Windows development machine
- Docker Engine: 29.8.0
- Docker Compose: v5.5.1
- Runtime: Python 3.12.14
- Stack command: `python scripts/dev.py up`
- Final status command: `python scripts/dev.py status`
- Cleanup command: `python scripts/dev.py down`
- Fault commands: `python scripts/dev.py fault inject --scenario <allowlisted-name> --run-id <validated-id>` followed by the matching `fault clean`

Local-only ignored credentials were distinct synthetic values. Because ports 9090 and 3200 were already owned by another local project, this run used ignored `.env` overrides `PROMETHEUS_PORT=19090`, `LOKI_PORT=13100`, and `TEMPO_PORT=13200`. The task runner loaded only the five allowlisted non-secret host/port settings so its health checks targeted the same endpoints as Compose.

## Baseline evidence

The simulator and observability profiles started ten containers: Gateway, Order, Inventory, Payment, simulator PostgreSQL, simulator Redis, Prometheus, Loki, Tempo, and OpenTelemetry Collector. The separate control-plane profile also started its PostgreSQL container and reached healthy status, covering all 11 services in the implemented topology. `python scripts/dev.py status` reported every simulator/observability container healthy and `[runtime] passed checks=6` for:

1. Gateway readiness
2. Gateway deployment/version marker
3. Prometheus readiness
4. Prometheus Collector scrape target `otel-collector:9464` with health `up`
5. Loki readiness
6. Tempo readiness

Live startup exposed and corrected two configuration defects that static rendering could not prove: the unpublished Collector 0.162.0 multi-architecture image and PostgreSQL 18's version-aware volume layout. The verified stack uses Collector 0.161.0 and mounts PostgreSQL named volumes at `/var/lib/postgresql`.

## Scenario evidence

| Scenario | Live observation | Cleanup observation |
| --- | --- | --- |
| `http-500` | Gateway checkout returned 502 in 1.107 s; Prometheus recorded Order `/v1/orders` 500 and Gateway `/v1/checkout` 502 | Order recreation restored checkout 200 |
| `db-pool-exhaustion` | Gateway checkout returned 502 in 2.057 s at the configured dependency boundary; Gateway health stayed 200 | Order recreation completed successfully |
| `redis-timeout` | Gateway checkout returned 502 in 2.026 s at the configured dependency boundary | Inventory recreation completed successfully |
| `downstream-latency` | Gateway checkout returned 502 in 2.026 s, bounding Payment's fixed three-second delay at Order's two-second client timeout | Payment recreation completed successfully |
| `memory-leak` | Three checkouts returned 200; Order logged retained bytes of 1,048,576, 2,097,152, and 3,145,728 against a 33,554,432-byte hard scenario limit | Order process recreation released process-local retention |
| `bad-configuration` | Payment health returned 200, readiness returned 503, and Gateway checkout returned 502 in 0.219 s | Payment recreation completed successfully |

Durations above are observations from this one run and are included only to prove configured timeout bounds, not to claim latency performance.

## Telemetry evidence

- Prometheus returned live `simulator_http_server_requests_total` series for all four service roles and the injected 500/502 route statuses.
- Loki's labels API returned OTLP resource labels including `service_name`.
- Tempo search returned simulator traces with trace IDs, root service names, and root span names.
- The final runtime check again observed the Collector target as `up`.

The runtime and model-capable paths had no Ground Truth mount or credential. Fault cleanup remained evaluator/developer infrastructure and received no platform recovery credit.

## Limits

This was one local functional run with sequential scenarios. It did not measure load, concurrency capacity, availability, long-duration retention, diagnosis accuracy, recovery rate, token use, cost, crash recovery, or production behavior. Those claims remain gated by the versioned Phase 12 evaluation and resilience work.

# Simulator Observability Baseline

The four diagnosed-system services emit OpenTelemetry traces, metrics, and logs through OTLP/HTTP to the local Collector. The Collector exposes metrics for Prometheus scraping and forwards logs and traces to Loki and Tempo. This is diagnosed-system telemetry only; control-plane and agent-workflow observability is delivered in later phases.

## Signal contract

Each process uses a resource with `service.name=agentops-simulator-{role}`, package `service.version`, and `deployment.environment`. The signal set is deliberately bounded:

- Server spans use the matched FastAPI route, HTTP method/status, and validated correlation ID. Unknown paths collapse to `unmatched`; query strings and request/response bodies are never attributes.
- Internal HTTP client spans identify only the allowlisted destination service, method, and route. W3C `traceparent` is propagated together with `X-Correlation-ID`.
- PostgreSQL and Redis spans contain dependency system, operation name, result status, and correlation ID. They do not contain statements, credentials, order payloads, stock values, or exception text.
- `simulator.http.server.requests` counts completed requests using method, matched route, and status dimensions.
- `simulator.http.server.duration` records milliseconds with the same bounded dimensions.
- The `http_request` log record contains service, method, matched route, status, duration, and correlation ID. The SDK binds its trace and span IDs from the active request context.

Exporter work is batched with bounded queues and two-second default export deadlines. Telemetry configuration or background export failure degrades to no-op/lost telemetry and cannot turn a valid business request into a failure. Shutdown flush is also bounded. These behaviors prioritize simulator availability; exporter failures remain visible in local SDK diagnostics and will gain explicit alerting in the later observability-hardening phase.

## Configuration

Compose enables the SDK for all four roles and supplies only non-secret settings:

| Variable | Local value | Constraint |
| --- | --- | --- |
| `OTEL_SDK_ENABLED` | `true` | Explicit opt-in; absent defaults to no-op for tests and direct library use |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | Credential-free HTTP(S) base URL; no query or fragment |
| `OTEL_EXPORT_TIMEOUT_SECONDS` | `2` | Greater than zero and at most 30 seconds |
| `OTEL_METRIC_EXPORT_INTERVAL_MILLIS` | `5000` | 1,000–300,000 milliseconds |
| `DEPLOYMENT_ENVIRONMENT` | `local` | Non-secret resource label |

The application expands the base endpoint to `/v1/traces`, `/v1/metrics`, and `/v1/logs`, following the official [OTLP exporter endpoint convention](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/). The selected SDK is OpenTelemetry Python 1.45.0; traces and metrics are stable while the upstream Python logs signal remains under development, as documented in the official [Python signal status](https://opentelemetry.io/docs/languages/python/).

## Collector routes

`config/observability/otel-collector.yml` has three independent pipelines, each with the memory limiter and batch processor:

```text
OTLP metrics -> Collector Prometheus exporter :9464 -> Prometheus scrape
OTLP logs    -> Collector OTLP/HTTP exporter   -> Loki /otlp
OTLP traces  -> Collector OTLP/HTTP exporter   -> Tempo :4318
```

Prometheus, Loki, Tempo, and the Collector share only the internal observability network; the Collector additionally joins the internal simulator network to receive OTLP. No telemetry receiver is published to the host.

## Verification boundary

Unit tests use in-memory exporters to assert trace hierarchy/propagation, metric names and attributes, log trace/span linkage, redaction boundaries, invalid configuration, disabled mode, exporter failure, and bounded shutdown. Static tests assert all service OTLP settings and all three Collector destinations.

The Docker daemon was unavailable on the implementation host. Therefore no claim is made yet that a live Collector received data or that Prometheus/Loki/Tempo queries returned it. Those runtime checks remain part of Phase 1 startup/readiness and smoke-test work.

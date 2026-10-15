# Simulator Observability Baseline

The four diagnosed-system services emit OpenTelemetry traces, metrics, and logs through OTLP/HTTP to the local Collector. The Collector exposes metrics for Prometheus scraping and forwards logs and traces to Loki and Tempo. This is diagnosed-system telemetry only; control-plane and agent-workflow observability is delivered in later phases.

## Signal contract

Each process uses a resource with `service.name=agentops-simulator-{role}`, package `service.version`, and `deployment.environment`. The signal set is deliberately bounded:

- Server spans extract an incoming W3C `traceparent` before starting, then use the matched FastAPI route, HTTP method/status, and validated correlation ID. Unknown paths collapse to `unmatched`; query strings and request/response bodies are never attributes.
- Internal HTTP client spans identify only the allowlisted destination service, method, and route. W3C `traceparent` is propagated together with `X-Correlation-ID`; the downstream server therefore remains in the same trace rather than creating an unrelated root.
- PostgreSQL and Redis spans contain dependency system, operation name, result status, and correlation ID. PostgreSQL spans also contain bounded pool size/idle observations, allowing saturation to be diagnosed without a Ground Truth label. They do not contain statements, credentials, order payloads, stock values, or exception text.
- A Redis deadline records `error.type=timeout` on the dependency Span and a bounded structured timeout event containing dependency, operation, and timeout duration. Scenario/run labels and request data are excluded.
- The Payment latency fixture is visible through the normal server duration histogram and Span timing; Order records the downstream client failure without any injected-cause label.
- The bounded memory fixture records retained bytes, allocation count, and the hard limit on Order request Spans and in structured events, without cause labels.
- The configuration fixture uses normal Payment 503 request metrics, Spans, and access logs; configuration values and injected-cause labels are absent.
- `simulator.http.server.requests` counts completed requests using method, matched route, and status dimensions.
- `simulator.http.server.duration` records milliseconds with the same bounded dimensions.
- `simulator.http.client.requests` and `simulator.http.client.duration` use only destination service, method, allowlisted route, bounded status (`100`–`599` or `transport_error`), and `ok`/`error`. HTTP failures, invalid JSON, and transport failures cannot add response bodies, URLs, or exception text.
- `simulator.dependency.operations` and `simulator.dependency.duration` use only `postgres`/`redis`, the closed adapter operation, and `ok`/`error`. Correlation remains in traces and logs and is deliberately excluded from metric labels.
- The `http_request` log record contains service, method, matched route, status, duration, and correlation ID. The SDK binds its trace and span IDs from the active request context.
- `http_client_request` and `dependency_operation` OTLP logs contain the same bounded dimensions, duration, and validated correlation ID and inherit the active trace/span IDs.
- Each process emits `service.deployment.changed` at startup and after every in-process typed deployment transition. Event schema `1.0` contains service, deployment ID, current and optional previous version, deployment environment, and an explicit UTC `event.observed_at`. A matching `/versionz` response exposes the typed deployment facts for deterministic health verification. The observation time is not represented as an unverified rollout start time.

Exporter work is batched with bounded queues and two-second default export deadlines. Telemetry configuration or background export failure degrades to no-op/lost telemetry and cannot turn a valid business request, dependency result, or deployment transition into a failure. Shutdown flush is also bounded. These behaviors prioritize simulator availability; exporter failures remain visible in local SDK diagnostics and gain actionable alerting in the dashboard/alert batch of Phase 11.

## Configuration

Compose enables the SDK for all four roles and supplies only non-secret settings:

| Variable | Local value | Constraint |
| --- | --- | --- |
| `OTEL_SDK_ENABLED` | `true` | Explicit opt-in; absent defaults to no-op for tests and direct library use |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | Credential-free HTTP(S) base URL; no query or fragment |
| `OTEL_EXPORT_TIMEOUT_SECONDS` | `2` | Greater than zero and at most 30 seconds |
| `OTEL_METRIC_EXPORT_INTERVAL_MILLIS` | `5000` | 1,000–300,000 milliseconds |
| `DEPLOYMENT_ENVIRONMENT` | `local` | 1–64 character conservative non-secret resource label |
| `SERVICE_VERSION` | role-specific baseline | Deployed service version used by the resource and deployment marker |

The application expands the base endpoint to `/v1/traces`, `/v1/metrics`, and `/v1/logs`, following the official [OTLP exporter endpoint convention](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/). The selected SDK is OpenTelemetry Python 1.45.0; traces and metrics are stable while the upstream Python logs signal remains under development, as documented in the official [Python signal status](https://opentelemetry.io/docs/languages/python/).

Deployment marker values use a conservative character set and fixed size limits. `SERVICE_VERSION`, `DEPLOYMENT_ID`, and optional `PREVIOUS_SERVICE_VERSION` cannot contain whitespace, newlines, paths, or arbitrary log text. Compose gives every baseline service a unique deployment ID. Deployment-changing fault commands must create a new ID and set the prior version explicitly rather than rewriting telemetry after the fact; resource and dependency faults preserve the baseline marker.

## Collector routes

`config/observability/otel-collector.yml` has three independent pipelines, each with the memory limiter and batch processor:

```text
OTLP metrics -> Collector Prometheus exporter :9464 -> Prometheus scrape
OTLP logs    -> Collector OTLP/HTTP exporter   -> Loki /otlp
OTLP traces  -> Collector OTLP/HTTP exporter   -> Tempo :4318
```

Prometheus, Loki, Tempo, and the Collector share the internal observability network; the Collector additionally joins the internal simulator network to receive OTLP. No Collector receiver is published to the host. Prometheus, Loki, and Tempo also join a separate host-ingress network solely for their loopback-bound diagnostic/query ports; they never join Gateway ingress.

## Verification boundary

Unit tests use in-memory exporters to assert inbound and outbound W3C hierarchy, server/client/dependency metric names and bounded attributes, OTLP log trace/span linkage, startup and live-transition deployment markers, payload/error-detail exclusion, invalid configuration, disabled mode, observer/exporter failure isolation, and bounded shutdown. Static tests assert all service OTLP settings and all three Collector destinations.

The 2026-10-02 Phase 1 run observed the Collector scrape target as `up`, queried `simulator_http_server_requests_total` including the injected Order 500 and Gateway 502 series, listed Loki OTLP resource labels, and returned simulator traces from Tempo search. The exact functional evidence and limitations are recorded in `docs/PHASE_1_VERIFICATION.md`; this single run is not a throughput, retention, or reliability measurement.

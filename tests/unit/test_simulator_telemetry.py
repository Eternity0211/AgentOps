"""Tests for safe simulator OpenTelemetry signals and propagation."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from agentops_incident_commander.simulator import app as simulator_app
from agentops_incident_commander.simulator import dependencies, telemetry
from agentops_incident_commander.simulator.fault_behavior import FaultBehavior
from agentops_incident_commander.simulator.models import CheckoutRequest


@pytest.fixture
def anyio_backend() -> str:
    """Run async telemetry tests on asyncio."""
    return "asyncio"


class CapturingMetricExporter(MetricExporter):
    """Keep exported SDK metric batches in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.exports: list[MetricsData] = []
        self.closed = False

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        self.exports.append(metrics_data)
        return MetricExportResult.SUCCESS

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        self.closed = True


class FailingSpanExporter(InMemorySpanExporter):
    """Simulate an unavailable Collector trace endpoint."""

    def export(self, spans: Any) -> Any:
        raise OSError("collector unavailable")


class UnusedOrderStore:
    """Satisfy Order composition while proving the fault short-circuits persistence."""

    async def ready(self, correlation_id: str) -> None:
        return None

    async def save(self, checkout: CheckoutRequest, correlation_id: str) -> bool:
        raise AssertionError("faulty request must not be persisted")

    async def close(self) -> None:
        return None


class UnusedCaller:
    """Prove a fault response occurs before either downstream call."""

    async def post(
        self, service: str, path: str, payload: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        raise AssertionError("faulty request must not call downstream services")


class UnusedRedisClient:
    """Prove forced timeout telemetry is emitted before the real client is invoked."""

    async def ping(self) -> bool:
        raise AssertionError("forced timeout must not ping Redis")

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object:
        raise AssertionError("forced timeout must not run Redis Lua")

    async def aclose(self) -> None:
        return None


def enabled_settings() -> telemetry.TelemetrySettings:
    """Return fast, valid settings for in-memory exporters."""
    return telemetry.TelemetrySettings(
        enabled=True,
        endpoint="http://collector:4318",
        timeout_seconds=1,
        export_interval_millis=300_000,
        environment="test",
    )


def in_memory_log_exporter() -> Any:
    """Construct the upstream test exporter despite its missing type metadata."""
    return InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]


def metric_points(exporter: CapturingMetricExporter) -> dict[str, list[Any]]:
    """Flatten metric names and points from captured SDK batches."""
    result: dict[str, list[Any]] = {}
    for batch in exporter.exports:
        for resource_metric in batch.resource_metrics:
            for scope_metric in resource_metric.scope_metrics:
                for metric in scope_metric.metrics:
                    result.setdefault(metric.name, []).extend(metric.data.data_points)
    return result


def test_enabled_http_telemetry_exports_safe_spans_metrics_and_logs() -> None:
    """One request emits all signals with stable route dimensions and trace correlation."""
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    logs = in_memory_log_exporter()
    observed = telemetry.SimulatorTelemetry(
        "gateway",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=logs,
    )
    app = simulator_app.create_app("gateway", telemetry=observed)

    with TestClient(app) as client:
        response = client.get(
            "/healthz?password=do-not-record",
            headers={simulator_app.CORRELATION_HEADER: "corr-telemetry"},
        )

    assert response.status_code == 200
    finished_spans = spans.get_finished_spans()
    assert len(finished_spans) == 1
    server_span = finished_spans[0]
    assert server_span.name == "GET /healthz"
    assert server_span.kind is SpanKind.SERVER
    assert server_span.attributes is not None
    assert server_span.attributes["agentops.correlation_id"] == "corr-telemetry"
    assert "password" not in str(server_span.attributes)

    points = metric_points(metrics)
    assert set(points) == {
        "simulator.http.server.requests",
        "simulator.http.server.duration",
    }
    assert points["simulator.http.server.requests"][0].attributes == {
        "method": "GET",
        "route": "/healthz",
        "status": "200",
    }
    assert metrics.closed is True

    finished_logs = logs.get_finished_logs()
    assert {item.log_record.body for item in finished_logs} == {
        "service.deployment.changed",
        "http_request",
    }
    deployment_record = next(
        item.log_record
        for item in finished_logs
        if item.log_record.body == "service.deployment.changed"
    )
    assert deployment_record.attributes is not None
    assert deployment_record.attributes["deployment.id"] == "baseline-gateway-v1"
    record = next(
        item.log_record for item in finished_logs if item.log_record.body == "http_request"
    )
    assert record.body == "http_request"
    assert record.attributes is not None
    assert record.attributes["http.route"] == "/healthz"
    assert record.attributes["agentops.correlation_id"] == "corr-telemetry"
    assert "do-not-record" not in str(record.attributes)
    assert record.trace_id == server_span.context.trace_id
    assert record.span_id == server_span.context.span_id


def test_unmatched_route_uses_bounded_telemetry_dimension() -> None:
    """Unknown request paths collapse to one label instead of causing cardinality growth."""
    spans = InMemorySpanExporter()
    observed = telemetry.SimulatorTelemetry(
        "gateway",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )

    with TestClient(simulator_app.create_app("gateway", telemetry=observed)) as client:
        response = client.get("/user-controlled-missing-path")

    assert response.status_code == 404
    assert spans.get_finished_spans()[0].name == "GET unmatched"


def test_export_failure_does_not_fail_business_request() -> None:
    """Background exporter errors never become simulator HTTP failures."""
    observed = telemetry.SimulatorTelemetry(
        "payment",
        enabled_settings(),
        span_exporter=FailingSpanExporter(),
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )

    with TestClient(simulator_app.create_app("payment", telemetry=observed)) as client:
        response = client.get("/healthz")

    assert response.status_code == 200


def test_http_500_fault_emits_error_span_and_status_metric() -> None:
    """The symptom is observable as failure signals without a root-cause label."""
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    observed = telemetry.SimulatorTelemetry(
        "order",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=in_memory_log_exporter(),
    )
    app = simulator_app.create_app(
        "order",
        caller=UnusedCaller(),
        order_store=UnusedOrderStore(),
        telemetry=observed,
        fault_behavior=FaultBehavior("http-500", "run-abcdef123456"),
    )
    checkout = {
        "order_id": "order-123",
        "items": [{"sku": "widget-1", "quantity": 2}],
        "amount_minor": 2500,
        "currency": "USD",
    }

    with TestClient(app) as client:
        response = client.post("/v1/orders", json=checkout)

    assert response.status_code == 500
    span = next(item for item in spans.get_finished_spans() if item.kind is SpanKind.SERVER)
    assert span.status.status_code is StatusCode.ERROR
    assert "http-500" not in str(span.attributes)
    points = metric_points(metrics)["simulator.http.server.requests"]
    assert points[0].attributes["status"] == "500"


def test_downstream_latency_fault_emits_three_second_payment_duration() -> None:
    """The fixed delay is visible in HTTP metrics without exposing its scenario label."""
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    observed = telemetry.SimulatorTelemetry(
        "payment",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=in_memory_log_exporter(),
    )

    app = simulator_app.create_app(
        "payment",
        telemetry=observed,
        fault_behavior=FaultBehavior("downstream-latency", "run-abcdef123456"),
    )

    with TestClient(app) as client:
        response = client.post(
            "/v1/authorizations",
            json={
                "order_id": "order-123",
                "items": [{"sku": "widget-1", "quantity": 2}],
                "amount_minor": 2500,
                "currency": "USD",
            },
        )

    assert response.status_code == 200
    duration = metric_points(metrics)["simulator.http.server.duration"][0]
    assert duration.sum >= 2900.0
    span = next(item for item in spans.get_finished_spans() if item.kind is SpanKind.SERVER)
    assert "downstream-latency" not in str(span.attributes)


def test_bad_configuration_fault_emits_503_without_cause_label() -> None:
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    observed = telemetry.SimulatorTelemetry(
        "payment",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=in_memory_log_exporter(),
    )
    app = simulator_app.create_app(
        "payment",
        telemetry=observed,
        fault_behavior=FaultBehavior("bad-configuration", "run-abcdef123456"),
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/authorizations",
            json={
                "order_id": "order-123",
                "items": [{"sku": "widget-1", "quantity": 2}],
                "amount_minor": 2500,
                "currency": "USD",
            },
        )
    assert response.status_code == 503
    span = next(item for item in spans.get_finished_spans() if item.kind is SpanKind.SERVER)
    assert span.status.status_code is StatusCode.ERROR
    assert "bad-configuration" not in str(span.attributes)
    assert metric_points(metrics)["simulator.http.server.requests"][0].attributes["status"] == "503"


@pytest.mark.anyio
async def test_http_client_span_propagates_w3c_context() -> None:
    """Internal HTTP carries traceparent and creates a bounded client span."""
    spans = InMemorySpanExporter()
    observed = telemetry.SimulatorTelemetry(
        "gateway",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers[simulator_app.CORRELATION_HEADER] == "corr-client"
        assert request.headers["traceparent"].startswith("00-")
        return httpx.Response(200, json={"status": "ok"})

    caller = simulator_app.HttpxServiceCaller(
        {"order": "http://order:8000"},
        transport=httpx.MockTransport(handler),
        telemetry=observed,
    )

    with observed.server_span("POST", "corr-client"):
        result = await caller.post("order", "/v1/orders", {"safe": True}, "corr-client")
    await observed.shutdown()

    assert result == {"status": "ok"}
    client_span = next(span for span in spans.get_finished_spans() if span.kind is SpanKind.CLIENT)
    assert client_span.name == "POST order"
    assert client_span.attributes is not None
    assert client_span.attributes["http.route"] == "/v1/orders"
    assert "safe" not in str(client_span.attributes)


@pytest.mark.anyio
async def test_dependency_observation_creates_error_span() -> None:
    """Dependency failures mark a span as error without adding exception text attributes."""
    spans = InMemorySpanExporter()
    observed = telemetry.SimulatorTelemetry(
        "order",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )

    async def fail() -> None:
        raise dependencies.DependencyUnavailable("contains-sensitive-detail")

    with pytest.raises(dependencies.DependencyUnavailable):
        await dependencies._observe("postgres", "ready", "corr-db", fail(), observed.tracer)
    await observed.shutdown()

    span = spans.get_finished_spans()[0]
    assert span.name == "postgres.ready"
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["db.system.name"] == "postgres"
    assert "contains-sensitive-detail" not in str(span.attributes)


@pytest.mark.anyio
async def test_redis_timeout_marks_dependency_span_without_ground_truth_label() -> None:
    """The dependency trace exposes a timeout symptom, not the injected scenario identity."""
    spans = InMemorySpanExporter()
    observed = telemetry.SimulatorTelemetry(
        "inventory",
        enabled_settings(),
        span_exporter=spans,
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )
    store = dependencies.RedisInventoryStore(
        {"DEPENDENCY_TIMEOUT_SECONDS": "0.001"},
        client=UnusedRedisClient(),
        tracer=observed.tracer,
        force_timeout=True,
    )

    with pytest.raises(dependencies.DependencyUnavailable):
        await store.ready("corr-cache-deadline")
    await observed.shutdown()

    span = spans.get_finished_spans()[0]
    assert span.name == "redis.ready"
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes is not None
    assert span.attributes["error.type"] == "timeout"
    assert "redis-timeout" not in str(span.attributes)
    assert "run-" not in str(span.attributes)


@pytest.mark.parametrize(
    "environment",
    [
        {"OTEL_EXPORT_TIMEOUT_SECONDS": "0"},
        {"OTEL_EXPORT_TIMEOUT_SECONDS": "31"},
        {"OTEL_METRIC_EXPORT_INTERVAL_MILLIS": "999"},
        {"OTEL_METRIC_EXPORT_INTERVAL_MILLIS": "300001"},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "ftp://collector"},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://user:pass@collector:4318"},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318?token=secret"},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318/#fragment"},
    ],
)
def test_settings_reject_unbounded_or_sensitive_configuration(
    environment: dict[str, str],
) -> None:
    """Invalid deadlines, intervals, protocols, and embedded secrets fail validation."""
    with pytest.raises(ValueError):
        telemetry.TelemetrySettings.from_environment(environment)


def test_settings_parse_enabled_defaults_and_trim_endpoint() -> None:
    """Environment settings normalize enablement and a trailing endpoint slash."""
    settings = telemetry.TelemetrySettings.from_environment(
        {
            "OTEL_SDK_ENABLED": " YES ",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector:4318/",
            "OTEL_EXPORT_TIMEOUT_SECONDS": "3",
            "OTEL_METRIC_EXPORT_INTERVAL_MILLIS": "2000",
            "DEPLOYMENT_ENVIRONMENT": "ci",
        }
    )

    assert settings == telemetry.TelemetrySettings(
        enabled=True,
        endpoint="https://collector:4318",
        timeout_seconds=3.0,
        export_interval_millis=2000,
        environment="ci",
    )


@pytest.mark.anyio
async def test_disabled_telemetry_is_noop() -> None:
    """The default disabled mode records nothing and shuts down immediately."""
    observed = telemetry.SimulatorTelemetry(
        "payment",
        telemetry.TelemetrySettings.from_environment({}),
    )

    with observed.server_span("GET", "corr-disabled") as span:
        observed.complete_request(
            span,
            method="GET",
            route="/healthz",
            status_code=503,
            started_at=0,
            correlation_id="corr-disabled",
        )
    await observed.shutdown()

    assert observed.settings.enabled is False


def test_factory_falls_back_when_configuration_is_invalid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Telemetry setup errors do not prevent a simulator service from starting."""
    caplog.set_level(logging.WARNING, logger="agentops.simulator.telemetry")
    monkeypatch.setattr(
        telemetry.TelemetrySettings,
        "from_environment",
        classmethod(lambda cls, environment=None: (_ for _ in ()).throw(ValueError("bad"))),
    )

    observed = telemetry.create_telemetry("gateway", {})

    assert observed.settings.enabled is False
    assert "telemetry_initialization_failed service=gateway" in caplog.text
    assert "bad" not in caplog.text


@pytest.mark.anyio
async def test_default_exporters_receive_signal_specific_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A base OTLP/HTTP endpoint expands into all three standard signal paths."""
    captured: dict[str, str] = {}
    span_exporter = InMemorySpanExporter()
    metric_exporter = CapturingMetricExporter()
    log_exporter = in_memory_log_exporter()

    def trace_exporter(**kwargs: Any) -> InMemorySpanExporter:
        captured["traces"] = str(kwargs["endpoint"])
        return span_exporter

    def metrics_exporter(**kwargs: Any) -> CapturingMetricExporter:
        captured["metrics"] = str(kwargs["endpoint"])
        return metric_exporter

    def logs_exporter(**kwargs: Any) -> Any:
        captured["logs"] = str(kwargs["endpoint"])
        return log_exporter

    monkeypatch.setattr(telemetry, "OTLPSpanExporter", trace_exporter)
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", metrics_exporter)
    monkeypatch.setattr(telemetry, "OTLPLogExporter", logs_exporter)

    observed = telemetry.SimulatorTelemetry("gateway", enabled_settings())
    await observed.shutdown()

    assert captured == {
        "traces": "http://collector:4318/v1/traces",
        "metrics": "http://collector:4318/v1/metrics",
        "logs": "http://collector:4318/v1/logs",
    }


@pytest.mark.anyio
async def test_shutdown_timeout_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A hung exporter cannot indefinitely block application shutdown."""
    observed = telemetry.SimulatorTelemetry(
        "gateway",
        enabled_settings(),
        span_exporter=InMemorySpanExporter(),
        metric_exporter=CapturingMetricExporter(),
        log_exporter=in_memory_log_exporter(),
    )
    caplog.set_level(logging.WARNING, logger="agentops.simulator.telemetry")

    async def timeout(awaitable: Any, timeout: float) -> None:
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("agentops_incident_commander.simulator.telemetry.asyncio.wait_for", timeout)

    await observed.shutdown()

    assert "telemetry_shutdown_timeout service=agentops-simulator-gateway" in caplog.text

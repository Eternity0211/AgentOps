"""Tests for typed, content-free control-plane OpenTelemetry signals."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    safely_record,
)
from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelMeteringUnavailableReason,
    ModelTokenUsage,
    OpaqueIdentifier,
    SemanticVersion,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import (
    ControlPlaneTelemetrySettings,
    OpenTelemetryControlPlaneObserver,
    control_plane_telemetry,
    create_control_plane_observer,
)

NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)


class CapturingMetricExporter(MetricExporter):
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


class RaisingObserver:
    def record(self, observation: ControlPlaneObservation) -> None:
        raise RuntimeError("secret payload from exporter")


def settings(*, enabled: bool = True) -> ControlPlaneTelemetrySettings:
    return ControlPlaneTelemetrySettings(
        enabled=enabled,
        endpoint="http://collector:4318",
        timeout_seconds=1,
        export_interval_millis=300_000,
        environment="test",
        service_name="agentops-worker",
        service_version="0.1.0",
    )


def metering() -> ModelMetering:
    return ModelMetering(
        ModelTokenUsage(100, 20, 10, 5, 120),
        ModelCost(
            12_345,
            "USD",
            ModelCostSource.RATE_CARD_CALCULATED,
            SemanticVersion("1.0.0"),
        ),
    )


def observation(**overrides: object) -> ControlPlaneObservation:
    values: dict[str, object] = {
        "component": ControlPlaneComponent.DIAGNOSIS_GRAPH,
        "operation": ControlPlaneOperation.GRAPH_PLAN,
        "outcome": ControlPlaneOutcome.SUCCEEDED,
        "occurred_at": NOW,
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "correlation_id": CorrelationId("correlation-1"),
        "causation_id": CausationId("cause-1"),
        "operation_id": OpaqueIdentifier("operation-1"),
        "workflow_run_id": WorkflowRunId("workflow-1"),
        "duration_ms": 25,
        "route": "INVESTIGATE",
        "subject_name": "plan",
        "subject_version": "1.0.0",
    }
    values.update(overrides)
    return ControlPlaneObservation(**values)  # type: ignore[arg-type]


def metric_points(exporter: CapturingMetricExporter) -> dict[str, list[Any]]:
    points: dict[str, list[Any]] = {}
    for batch in exporter.exports:
        for resource_metric in batch.resource_metrics:
            for scope_metric in resource_metric.scope_metrics:
                for metric in scope_metric.metrics:
                    points.setdefault(metric.name, []).extend(metric.data.data_points)
    return points


@pytest.mark.anyio
async def test_seeded_secret_never_crosses_control_plane_signal_boundaries() -> None:
    secret = "sk-" + "supersecret123456"
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    logs = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    observer = OpenTelemetryControlPlaneObserver(
        settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=logs,
    )
    observer.record(
        observation(
            component=ControlPlaneComponent.MODEL,
            operation=ControlPlaneOperation.MODEL_CALL,
            subject_name=f"provider-{secret}",
            subject_version="model-v1",
            model_metering=metering(),
        )
    )
    await observer.shutdown()

    assert secret not in str(spans.get_finished_spans())
    assert secret not in str(logs.get_finished_logs())
    assert secret not in str(metric_points(metrics))
    span = spans.get_finished_spans()[0]
    assert span.attributes is not None
    assert span.attributes["agentops.correlation_id"] == "correlation-1"
    assert "[REDACTED]" in str(span.attributes["agentops.subject.name"])


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"component": "MODEL"}, "component"),
        ({"operation": "MODEL_CALL"}, "component"),
        ({"outcome": "FAILED"}, "outcome"),
        ({"tenant_id": cast(TenantId, object())}, "identity"),
        ({"workflow_run_id": cast(WorkflowRunId, object())}, "workflow"),
        ({"duration_ms": True}, "duration"),
        ({"duration_ms": -1}, "duration"),
        ({"duration_ms": 86_400_001}, "duration"),
        ({"outcome": ControlPlaneOutcome.STARTED, "duration_ms": 1}, "started"),
        ({"duration_ms": None}, "terminal"),
        ({"attempt": None, "max_attempts": 2}, "maximum"),
        ({"attempt": 0}, "attempt"),
        ({"attempt": 129}, "attempt"),
        ({"attempt": 2, "max_attempts": 1}, "attempt"),
        ({"attempt": 1, "max_attempts": 129}, "attempt"),
        ({"route": "bad route"}, "route"),
        ({"result_code": "bad/result"}, "result code"),
        ({"model_metering": cast(ModelMetering, object())}, "metering"),
        ({"model_metering": metering()}, "only"),
        ({"schema_version": "2.0"}, "schema"),
    ],
)
def test_observation_rejects_untyped_unbounded_or_content_like_fields(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        observation(**overrides)


def test_started_observation_and_noop_are_valid() -> None:
    value = observation(
        outcome=ControlPlaneOutcome.STARTED,
        duration_ms=None,
        attempt=2,
        max_attempts=None,
    )
    NOOP_CONTROL_PLANE_OBSERVER.record(value)
    assert value.occurred_at.tzinfo is UTC
    assert not hasattr(value, "payload")
    assert not hasattr(value, "prompt")
    assert not hasattr(value, "response")


def test_safe_record_hides_exporter_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="agentops.control_plane.observability")
    safely_record(RaisingObserver(), observation())
    assert "control_plane_observation_failed" in caplog.text
    assert "secret payload" not in caplog.text


@pytest.mark.anyio
async def test_adapter_exports_linked_spans_logs_and_bounded_metrics() -> None:
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    logs = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    observer = OpenTelemetryControlPlaneObserver(
        settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=logs,
    )
    observer.record(
        observation(
            component=ControlPlaneComponent.MODEL,
            operation=ControlPlaneOperation.MODEL_CALL,
            outcome=ControlPlaneOutcome.STARTED,
            duration_ms=None,
            attempt=1,
            route="diagnosis.hypothesis",
            subject_name="mock",
            subject_version="model-v1",
        )
    )
    observer.record(
        observation(
            component=ControlPlaneComponent.MODEL,
            operation=ControlPlaneOperation.MODEL_CALL,
            outcome=ControlPlaneOutcome.SUCCEEDED,
            attempt=1,
            route="diagnosis.hypothesis",
            subject_name="mock",
            subject_version="model-v1",
            model_metering=metering(),
        )
    )
    observer.record(
        observation(
            component=ControlPlaneComponent.TOOL,
            operation=ControlPlaneOperation.TOOL_CALL,
            outcome=ControlPlaneOutcome.RETRYING,
            attempt=1,
            max_attempts=2,
            route=None,
            result_code="TOOL_TIMEOUT",
            subject_name="query_logs",
            subject_version="1.0.0",
        )
    )
    observer.record(
        observation(
            component=ControlPlaneComponent.TOOL,
            operation=ControlPlaneOperation.TOOL_CALL,
            outcome=ControlPlaneOutcome.REJECTED,
            attempt=None,
            max_attempts=None,
            route=None,
            result_code="REQUEST_REJECTED",
            subject_name="query_logs",
            subject_version="1.0.0",
        )
    )
    observer.record(observation())
    await observer.shutdown()

    finished_spans = spans.get_finished_spans()
    assert len(finished_spans) == 5
    assert finished_spans[1].attributes is not None
    assert finished_spans[1].attributes["gen_ai.usage.total_tokens"] == 120
    assert "payload" not in str(finished_spans[1].attributes)
    finished_logs = logs.get_finished_logs()
    assert len(finished_logs) == 5
    assert all(item.log_record.body == "control_plane.operation" for item in finished_logs)
    assert finished_logs[1].log_record.trace_id == finished_spans[1].context.trace_id
    points = metric_points(metrics)
    assert {
        "agentops.control_plane.operations",
        "agentops.control_plane.duration",
        "agentops.model.calls",
        "agentops.model.tokens",
        "agentops.model.cost",
        "agentops.tool.attempts",
        "agentops.tool.retries",
    } <= set(points)
    assert metrics.closed is True


@pytest.mark.anyio
async def test_one_process_observer_preserves_a_correlated_end_to_end_signal_set() -> None:
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    observer = OpenTelemetryControlPlaneObserver(
        settings(),
        span_exporter=spans,
        metric_exporter=CapturingMetricExporter(),
        log_exporter=logs,
    )
    correlation = CorrelationId("correlation-process-e2e")
    signals = (
        (
            ControlPlaneComponent.DIAGNOSIS_GRAPH,
            ControlPlaneOperation.GRAPH_PLAN,
            ControlPlaneOutcome.SUCCEEDED,
            "SUCCESS",
        ),
        (
            ControlPlaneComponent.RECOVERY_EXECUTION,
            ControlPlaneOperation.RECOVERY_EXECUTE,
            ControlPlaneOutcome.REFUSED,
            "REFUSAL",
        ),
        (
            ControlPlaneComponent.TOOL,
            ControlPlaneOperation.TOOL_CALL,
            ControlPlaneOutcome.RETRYING,
            "RETRY",
        ),
        (
            ControlPlaneComponent.APPROVAL,
            ControlPlaneOperation.APPROVAL_RESUME,
            ControlPlaneOutcome.PAUSED,
            "PAUSE",
        ),
        (
            ControlPlaneComponent.APPROVAL,
            ControlPlaneOperation.APPROVAL_RESUME,
            ControlPlaneOutcome.RESUMED,
            "RESUME",
        ),
        (
            ControlPlaneComponent.VERIFICATION,
            ControlPlaneOperation.HEALTH_VERIFY,
            ControlPlaneOutcome.FAILED,
            "FAILURE",
        ),
    )
    for index, (component, operation, outcome, result_code) in enumerate(signals, 1):
        observer.record(
            observation(
                component=component,
                operation=operation,
                outcome=outcome,
                correlation_id=correlation,
                causation_id=CausationId(f"cause-process-{index}"),
                operation_id=OpaqueIdentifier(f"operation-process-{index}"),
                attempt=1 if outcome is ControlPlaneOutcome.RETRYING else None,
                max_attempts=2 if outcome is ControlPlaneOutcome.RETRYING else None,
                result_code=result_code,
            )
        )
    await observer.shutdown()

    finished = spans.get_finished_spans()
    assert len(finished) == len(signals)
    assert {
        item.attributes["agentops.correlation_id"]
        for item in finished
        if item.attributes is not None
    } == {correlation.value}
    assert {
        item.attributes["agentops.outcome"] for item in finished if item.attributes is not None
    } == {signal[2].value for signal in signals}
    assert len(logs.get_finished_logs()) == len(signals)


@pytest.mark.anyio
async def test_error_and_unavailable_metering_have_safe_signals() -> None:
    spans = InMemorySpanExporter()
    metrics = CapturingMetricExporter()
    logs = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    observer = OpenTelemetryControlPlaneObserver(
        settings(),
        span_exporter=spans,
        metric_exporter=metrics,
        log_exporter=logs,
    )
    unavailable = ModelMetering(
        None,
        None,
        ModelMeteringUnavailableReason.CALL_FAILED_BEFORE_METERING,
    )
    failed = observation(
        component=ControlPlaneComponent.MODEL,
        operation=ControlPlaneOperation.MODEL_CALL,
        outcome=ControlPlaneOutcome.FAILED,
        result_code="provider_error",
        route="diagnosis.plan",
        subject_name="mock",
        subject_version="model-v1",
        model_metering=unavailable,
    )
    observer.record(failed)
    await observer.shutdown()

    assert spans.get_finished_spans()[0].status.status_code is StatusCode.ERROR
    assert "agentops.model.errors" in metric_points(metrics)
    attributes = logs.get_finished_logs()[0].log_record.attributes
    assert attributes is not None
    assert attributes["agentops.model.metering_unavailable"] == ("CALL_FAILED_BEFORE_METERING")


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
        {"DEPLOYMENT_ENVIRONMENT": "bad environment"},
        {"AGENTOPS_SERVICE_VERSION": "bad/version"},
    ],
)
def test_settings_reject_unsafe_or_unbounded_values(environment: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        ControlPlaneTelemetrySettings.from_environment(environment)


def test_settings_parse_enabled_values_and_service_identity() -> None:
    value = ControlPlaneTelemetrySettings.from_environment(
        {
            "OTEL_SDK_ENABLED": " yes ",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "https://collector:4318/",
            "OTEL_EXPORT_TIMEOUT_SECONDS": "3",
            "OTEL_METRIC_EXPORT_INTERVAL_MILLIS": "2000",
            "DEPLOYMENT_ENVIRONMENT": "ci",
            "AGENTOPS_SERVICE_VERSION": "2.0.0",
        },
        service_name="agentops-api",
    )
    assert value == ControlPlaneTelemetrySettings(
        True,
        "https://collector:4318",
        3,
        2000,
        "ci",
        "agentops-api",
        "2.0.0",
    )


def test_settings_reject_invalid_explicit_service_name() -> None:
    with pytest.raises(ValueError, match="service name"):
        ControlPlaneTelemetrySettings.from_environment({}, service_name="bad service")


@pytest.mark.anyio
async def test_default_exporters_use_signal_specific_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}
    span_exporter = InMemorySpanExporter()
    metric_exporter = CapturingMetricExporter()
    log_exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]

    def traces(**kwargs: Any) -> InMemorySpanExporter:
        captured["traces"] = str(kwargs["endpoint"])
        return span_exporter

    def metrics_exporter(**kwargs: Any) -> CapturingMetricExporter:
        captured["metrics"] = str(kwargs["endpoint"])
        return metric_exporter

    def logs_exporter(**kwargs: Any) -> Any:
        captured["logs"] = str(kwargs["endpoint"])
        return log_exporter

    monkeypatch.setattr(control_plane_telemetry, "OTLPSpanExporter", traces)
    monkeypatch.setattr(control_plane_telemetry, "OTLPMetricExporter", metrics_exporter)
    monkeypatch.setattr(control_plane_telemetry, "OTLPLogExporter", logs_exporter)

    observer = OpenTelemetryControlPlaneObserver(settings())
    await observer.shutdown()

    assert captured == {
        "traces": "http://collector:4318/v1/traces",
        "metrics": "http://collector:4318/v1/metrics",
        "logs": "http://collector:4318/v1/logs",
    }


@pytest.mark.anyio
async def test_disabled_observer_is_noop() -> None:
    observer = OpenTelemetryControlPlaneObserver(settings(enabled=False))
    observer.record(observation())
    await observer.shutdown()
    assert observer.settings.enabled is False


def test_factory_builds_valid_disabled_observer() -> None:
    observer = create_control_plane_observer(
        service_name="agentops-worker",
        environment={"OTEL_SDK_ENABLED": "false"},
    )
    assert observer.settings.enabled is False


def test_factory_falls_back_without_exposing_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="agentops.control_plane.telemetry")
    monkeypatch.setattr(
        ControlPlaneTelemetrySettings,
        "from_environment",
        classmethod(
            lambda cls, environment=None, *, service_name="agentops-worker": (_ for _ in ()).throw(
                ValueError("secret configuration detail")
            )
        ),
    )
    observer = create_control_plane_observer(service_name="agentops-worker", environment={})
    assert observer.settings.enabled is False
    assert "control_plane_telemetry_initialization_failed" in caplog.text
    assert "secret configuration detail" not in caplog.text


@pytest.mark.anyio
async def test_shutdown_timeout_is_nonfatal(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    observer = OpenTelemetryControlPlaneObserver(
        settings(),
        span_exporter=InMemorySpanExporter(),
        metric_exporter=CapturingMetricExporter(),
        log_exporter=InMemoryLogRecordExporter(),  # type: ignore[no-untyped-call]
    )
    caplog.set_level(logging.WARNING, logger="agentops.control_plane.telemetry")

    async def timeout(awaitable: Any, timeout: float) -> None:
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(
        "agentops_incident_commander.infrastructure.control_plane_telemetry.asyncio.wait_for",
        timeout,
    )
    await observer.shutdown()
    assert "control_plane_telemetry_shutdown_timeout" in caplog.text

"""Bounded OpenTelemetry adapter for control-plane operation observations."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from opentelemetry import metrics, trace
from opentelemetry._logs import Logger
from opentelemetry._logs.severity import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import (
    DEPLOYMENT_ENVIRONMENT,
    SERVICE_NAME,
    SERVICE_VERSION,
    Resource,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from agentops_incident_commander.application.control_plane_observability import (
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneOutcome,
)

logger = logging.getLogger("agentops.control_plane.telemetry")
_RESOURCE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_ERROR_OUTCOMES = frozenset(
    {
        ControlPlaneOutcome.FAILED,
        ControlPlaneOutcome.TIMED_OUT,
        ControlPlaneOutcome.REJECTED,
        ControlPlaneOutcome.REFUSED,
        ControlPlaneOutcome.BLOCKED,
    }
)


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ControlPlaneTelemetrySettings:
    enabled: bool
    endpoint: str
    timeout_seconds: float
    export_interval_millis: int
    environment: str
    service_name: str
    service_version: str

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        service_name: str = "agentops-worker",
    ) -> ControlPlaneTelemetrySettings:
        source = os.environ if environment is None else environment
        timeout = float(source.get("OTEL_EXPORT_TIMEOUT_SECONDS", "2"))
        interval = int(source.get("OTEL_METRIC_EXPORT_INTERVAL_MILLIS", "5000"))
        endpoint = source.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
        parsed = urlsplit(endpoint)
        if timeout <= 0 or timeout > 30:
            raise ValueError("OTEL export timeout must be in (0, 30]")
        if interval < 1000 or interval > 300_000:
            raise ValueError("OTEL metric export interval must be in [1000, 300000]")
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OTEL endpoint must be a credential-free HTTP(S) URL")
        deployment_environment = source.get("DEPLOYMENT_ENVIRONMENT", "local")
        service_version = source.get("AGENTOPS_SERVICE_VERSION", "0.1.0")
        for value, field_name in (
            (deployment_environment, "deployment environment"),
            (service_name, "service name"),
            (service_version, "service version"),
        ):
            if _RESOURCE_VALUE.fullmatch(value) is None:
                raise ValueError(f"invalid {field_name}")
        return cls(
            enabled=_enabled(source.get("OTEL_SDK_ENABLED", "false")),
            endpoint=endpoint.rstrip("/"),
            timeout_seconds=timeout,
            export_interval_millis=interval,
            environment=deployment_environment,
            service_name=service_name,
            service_version=service_version,
        )


class OpenTelemetryControlPlaneObserver:
    """Export content-free operation records as linked spans, metrics, and logs."""

    def __init__(
        self,
        settings: ControlPlaneTelemetrySettings,
        *,
        span_exporter: Any | None = None,
        metric_exporter: Any | None = None,
        log_exporter: Any | None = None,
    ) -> None:
        self.settings = settings
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None
        self._otel_logger: Logger | None = None
        if not settings.enabled:
            self.tracer = trace.NoOpTracerProvider().get_tracer(__name__)
            self._create_instruments(metrics.NoOpMeterProvider().get_meter(__name__))
            return

        resource = Resource.create(
            {
                SERVICE_NAME: settings.service_name,
                SERVICE_VERSION: settings.service_version,
                DEPLOYMENT_ENVIRONMENT: settings.environment,
            }
        )
        timeout = settings.timeout_seconds
        span_exporter = span_exporter or OTLPSpanExporter(
            endpoint=f"{settings.endpoint}/v1/traces", timeout=timeout
        )
        metric_exporter = metric_exporter or OTLPMetricExporter(
            endpoint=f"{settings.endpoint}/v1/metrics", timeout=timeout
        )
        log_exporter = log_exporter or OTLPLogExporter(
            endpoint=f"{settings.endpoint}/v1/logs", timeout=timeout
        )
        tracer_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                span_exporter,
                max_queue_size=1024,
                max_export_batch_size=256,
                schedule_delay_millis=1000,
                export_timeout_millis=timeout * 1000,
            )
        )
        metric_reader = PeriodicExportingMetricReader(
            metric_exporter,
            export_interval_millis=settings.export_interval_millis,
            export_timeout_millis=timeout * 1000,
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        logger_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                log_exporter,
                max_queue_size=1024,
                max_export_batch_size=256,
                schedule_delay_millis=1000,
                export_timeout_millis=timeout * 1000,
            )
        )
        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._logger_provider = logger_provider
        self.tracer = tracer_provider.get_tracer(__name__, "1.0.0")
        self._create_instruments(meter_provider.get_meter(__name__, "1.0.0"))
        self._otel_logger = logger_provider.get_logger(__name__, "1.0.0")

    def _create_instruments(self, meter: Any) -> None:
        self._operations = meter.create_counter(
            "agentops.control_plane.operations",
            description="Observed control-plane lifecycle events",
        )
        self._duration = meter.create_histogram(
            "agentops.control_plane.duration",
            unit="ms",
            description="Terminal control-plane operation duration",
        )
        self._model_calls = meter.create_counter("agentops.model.calls")
        self._model_errors = meter.create_counter("agentops.model.errors")
        self._model_tokens = meter.create_counter("agentops.model.tokens", unit="{token}")
        self._model_cost = meter.create_counter("agentops.model.cost", unit="{nanounit}")
        self._tool_attempts = meter.create_counter("agentops.tool.attempts")
        self._tool_retries = meter.create_counter("agentops.tool.retries")

    def record(self, observation: ControlPlaneObservation) -> None:
        metric_attributes = {
            "component": observation.component.value,
            "operation": observation.operation.value,
            "outcome": observation.outcome.value,
        }
        if observation.route is not None:
            metric_attributes["route"] = observation.route
        self._operations.add(1, metric_attributes)
        if observation.duration_ms is not None:
            self._duration.record(observation.duration_ms, metric_attributes)

        attributes = self._span_and_log_attributes(observation)
        end_ns = int(observation.occurred_at.timestamp() * 1_000_000_000)
        duration_ns = (observation.duration_ms or 0) * 1_000_000
        span = self.tracer.start_span(
            f"{observation.component.value.lower()}.{observation.operation.value.lower()}",
            start_time=end_ns - duration_ns,
            attributes=attributes,
        )
        if observation.outcome in _ERROR_OUTCOMES:
            span.set_status(Status(StatusCode.ERROR))
        with trace.use_span(span, end_on_exit=False):
            self._emit_log(observation, attributes)
        span.end(end_time=end_ns)
        self._record_model_metrics(observation)
        self._record_tool_metrics(observation)

    def _span_and_log_attributes(
        self, observation: ControlPlaneObservation
    ) -> dict[str, str | int]:
        attributes: dict[str, str | int] = {
            "agentops.schema.version": observation.schema_version,
            "agentops.component": observation.component.value,
            "agentops.operation": observation.operation.value,
            "agentops.outcome": observation.outcome.value,
            "agentops.tenant_id": observation.tenant_id.value,
            "agentops.incident_id": observation.incident_id.value,
            "agentops.correlation_id": observation.correlation_id.value,
            "agentops.causation_id": observation.causation_id.value,
            "agentops.operation_id": observation.operation_id.value,
        }
        optional: tuple[tuple[str, str | int | None], ...] = (
            (
                "agentops.workflow_run_id",
                observation.workflow_run_id.value if observation.workflow_run_id else None,
            ),
            ("agentops.duration_ms", observation.duration_ms),
            ("agentops.attempt", observation.attempt),
            ("agentops.max_attempts", observation.max_attempts),
            ("agentops.route", observation.route),
            ("agentops.result_code", observation.result_code),
            ("agentops.subject.name", observation.subject_name),
            ("agentops.subject.version", observation.subject_version),
        )
        attributes.update({key: value for key, value in optional if value is not None})
        metering = observation.model_metering
        if metering is not None:
            if metering.token_usage is not None:
                attributes["gen_ai.usage.input_tokens"] = metering.token_usage.input_tokens
                attributes["gen_ai.usage.output_tokens"] = metering.token_usage.output_tokens
                attributes["gen_ai.usage.cached_input_tokens"] = (
                    metering.token_usage.cached_input_tokens
                )
                attributes["gen_ai.usage.reasoning_tokens"] = metering.token_usage.reasoning_tokens
                attributes["gen_ai.usage.total_tokens"] = metering.token_usage.total_tokens
            if metering.cost is not None:
                attributes["agentops.model.cost_nanounits"] = metering.cost.amount_nanounits
                attributes["agentops.model.cost_currency"] = metering.cost.currency
                attributes["agentops.model.cost_source"] = metering.cost.source.value
                attributes["agentops.model.rate_card_version"] = (
                    metering.cost.rate_card_version.value
                )
            if metering.unavailable_reason is not None:
                attributes["agentops.model.metering_unavailable"] = (
                    metering.unavailable_reason.value
                )
        return attributes

    def _emit_log(
        self,
        observation: ControlPlaneObservation,
        attributes: Mapping[str, str | int],
    ) -> None:
        if self._otel_logger is None:
            return
        severity = (
            SeverityNumber.ERROR if observation.outcome in _ERROR_OUTCOMES else SeverityNumber.INFO
        )
        self._otel_logger.emit(
            severity_number=severity,
            severity_text=severity.name,
            body="control_plane.operation",
            attributes=dict(attributes),
        )

    def _record_model_metrics(self, observation: ControlPlaneObservation) -> None:
        if observation.component is not ControlPlaneComponent.MODEL:
            return
        dimensions = {
            "provider": observation.subject_name or "unknown",
            "model": observation.subject_version or "unknown",
            "outcome": observation.outcome.value,
        }
        if observation.outcome is ControlPlaneOutcome.STARTED:
            self._model_calls.add(1, dimensions)
            return
        if observation.outcome in _ERROR_OUTCOMES:
            self._model_errors.add(1, dimensions)
        metering = observation.model_metering
        if metering is None or metering.token_usage is None or metering.cost is None:
            return
        usage = metering.token_usage
        for token_type, value in (
            ("input", usage.input_tokens),
            ("output", usage.output_tokens),
            ("cached_input", usage.cached_input_tokens),
            ("reasoning", usage.reasoning_tokens),
            ("total", usage.total_tokens),
        ):
            self._model_tokens.add(value, {**dimensions, "token_type": token_type})
        self._model_cost.add(
            metering.cost.amount_nanounits,
            {
                **dimensions,
                "currency": metering.cost.currency,
                "source": metering.cost.source.value,
            },
        )

    def _record_tool_metrics(self, observation: ControlPlaneObservation) -> None:
        if observation.component is not ControlPlaneComponent.TOOL:
            return
        dimensions = {
            "tool": observation.subject_name or "unknown",
            "version": observation.subject_version or "unknown",
            "outcome": observation.outcome.value,
        }
        if observation.attempt is not None:
            self._tool_attempts.add(1, dimensions)
        if observation.outcome is ControlPlaneOutcome.RETRYING:
            self._tool_retries.add(1, dimensions)

    async def shutdown(self) -> None:
        if self._tracer_provider is None:
            return
        tracer_provider = self._tracer_provider

        def close_providers() -> None:
            assert self._meter_provider is not None
            assert self._logger_provider is not None
            tracer_provider.shutdown()
            self._meter_provider.shutdown(timeout_millis=self.settings.timeout_seconds * 1000)
            self._logger_provider.shutdown()

        try:
            await asyncio.wait_for(
                asyncio.to_thread(close_providers),
                timeout=(self.settings.timeout_seconds * 3) + 1,
            )
        except TimeoutError:
            logger.warning("control_plane_telemetry_shutdown_timeout")


def create_control_plane_observer(
    *,
    service_name: str,
    environment: Mapping[str, str] | None = None,
) -> OpenTelemetryControlPlaneObserver:
    try:
        settings = ControlPlaneTelemetrySettings.from_environment(
            environment, service_name=service_name
        )
        return OpenTelemetryControlPlaneObserver(settings)
    except Exception:
        logger.warning("control_plane_telemetry_initialization_failed service=%s", service_name)
        return OpenTelemetryControlPlaneObserver(
            ControlPlaneTelemetrySettings(
                enabled=False,
                endpoint="http://otel-collector:4318",
                timeout_seconds=2,
                export_interval_millis=5000,
                environment="local",
                service_name=service_name,
                service_version="0.1.0",
            )
        )

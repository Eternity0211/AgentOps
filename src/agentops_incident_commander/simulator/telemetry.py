"""Explicit, bounded OpenTelemetry setup for one simulator service process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
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
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

logger = logging.getLogger("agentops.simulator.telemetry")
RESOURCE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
TRACE_CONTEXT_PROPAGATOR = TraceContextTextMapPropagator()


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class TelemetrySettings:
    """Validated, non-secret telemetry settings for one service."""

    enabled: bool
    endpoint: str
    timeout_seconds: float
    export_interval_millis: int
    environment: str
    service_version: str = "1.0.0"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> TelemetrySettings:
        source = os.environ if environment is None else environment
        timeout = float(source.get("OTEL_EXPORT_TIMEOUT_SECONDS", "2"))
        interval = int(source.get("OTEL_METRIC_EXPORT_INTERVAL_MILLIS", "5000"))
        if timeout <= 0 or timeout > 30:
            raise ValueError("OTEL export timeout must be in (0, 30]")
        if interval < 1000 or interval > 300_000:
            raise ValueError("OTEL metric export interval must be in [1000, 300000]")
        endpoint = source.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318")
        parsed_endpoint = urlsplit(endpoint)
        if (
            parsed_endpoint.scheme not in {"http", "https"}
            or parsed_endpoint.hostname is None
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise ValueError("OTEL endpoint must be a credential-free HTTP(S) URL")
        deployment_environment = source.get("DEPLOYMENT_ENVIRONMENT", "local")
        service_version = source.get("SERVICE_VERSION", "1.0.0")
        if RESOURCE_VALUE_PATTERN.fullmatch(deployment_environment) is None:
            raise ValueError("invalid deployment environment")
        if RESOURCE_VALUE_PATTERN.fullmatch(service_version) is None:
            raise ValueError("invalid service version")
        return cls(
            enabled=_enabled(source.get("OTEL_SDK_ENABLED", "false")),
            endpoint=endpoint.rstrip("/"),
            timeout_seconds=timeout,
            export_interval_millis=interval,
            environment=deployment_environment,
            service_version=service_version,
        )


class SimulatorTelemetry:
    """Own service-scoped providers without installing mutable global providers."""

    def __init__(
        self,
        service: str,
        settings: TelemetrySettings,
        *,
        span_exporter: Any | None = None,
        metric_exporter: Any | None = None,
        log_exporter: Any | None = None,
    ) -> None:
        self.service_name = f"agentops-simulator-{service}"
        self.settings = settings
        self._tracer_provider: TracerProvider | None = None
        self._meter_provider: MeterProvider | None = None
        self._logger_provider: LoggerProvider | None = None
        self._otel_logger: Logger | None = None

        if not settings.enabled:
            self.tracer = trace.NoOpTracerProvider().get_tracer(__name__)
            meter = metrics.NoOpMeterProvider().get_meter(__name__)
            self._create_instruments(meter)
            return

        resource = Resource.create(
            {
                SERVICE_NAME: self.service_name,
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
                max_queue_size=512,
                max_export_batch_size=128,
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
                max_queue_size=512,
                max_export_batch_size=128,
                schedule_delay_millis=1000,
                export_timeout_millis=timeout * 1000,
            )
        )

        self._tracer_provider = tracer_provider
        self._meter_provider = meter_provider
        self._logger_provider = logger_provider
        self.tracer = tracer_provider.get_tracer(__name__, "0.1.0")
        meter = meter_provider.get_meter(__name__, "0.1.0")
        self._create_instruments(meter)
        self._otel_logger = logger_provider.get_logger(__name__, "0.1.0")

    def _create_instruments(self, meter: Any) -> None:
        """Create the complete bounded metric vocabulary in enabled and no-op modes."""
        self._request_count = meter.create_counter(
            "simulator.http.server.requests",
            description="Completed simulator HTTP server requests",
        )
        self._request_duration = meter.create_histogram(
            "simulator.http.server.duration",
            unit="ms",
            description="Simulator HTTP server request duration",
        )
        self._client_count = meter.create_counter(
            "simulator.http.client.requests",
            description="Completed simulator downstream HTTP requests",
        )
        self._client_duration = meter.create_histogram(
            "simulator.http.client.duration",
            unit="ms",
            description="Simulator downstream HTTP request duration",
        )
        self._dependency_count = meter.create_counter(
            "simulator.dependency.operations",
            description="Completed simulator dependency operations",
        )
        self._dependency_duration = meter.create_histogram(
            "simulator.dependency.duration",
            unit="ms",
            description="Simulator dependency operation duration",
        )

    def server_span(
        self,
        method: str,
        correlation_id: str,
        carrier: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[Span]:
        """Start a server span with bounded, non-sensitive initial attributes."""
        return cast(
            AbstractContextManager[Span],
            self.tracer.start_as_current_span(
                f"HTTP {method}",
                kind=SpanKind.SERVER,
                context=(
                    TRACE_CONTEXT_PROPAGATOR.extract(carrier=carrier)
                    if carrier is not None
                    else None
                ),
                attributes={
                    "http.request.method": method,
                    "agentops.correlation_id": correlation_id,
                },
            ),
        )

    def inject_trace_context(self, carrier: dict[str, str]) -> None:
        """Inject only W3C trace context; never forward caller-supplied baggage."""
        TRACE_CONTEXT_PROPAGATOR.inject(carrier=carrier)

    def complete_client_request(
        self,
        span: Span,
        *,
        service: str,
        method: str,
        route: str,
        status_code: int | None,
        started_at: float,
        correlation_id: str,
        result: Literal["ok", "error"] | None = None,
    ) -> None:
        """Record one downstream outcome without URLs, payloads, or exception details."""
        status = str(status_code) if status_code is not None else "transport_error"
        request_result = (
            result
            if result is not None
            else ("ok" if status_code is not None and status_code < 400 else "error")
        )
        attributes: dict[str, str | int] = {
            "server.address": service,
            "http.request.method": method,
            "http.route": route,
            "request.result": request_result,
        }
        if status_code is not None:
            attributes["http.response.status_code"] = status_code
        else:
            attributes["error.type"] = "transport"
        span.set_attributes(attributes)
        if request_result == "error":
            span.set_status(Status(StatusCode.ERROR))
        duration_ms = (time.monotonic() - started_at) * 1000
        metric_attributes = {
            "service": service,
            "method": method,
            "route": route,
            "status": status,
            "result": request_result,
        }
        self._client_count.add(1, metric_attributes)
        self._client_duration.record(duration_ms, metric_attributes)
        self._emit_log(
            body="http_client_request",
            severity=(SeverityNumber.INFO if request_result == "ok" else SeverityNumber.WARN),
            attributes={
                **attributes,
                "service.name": self.service_name,
                "duration_ms": duration_ms,
                "agentops.correlation_id": correlation_id,
            },
        )

    def record_dependency(
        self,
        *,
        dependency: str,
        operation: str,
        result: str,
        duration_ms: float,
        correlation_id: str,
    ) -> None:
        """Record one bounded PostgreSQL or Redis operation in all three signals."""
        metric_attributes = {
            "dependency": dependency,
            "operation": operation,
            "result": result,
        }
        self._dependency_count.add(1, metric_attributes)
        self._dependency_duration.record(duration_ms, metric_attributes)
        self._emit_log(
            body="dependency_operation",
            severity=SeverityNumber.INFO if result == "ok" else SeverityNumber.WARN,
            attributes={
                "service.name": self.service_name,
                "dependency": dependency,
                "operation": operation,
                "result": result,
                "duration_ms": duration_ms,
                "agentops.correlation_id": correlation_id,
            },
        )

    def _emit_log(
        self,
        *,
        body: str,
        severity: SeverityNumber,
        attributes: Mapping[str, Any],
    ) -> None:
        if self._otel_logger is not None:
            self._otel_logger.emit(
                severity_number=severity,
                severity_text=severity.name,
                body=body,
                attributes=dict(attributes),
            )

    def client_span(
        self, service: str, method: str, route: str, correlation_id: str
    ) -> AbstractContextManager[Span]:
        """Start an internal client span without recording a URL or request body."""
        return cast(
            AbstractContextManager[Span],
            self.tracer.start_as_current_span(
                f"{method} {service}",
                kind=SpanKind.CLIENT,
                attributes={
                    "server.address": service,
                    "http.request.method": method,
                    "http.route": route,
                    "agentops.correlation_id": correlation_id,
                },
            ),
        )

    def complete_request(
        self,
        span: Span,
        *,
        method: str,
        route: str,
        status_code: int,
        started_at: float,
        correlation_id: str,
    ) -> None:
        """Record the stable route, status, duration, and one safe access log."""
        attributes: dict[str, str | int] = {
            "http.request.method": method,
            "http.route": route,
            "http.response.status_code": status_code,
        }
        span.update_name(f"{method} {route}")
        span.set_attributes(attributes)
        if status_code >= 500:
            span.set_status(Status(StatusCode.ERROR))
        duration_ms = (time.monotonic() - started_at) * 1000
        metric_attributes = {"method": method, "route": route, "status": str(status_code)}
        self._request_count.add(1, metric_attributes)
        self._request_duration.record(duration_ms, metric_attributes)
        logger.info(
            "http_request service=%s method=%s route=%s status=%s "
            "duration_ms=%.3f correlation_id=%s",
            self.service_name,
            method,
            route,
            status_code,
            duration_ms,
            correlation_id,
        )
        self._emit_log(
            body="http_request",
            severity=SeverityNumber.INFO,
            attributes={
                **attributes,
                "service.name": self.service_name,
                "duration_ms": duration_ms,
                "agentops.correlation_id": correlation_id,
            },
        )

    def record_deployment(self, attributes: Mapping[str, str]) -> None:
        """Emit one bounded marker for startup or a typed deployment transition."""
        event_attributes = {
            **dict(attributes),
            "deployment.environment": self.settings.environment,
            "event.observed_at": datetime.now(UTC).isoformat(),
        }
        logger.info(json.dumps(event_attributes, sort_keys=True))
        self._emit_log(
            body="service.deployment.changed",
            severity=SeverityNumber.INFO,
            attributes=event_attributes,
        )

    async def shutdown(self) -> None:
        """Flush providers within a fixed application-shutdown deadline."""
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
            logger.warning("telemetry_shutdown_timeout service=%s", self.service_name)


def create_telemetry(
    service: str, environment: Mapping[str, str] | None = None
) -> SimulatorTelemetry:
    """Create configured telemetry, falling back to no-op providers on setup errors."""
    try:
        return SimulatorTelemetry(service, TelemetrySettings.from_environment(environment))
    except Exception:
        logger.warning("telemetry_initialization_failed service=%s", service)
        return SimulatorTelemetry(
            service,
            TelemetrySettings(
                enabled=False,
                endpoint="http://otel-collector:4318",
                timeout_seconds=2,
                export_interval_millis=5000,
                environment="local",
                service_version="1.0.0",
            ),
        )

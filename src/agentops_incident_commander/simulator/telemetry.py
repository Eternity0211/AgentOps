"""Explicit, bounded OpenTelemetry setup for one simulator service process."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, cast
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

logger = logging.getLogger("agentops.simulator.telemetry")


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
        return cls(
            enabled=_enabled(source.get("OTEL_SDK_ENABLED", "false")),
            endpoint=endpoint.rstrip("/"),
            timeout_seconds=timeout,
            export_interval_millis=interval,
            environment=source.get("DEPLOYMENT_ENVIRONMENT", "local"),
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
            self._request_count = meter.create_counter("simulator.http.server.requests")
            self._request_duration = meter.create_histogram(
                "simulator.http.server.duration", unit="ms"
            )
            return

        resource = Resource.create(
            {
                SERVICE_NAME: self.service_name,
                SERVICE_VERSION: "0.1.0",
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
        self._request_count = meter.create_counter(
            "simulator.http.server.requests",
            description="Completed simulator HTTP server requests",
        )
        self._request_duration = meter.create_histogram(
            "simulator.http.server.duration",
            unit="ms",
            description="Simulator HTTP server request duration",
        )
        self._otel_logger = logger_provider.get_logger(__name__, "0.1.0")

    def server_span(self, method: str, correlation_id: str) -> AbstractContextManager[Span]:
        """Start a server span with bounded, non-sensitive initial attributes."""
        return cast(
            AbstractContextManager[Span],
            self.tracer.start_as_current_span(
                f"HTTP {method}",
                kind=SpanKind.SERVER,
                attributes={
                    "http.request.method": method,
                    "agentops.correlation_id": correlation_id,
                },
            ),
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
        if self._otel_logger is not None:
            self._otel_logger.emit(
                severity_number=SeverityNumber.INFO,
                severity_text="INFO",
                body="http_request",
                attributes={
                    **attributes,
                    "service.name": self.service_name,
                    "duration_ms": duration_ms,
                    "agentops.correlation_id": correlation_id,
                },
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
            ),
        )

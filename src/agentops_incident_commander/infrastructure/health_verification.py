"""Bounded read-only collection of Artifact-backed health-verification signals."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Protocol

from agentops_incident_commander.application import (
    HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION,
    HealthVerificationSignal,
)
from agentops_incident_commander.domain import (
    ArtifactId,
    EvidenceBuildRequest,
    EvidenceId,
    EvidenceLineage,
    EvidenceNormalizer,
    EvidenceSourceType,
    HealthVerificationCriteria,
    HealthVerificationObservation,
    HealthVerificationSample,
    InvalidDomainValueError,
    JsonValue,
    NormalizedEvidence,
    NormalizedQuery,
    OpaqueIdentifier,
    PromptInjectionStatus,
    QualitySignals,
    QueryParameter,
    SemanticVersion,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
    as_utc,
)

from .tool_adapters import MetricBackendResult, MetricName, MetricQuery, MetricsBackend

HEALTH_VERIFICATION_COLLECTION_SCHEMA_VERSION: Final = "1.0.0"
MAX_VERIFICATION_COLLECTION_TIMEOUT_SECONDS: Final = 30.0


@dataclass(frozen=True, slots=True)
class HealthProbeSample:
    observed_at: datetime
    healthy: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if not isinstance(self.healthy, bool):
            raise InvalidDomainValueError("health probe sample is invalid")


@dataclass(frozen=True, slots=True)
class ActiveVersionSample:
    observed_at: datetime
    version: SemanticVersion

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if not isinstance(self.version, SemanticVersion):
            raise InvalidDomainValueError("active-version sample is invalid")


@dataclass(frozen=True, slots=True)
class NewAlertCountSample:
    observed_at: datetime
    count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        if (
            not isinstance(self.count, int)
            or isinstance(self.count, bool)
            or not 0 <= self.count <= 10_000
        ):
            raise InvalidDomainValueError("new-alert sample is invalid")


@dataclass(frozen=True, slots=True)
class HealthProbeResult:
    samples: tuple[HealthProbeSample, ...]
    complete_window: bool

    def __post_init__(self) -> None:
        if not isinstance(self.complete_window, bool) or any(
            not isinstance(item, HealthProbeSample) for item in self.samples
        ):
            raise InvalidDomainValueError("health probe result is invalid")


@dataclass(frozen=True, slots=True)
class ActiveVersionResult:
    samples: tuple[ActiveVersionSample, ...]
    complete_window: bool

    def __post_init__(self) -> None:
        if not isinstance(self.complete_window, bool) or any(
            not isinstance(item, ActiveVersionSample) for item in self.samples
        ):
            raise InvalidDomainValueError("active-version result is invalid")


@dataclass(frozen=True, slots=True)
class NewAlertCountResult:
    samples: tuple[NewAlertCountSample, ...]
    complete_window: bool

    def __post_init__(self) -> None:
        if not isinstance(self.complete_window, bool) or any(
            not isinstance(item, NewAlertCountSample) for item in self.samples
        ):
            raise InvalidDomainValueError("new-alert result is invalid")


class HealthProbeBackend(Protocol):
    async def read(
        self, *, service: str, environment: str, sample_times: tuple[datetime, ...]
    ) -> HealthProbeResult: ...


class ActiveVersionBackend(Protocol):
    async def read(
        self, *, service: str, environment: str, sample_times: tuple[datetime, ...]
    ) -> ActiveVersionResult: ...


class NewAlertCountBackend(Protocol):
    async def read(
        self,
        *,
        service: str,
        environment: str,
        window_started_at: datetime,
        sample_times: tuple[datetime, ...],
    ) -> NewAlertCountResult: ...


@dataclass(frozen=True, slots=True)
class HealthVerificationCollectionIds:
    observation_id: OpaqueIdentifier
    workflow_run_id: WorkflowRunId
    error_rate_evidence_id: EvidenceId
    error_rate_artifact_id: ArtifactId
    error_rate_tool_call_id: ToolCallId
    p95_latency_evidence_id: EvidenceId
    p95_latency_artifact_id: ArtifactId
    p95_latency_tool_call_id: ToolCallId
    health_endpoint_evidence_id: EvidenceId
    health_endpoint_artifact_id: ArtifactId
    health_endpoint_tool_call_id: ToolCallId
    deployed_version_evidence_id: EvidenceId
    deployed_version_artifact_id: ArtifactId
    deployed_version_tool_call_id: ToolCallId
    new_alerts_evidence_id: EvidenceId
    new_alerts_artifact_id: ArtifactId
    new_alerts_tool_call_id: ToolCallId

    def __post_init__(self) -> None:
        typed_groups = (
            (
                self.error_rate_evidence_id,
                self.p95_latency_evidence_id,
                self.health_endpoint_evidence_id,
                self.deployed_version_evidence_id,
                self.new_alerts_evidence_id,
            ),
            (
                self.error_rate_artifact_id,
                self.p95_latency_artifact_id,
                self.health_endpoint_artifact_id,
                self.deployed_version_artifact_id,
                self.new_alerts_artifact_id,
            ),
            (
                self.error_rate_tool_call_id,
                self.p95_latency_tool_call_id,
                self.health_endpoint_tool_call_id,
                self.deployed_version_tool_call_id,
                self.new_alerts_tool_call_id,
            ),
        )
        if not isinstance(self.observation_id, OpaqueIdentifier) or not isinstance(
            self.workflow_run_id, WorkflowRunId
        ):
            raise InvalidDomainValueError("health verification collection identities are invalid")
        expected_types = (EvidenceId, ArtifactId, ToolCallId)
        if any(
            any(not isinstance(item, expected_type) for item in items)
            for items, expected_type in zip(typed_groups, expected_types, strict=True)
        ):
            raise InvalidDomainValueError("health verification collection identities are invalid")
        if any(len(items) != len(set(items)) for items in typed_groups):
            raise InvalidDomainValueError(
                "health verification collection identities must be unique"
            )


@dataclass(frozen=True, slots=True)
class HealthVerificationCollectionRequest:
    criteria: HealthVerificationCriteria
    ids: HealthVerificationCollectionIds
    window_started_at: datetime
    sample_interval_seconds: int
    collected_at: datetime
    expires_at: datetime
    artifact_expires_at: datetime
    schema_version: str = HEALTH_VERIFICATION_COLLECTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.criteria, HealthVerificationCriteria) or not isinstance(
            self.ids, HealthVerificationCollectionIds
        ):
            raise InvalidDomainValueError("health verification collection scope is invalid")
        started = as_utc(self.window_started_at)
        collected = as_utc(self.collected_at)
        expires = as_utc(self.expires_at)
        artifact_expires = as_utc(self.artifact_expires_at)
        if (
            not isinstance(self.sample_interval_seconds, int)
            or isinstance(self.sample_interval_seconds, bool)
            or self.sample_interval_seconds < 1
            or self.sample_interval_seconds > self.criteria.max_sample_gap_seconds
            or self.criteria.stability_window_seconds % self.sample_interval_seconds != 0
        ):
            raise InvalidDomainValueError("health verification sampling interval is invalid")
        ended = started + timedelta(seconds=self.criteria.stability_window_seconds)
        if not ended <= collected < expires <= artifact_expires:
            raise InvalidDomainValueError("health verification collection times are invalid")
        if self.schema_version != HEALTH_VERIFICATION_COLLECTION_SCHEMA_VERSION:
            raise InvalidDomainValueError("health verification collection schema is unsupported")
        object.__setattr__(self, "window_started_at", started)
        object.__setattr__(self, "collected_at", collected)
        object.__setattr__(self, "expires_at", expires)
        object.__setattr__(self, "artifact_expires_at", artifact_expires)

    @property
    def sample_times(self) -> tuple[datetime, ...]:
        return tuple(
            self.window_started_at + timedelta(seconds=offset)
            for offset in range(
                0,
                self.criteria.stability_window_seconds + 1,
                self.sample_interval_seconds,
            )
        )


@dataclass(frozen=True, slots=True)
class CollectedHealthVerification:
    observation: HealthVerificationObservation
    evidence: tuple[NormalizedEvidence, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.observation, HealthVerificationObservation) or (
            len(self.evidence) != len(HealthVerificationSignal)
            or any(not isinstance(item, NormalizedEvidence) for item in self.evidence)
        ):
            raise InvalidDomainValueError("health verification collection is incomplete")


class LiveHealthVerificationCollector:
    """Query five fixed read-only ports and atomically construct a complete observation bundle."""

    def __init__(
        self,
        metrics: MetricsBackend,
        health: HealthProbeBackend,
        versions: ActiveVersionBackend,
        alerts: NewAlertCountBackend,
        *,
        timeout_seconds: float = 10.0,
    ) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not 0 < timeout_seconds <= MAX_VERIFICATION_COLLECTION_TIMEOUT_SECONDS
        ):
            raise InvalidDomainValueError("health verification collection timeout is invalid")
        self._metrics = metrics
        self._health = health
        self._versions = versions
        self._alerts = alerts
        self._timeout_seconds = timeout_seconds

    async def collect(
        self, request: HealthVerificationCollectionRequest
    ) -> CollectedHealthVerification:
        if not isinstance(request, HealthVerificationCollectionRequest):
            raise InvalidDomainValueError("health verification collection request is invalid")
        criteria = request.criteria
        times = request.sample_times
        end = times[-1]

        def metric_query(metric: MetricName) -> MetricQuery:
            return MetricQuery(
                metric=metric,
                service=criteria.service,
                environment=criteria.environment.value.lower(),
                start=request.window_started_at.isoformat(),
                end=end.isoformat(),
                step_seconds=request.sample_interval_seconds,
            )

        async with asyncio.timeout(self._timeout_seconds):
            (
                error_result,
                p95_result,
                health_result,
                version_result,
                alert_result,
            ) = await asyncio.gather(
                self._metrics.query_range(metric_query(MetricName.HTTP_ERROR_RATE)),
                self._metrics.query_range(metric_query(MetricName.HTTP_DURATION_P95)),
                self._health.read(
                    service=criteria.service,
                    environment=criteria.environment.value.lower(),
                    sample_times=times,
                ),
                self._versions.read(
                    service=criteria.service,
                    environment=criteria.environment.value.lower(),
                    sample_times=times,
                ),
                self._alerts.read(
                    service=criteria.service,
                    environment=criteria.environment.value.lower(),
                    window_started_at=request.window_started_at,
                    sample_times=times,
                ),
            )
        error_values = _metric_values(
            error_result,
            MetricName.HTTP_ERROR_RATE,
            times,
            criteria.service,
            criteria.environment.value.lower(),
        )
        p95_values = _metric_values(
            p95_result,
            MetricName.HTTP_DURATION_P95,
            times,
            criteria.service,
            criteria.environment.value.lower(),
        )
        health_values = _series_values(health_result, times, "health endpoint")
        version_values = _series_values(version_result, times, "active version")
        alert_values = _series_values(alert_result, times, "new alerts")
        samples = tuple(
            HealthVerificationSample(
                observed_at=observed_at,
                error_rate_basis_points=_scaled(error_rate, 10_000, "error rate"),
                p95_latency_ms=_scaled(p95, 1_000, "P95 latency"),
                health_endpoint_healthy=health_sample.healthy,
                deployed_version=version_sample.version,
                new_alert_count=alert_sample.count,
            )
            for observed_at, error_rate, p95, health_sample, version_sample, alert_sample in zip(
                times,
                error_values,
                p95_values,
                health_values,
                version_values,
                alert_values,
                strict=True,
            )
        )
        observation = HealthVerificationObservation(
            id=request.ids.observation_id,
            tenant_id=criteria.tenant_id,
            incident_id=criteria.incident_id,
            action_execution_id=criteria.action_execution_id,
            service=criteria.service,
            environment=criteria.environment,
            expected_stable_version=criteria.expected_stable_version,
            window_started_at=request.window_started_at,
            window_ended_at=end,
            samples=samples,
            error_rate_evidence_id=request.ids.error_rate_evidence_id,
            p95_latency_evidence_id=request.ids.p95_latency_evidence_id,
            health_endpoint_evidence_id=request.ids.health_endpoint_evidence_id,
            deployed_version_evidence_id=request.ids.deployed_version_evidence_id,
            new_alerts_evidence_id=request.ids.new_alerts_evidence_id,
            collected_at=request.collected_at,
            expires_at=request.expires_at,
        )
        evidence = _normalize_evidence(request, observation)
        return CollectedHealthVerification(observation, evidence)


def _metric_values(
    result: MetricBackendResult,
    metric: MetricName,
    times: tuple[datetime, ...],
    service: str,
    environment: str,
) -> tuple[float, ...]:
    if not result.complete_window or result.records_dropped:
        raise InvalidDomainValueError("health verification metric window is incomplete")
    expected_labels = (("environment", environment), ("service", service))
    if tuple(item.observed_at for item in result.samples) != times or any(
        item.metric != metric.value or item.labels != expected_labels for item in result.samples
    ):
        raise InvalidDomainValueError("health verification metric samples are misaligned")
    return tuple(item.value for item in result.samples)


def _series_values(
    result: HealthProbeResult | ActiveVersionResult | NewAlertCountResult,
    times: tuple[datetime, ...],
    label: str,
) -> tuple[HealthProbeSample | ActiveVersionSample | NewAlertCountSample, ...]:
    if not result.complete_window:
        raise InvalidDomainValueError(f"health verification {label} window is incomplete")
    if tuple(item.observed_at for item in result.samples) != times:
        raise InvalidDomainValueError(f"health verification {label} samples are misaligned")
    return result.samples


def _scaled(value: float, scale: int, label: str) -> int:
    decimal = Decimal(str(value))
    if not isinstance(value, float) or not decimal.is_finite() or value < 0:
        raise InvalidDomainValueError(f"health verification {label} value is invalid")
    return int((decimal * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_evidence(
    request: HealthVerificationCollectionRequest,
    observation: HealthVerificationObservation,
) -> tuple[NormalizedEvidence, ...]:
    ids = request.ids
    definitions = (
        (
            HealthVerificationSignal.ERROR_RATE,
            ids.error_rate_evidence_id,
            ids.error_rate_artifact_id,
            ids.error_rate_tool_call_id,
            EvidenceSourceType.METRIC,
            "prometheus-primary",
            "query_metrics",
            ("metric", "http_request_error_rate"),
            tuple(item.error_rate_basis_points for item in observation.samples),
        ),
        (
            HealthVerificationSignal.P95_LATENCY,
            ids.p95_latency_evidence_id,
            ids.p95_latency_artifact_id,
            ids.p95_latency_tool_call_id,
            EvidenceSourceType.METRIC,
            "prometheus-primary",
            "query_metrics",
            ("metric", "http_request_duration_p95"),
            tuple(item.p95_latency_ms for item in observation.samples),
        ),
        (
            HealthVerificationSignal.HEALTH_ENDPOINT,
            ids.health_endpoint_evidence_id,
            ids.health_endpoint_artifact_id,
            ids.health_endpoint_tool_call_id,
            EvidenceSourceType.TRACE,
            "health-probe-primary",
            "query_traces",
            ("endpoint", "/healthz"),
            tuple(item.health_endpoint_healthy for item in observation.samples),
        ),
        (
            HealthVerificationSignal.DEPLOYED_VERSION,
            ids.deployed_version_evidence_id,
            ids.deployed_version_artifact_id,
            ids.deployed_version_tool_call_id,
            EvidenceSourceType.DEPLOYMENT,
            "deployment-registry-primary",
            "query_deployments",
            None,
            tuple(item.deployed_version.value for item in observation.samples),
        ),
        (
            HealthVerificationSignal.NEW_ALERTS,
            ids.new_alerts_evidence_id,
            ids.new_alerts_artifact_id,
            ids.new_alerts_tool_call_id,
            EvidenceSourceType.LOG,
            "alert-store-primary",
            "query_logs",
            ("record_kind", "alert"),
            tuple(item.new_alert_count for item in observation.samples),
        ),
    )
    normalized: list[NormalizedEvidence] = []
    for (
        signal,
        evidence_id,
        artifact_id,
        call_id,
        source_type,
        source_instance,
        tool_name,
        discriminator,
        values,
    ) in definitions:
        query = {
            "end": observation.window_ended_at.isoformat(),
            "environment": observation.environment.value.lower(),
            "service": observation.service,
            "start": observation.window_started_at.isoformat(),
        }
        if discriminator is not None:
            query[discriminator[0]] = discriminator[1]
        build = EvidenceBuildRequest(
            evidence_id=evidence_id,
            artifact_id=artifact_id,
            tenant_id=observation.tenant_id,
            incident_id=observation.incident_id,
            source_type=source_type,
            source_instance=source_instance,
            tool_name=tool_name,
            tool_version="1.0.0",
            tool_schema_version="1.0.0",
            normalized_query=NormalizedQuery(
                tuple(QueryParameter(key, value) for key, value in query.items())
            ),
            observed_from=observation.window_started_at,
            observed_to=observation.window_ended_at,
            collected_at=request.collected_at,
            expires_at=request.expires_at,
            artifact_expires_at=request.artifact_expires_at,
            parser_version="1.0.0",
            normalizer_version="1.0.0",
            quality_signals=QualitySignals(True, True, len(observation.samples)),
            lineage=EvidenceLineage(call_id, ids.workflow_run_id, None),
            trust=TrustClassification.DIRECT_OBSERVATION,
            prompt_injection_status=PromptInjectionStatus.NONE,
        )
        payload: JsonValue = {
            "environment": observation.environment.value.lower(),
            "kind": "health-verification-signal",
            "samples": [
                {"observed_at": sample.observed_at.isoformat(), "value": value}
                for sample, value in zip(observation.samples, values, strict=True)
            ],
            "schema_version": HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION,
            "service": observation.service,
            "signal": signal.value,
            "window_ended_at": observation.window_ended_at.isoformat(),
            "window_started_at": observation.window_started_at.isoformat(),
        }
        normalized.append(EvidenceNormalizer().normalize(build, payload))
    return tuple(normalized)

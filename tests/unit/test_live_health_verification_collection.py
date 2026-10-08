"""Bounded live health signal collection and canonical Evidence tests."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentops_incident_commander.application import resolve_health_verification_evidence
from agentops_incident_commander.domain import (
    ActorId,
    Artifact,
    ArtifactContent,
    ArtifactId,
    Evidence,
    EvidenceId,
    HealthVerificationCriteria,
    HealthVerificationScenario,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyEnvironment,
    Principal,
    Role,
    SemanticVersion,
    TenantId,
    ToolCallId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import (
    HEALTH_VERIFICATION_COLLECTION_SCHEMA_VERSION,
    ActiveVersionResult,
    ActiveVersionSample,
    CollectedHealthVerification,
    HealthProbeResult,
    HealthProbeSample,
    HealthVerificationCollectionIds,
    HealthVerificationCollectionRequest,
    LiveHealthVerificationCollector,
    NewAlertCountResult,
    NewAlertCountSample,
)
from agentops_incident_commander.infrastructure.collectors import MetricSample
from agentops_incident_commander.infrastructure.tool_adapters import (
    MetricBackendResult,
    MetricName,
    MetricQuery,
)

NOW = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)
TENANT = TenantId("tenant-live-verification")
INCIDENT = IncidentId("incident-live-verification")
PRINCIPAL = Principal(ActorId("viewer-live-verification"), TENANT, frozenset({Role.VIEWER}))


def criteria() -> HealthVerificationCriteria:
    return HealthVerificationCriteria(
        TENANT,
        INCIDENT,
        OpaqueIdentifier("execution-live-verification"),
        HealthVerificationScenario.RELEASE_HTTP_500,
        "orders",
        PolicyEnvironment.PRODUCTION,
        SemanticVersion("1.0.0"),
        100,
        500,
        0,
        60,
        30,
    )


def ids(**overrides: Any) -> HealthVerificationCollectionIds:
    values: dict[str, Any] = {
        "observation_id": OpaqueIdentifier("observation-live-verification"),
        "workflow_run_id": WorkflowRunId("workflow-live-verification"),
    }
    for prefix in (
        "error_rate",
        "p95_latency",
        "health_endpoint",
        "deployed_version",
        "new_alerts",
    ):
        values[f"{prefix}_evidence_id"] = EvidenceId(f"evidence-{prefix}")
        values[f"{prefix}_artifact_id"] = ArtifactId(f"artifact-{prefix}")
        values[f"{prefix}_tool_call_id"] = ToolCallId(f"call-{prefix}")
    values.update(overrides)
    return HealthVerificationCollectionIds(**values)


def request(**overrides: Any) -> HealthVerificationCollectionRequest:
    values: dict[str, Any] = {
        "criteria": criteria(),
        "ids": ids(),
        "window_started_at": NOW,
        "sample_interval_seconds": 30,
        "collected_at": NOW + timedelta(seconds=61),
        "expires_at": NOW + timedelta(minutes=5),
        "artifact_expires_at": NOW + timedelta(minutes=6),
    }
    values.update(overrides)
    return HealthVerificationCollectionRequest(**values)


def times() -> tuple[datetime, ...]:
    return request().sample_times


class Metrics:
    def __init__(self) -> None:
        self.queries: list[MetricQuery] = []
        self.error_result = metric_result(MetricName.HTTP_ERROR_RATE, 0.005)
        self.p95_result = metric_result(MetricName.HTTP_DURATION_P95, 0.4)

    async def query_range(self, query: MetricQuery) -> MetricBackendResult:
        self.queries.append(query)
        return self.error_result if query.metric is MetricName.HTTP_ERROR_RATE else self.p95_result


def metric_result(
    metric: MetricName,
    value: float,
    *,
    sample_times: tuple[datetime, ...] | None = None,
    labels: tuple[tuple[str, str], ...] = (
        ("environment", "production"),
        ("service", "orders"),
    ),
    complete: bool = True,
    dropped: int = 0,
) -> MetricBackendResult:
    points = times() if sample_times is None else sample_times
    return MetricBackendResult(
        tuple(MetricSample(metric.value, at, value, labels) for at in points), complete, dropped
    )


def tampered_metric_result(metric: MetricName, value: float) -> MetricBackendResult:
    result = metric_result(metric, 0.1)
    for item in result.samples:
        object.__setattr__(item, "value", value)
    return result


def invalid_result(factory: Any, samples: Any, complete: Any) -> Any:
    return factory(samples, complete)


class Health:
    def __init__(self, result: HealthProbeResult | None = None) -> None:
        self.result = result or HealthProbeResult(
            tuple(HealthProbeSample(at, True) for at in times()), True
        )
        self.calls: list[tuple[str, str, tuple[datetime, ...]]] = []

    async def read(
        self, *, service: str, environment: str, sample_times: tuple[datetime, ...]
    ) -> HealthProbeResult:
        self.calls.append((service, environment, sample_times))
        return self.result


class Versions:
    def __init__(self, result: ActiveVersionResult | None = None) -> None:
        self.result = result or ActiveVersionResult(
            tuple(ActiveVersionSample(at, SemanticVersion("1.0.0")) for at in times()), True
        )

    async def read(
        self, *, service: str, environment: str, sample_times: tuple[datetime, ...]
    ) -> ActiveVersionResult:
        assert (service, environment, sample_times) == ("orders", "production", times())
        return self.result


class Alerts:
    def __init__(self, result: NewAlertCountResult | None = None) -> None:
        self.result = result or NewAlertCountResult(
            tuple(NewAlertCountSample(at, 0) for at in times()), True
        )

    async def read(
        self,
        *,
        service: str,
        environment: str,
        window_started_at: datetime,
        sample_times: tuple[datetime, ...],
    ) -> NewAlertCountResult:
        assert (service, environment, window_started_at, sample_times) == (
            "orders",
            "production",
            NOW,
            times(),
        )
        return self.result


def collector(
    *,
    metrics: Metrics | None = None,
    health: Health | None = None,
    versions: Versions | None = None,
    alerts: Alerts | None = None,
    timeout: float = 1.0,
) -> LiveHealthVerificationCollector:
    return LiveHealthVerificationCollector(
        metrics or Metrics(),
        health or Health(),
        versions or Versions(),
        alerts or Alerts(),
        timeout_seconds=timeout,
    )


class Reader:
    def __init__(self, items: tuple[Evidence, ...]) -> None:
        self.items = {item.id: item for item in items}

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        assert (tenant_id, incident_id) == (TENANT, INCIDENT)
        return self.items.get(evidence_id)


class Storage:
    def __init__(self, result: CollectedHealthVerification) -> None:
        self.items = {
            item.artifact.id: ArtifactContent(item.artifact, item.content)
            for item in result.evidence
        }

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        raise AssertionError((artifact, content))

    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        assert (incident_id, principal, at) == (
            INCIDENT,
            PRINCIPAL,
            NOW + timedelta(seconds=62),
        )
        return self.items[artifact_id]


@pytest.mark.anyio
async def test_collects_aligned_real_ports_and_builds_resolvable_artifacts() -> None:
    metrics = Metrics()
    health = Health()
    result = await collector(metrics=metrics, health=health).collect(request())
    assert [item.metric for item in metrics.queries] == [
        MetricName.HTTP_ERROR_RATE,
        MetricName.HTTP_DURATION_P95,
    ]
    assert all(
        (item.service, item.environment, item.start, item.end, item.step_seconds)
        == ("orders", "production", NOW.isoformat(), times()[-1].isoformat(), 30)
        for item in metrics.queries
    )
    assert health.calls == [("orders", "production", times())]
    assert tuple(item.error_rate_basis_points for item in result.observation.samples) == (
        50,
        50,
        50,
    )
    assert tuple(item.p95_latency_ms for item in result.observation.samples) == (400, 400, 400)
    assert len(result.evidence) == 5
    assert [json.loads(item.content)["signal"] for item in result.evidence] == [
        "ERROR_RATE_BASIS_POINTS",
        "P95_LATENCY_MS",
        "HEALTH_ENDPOINT_HEALTHY",
        "DEPLOYED_VERSION",
        "NEW_ALERT_COUNT",
    ]
    resolution = await resolve_health_verification_evidence(
        result.observation,
        principal=PRINCIPAL,
        reader=Reader(tuple(item.evidence for item in result.evidence)),
        artifact_storage=Storage(result),
        at=NOW + timedelta(seconds=62),
    )
    assert resolution.ready


@pytest.mark.anyio
@pytest.mark.parametrize(
    "configure",
    [
        lambda metrics: setattr(
            metrics,
            "error_result",
            metric_result(MetricName.HTTP_ERROR_RATE, 0.005, complete=False),
        ),
        lambda metrics: setattr(
            metrics,
            "error_result",
            metric_result(MetricName.HTTP_ERROR_RATE, 0.005, dropped=1),
        ),
        lambda metrics: setattr(
            metrics,
            "error_result",
            metric_result(
                MetricName.HTTP_ERROR_RATE,
                0.005,
                sample_times=(times()[0], times()[2]),
            ),
        ),
        lambda metrics: setattr(
            metrics,
            "error_result",
            metric_result(
                MetricName.HTTP_DURATION_P95,
                0.005,
            ),
        ),
        lambda metrics: setattr(
            metrics,
            "error_result",
            metric_result(
                MetricName.HTTP_ERROR_RATE,
                0.005,
                labels=(("environment", "staging"), ("service", "orders")),
            ),
        ),
    ],
)
async def test_rejects_incomplete_or_substituted_metric_series(configure: Any) -> None:
    metrics = Metrics()
    configure(metrics)
    with pytest.raises(InvalidDomainValueError, match="metric"):
        await collector(metrics=metrics).collect(request())


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("kwargs", "label"),
    [
        (
            {
                "health": Health(
                    HealthProbeResult(tuple(HealthProbeSample(at, True) for at in times()), False)
                )
            },
            "health endpoint",
        ),
        (
            {"health": Health(HealthProbeResult((HealthProbeSample(times()[0], True),), True))},
            "health endpoint",
        ),
        (
            {"versions": Versions(ActiveVersionResult((), False))},
            "active version",
        ),
        (
            {"alerts": Alerts(NewAlertCountResult((), False))},
            "new alerts",
        ),
    ],
)
async def test_rejects_incomplete_or_misaligned_nonmetric_series(
    kwargs: dict[str, Any], label: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=label):
        await collector(**kwargs).collect(request())


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("metric", "value", "label"),
    [
        (MetricName.HTTP_ERROR_RATE, -0.1, "error rate"),
        (MetricName.HTTP_DURATION_P95, float("inf"), "P95 latency"),
        (MetricName.HTTP_ERROR_RATE, 2.0, "observed error rate"),
    ],
)
async def test_rejects_invalid_or_out_of_domain_metric_values(
    metric: MetricName, value: float, label: str
) -> None:
    metrics = Metrics()
    result = (
        tampered_metric_result(metric, value)
        if value == float("inf")
        else metric_result(metric, value)
    )
    if metric is MetricName.HTTP_ERROR_RATE:
        metrics.error_result = result
    else:
        metrics.p95_result = result
    with pytest.raises(InvalidDomainValueError, match=label):
        await collector(metrics=metrics).collect(request())


@pytest.mark.anyio
async def test_collection_timeout_cancels_partial_bundle() -> None:
    class SlowHealth(Health):
        async def read(
            self, *, service: str, environment: str, sample_times: tuple[datetime, ...]
        ) -> HealthProbeResult:
            del service, environment, sample_times
            await asyncio.sleep(1)
            return self.result

    with pytest.raises(TimeoutError):
        await collector(health=SlowHealth(), timeout=0.001).collect(request())


@pytest.mark.parametrize("timeout", [0, -1, 31, True, "1"])
def test_collector_rejects_invalid_timeout(timeout: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="timeout"):
        collector(timeout=timeout)


@pytest.mark.parametrize(
    "overrides",
    [
        {"sample_interval_seconds": 0},
        {"sample_interval_seconds": True},
        {"sample_interval_seconds": 31},
        {"sample_interval_seconds": 16},
        {"collected_at": NOW + timedelta(seconds=59)},
        {"expires_at": NOW + timedelta(seconds=61)},
        {"artifact_expires_at": NOW + timedelta(seconds=61)},
        {"schema_version": "2.0.0"},
        {"criteria": object()},
    ],
)
def test_collection_request_rejects_invalid_bounds(overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidDomainValueError):
        request(**overrides)


def test_collection_identities_are_typed_and_unique() -> None:
    with pytest.raises(InvalidDomainValueError, match="unique"):
        ids(p95_latency_evidence_id=EvidenceId("evidence-error_rate"))
    with pytest.raises(InvalidDomainValueError, match="identities"):
        ids(observation_id=object())
    with pytest.raises(InvalidDomainValueError, match="identities"):
        ids(error_rate_evidence_id=ArtifactId("wrong-type"))


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (HealthProbeSample, 1),
        (ActiveVersionSample, "1.0.0"),
        (NewAlertCountSample, True),
        (NewAlertCountSample, -1),
        (NewAlertCountSample, 10_001),
    ],
)
def test_signal_samples_reject_invalid_values(factory: Any, value: Any) -> None:
    with pytest.raises(InvalidDomainValueError):
        factory(NOW, value)


@pytest.mark.parametrize(
    "result",
    [
        lambda: invalid_result(HealthProbeResult, (object(),), True),
        lambda: invalid_result(HealthProbeResult, (), 1),
        lambda: invalid_result(ActiveVersionResult, (object(),), True),
        lambda: invalid_result(ActiveVersionResult, (), 1),
        lambda: invalid_result(NewAlertCountResult, (object(),), True),
        lambda: invalid_result(NewAlertCountResult, (), 1),
    ],
)
def test_signal_results_reject_invalid_types(result: Any) -> None:
    with pytest.raises(InvalidDomainValueError):
        result()


@pytest.mark.anyio
async def test_collection_rejects_untyped_request() -> None:
    with pytest.raises(InvalidDomainValueError, match="request"):
        await collector().collect(object())  # type: ignore[arg-type]


def test_collected_bundle_rejects_incomplete_or_untyped_content() -> None:
    placeholder = object()
    with pytest.raises(InvalidDomainValueError, match="incomplete"):
        CollectedHealthVerification(placeholder, ())  # type: ignore[arg-type]
    assert HEALTH_VERIFICATION_COLLECTION_SCHEMA_VERSION == "1.0.0"

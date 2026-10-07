"""Immutable Evidence and Artifact binding for deterministic health verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentops_incident_commander.application import (
    HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION,
    EvidenceBoundHealthVerification,
    HealthVerificationEvidenceReason,
    HealthVerificationEvidenceReasonCode,
    HealthVerificationEvidenceResolution,
    HealthVerificationSignal,
    evaluate_evidence_bound_health_verification,
    resolve_health_verification_evidence,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    ApprovalId,
    Artifact,
    ArtifactContent,
    ArtifactId,
    ArtifactNotFoundError,
    Evidence,
    EvidenceBuildRequest,
    EvidenceId,
    EvidenceLineage,
    EvidenceNormalizer,
    EvidenceQuality,
    EvidenceSourceType,
    HealthVerificationCriteria,
    HealthVerificationDecision,
    HealthVerificationObservation,
    HealthVerificationOutcome,
    HealthVerificationSample,
    HealthVerificationScenario,
    IdempotencyKey,
    IncidentId,
    InvalidDomainValueError,
    NormalizedEvidence,
    NormalizedQuery,
    OpaqueIdentifier,
    PolicyEnvironment,
    Principal,
    PromptInjectionStatus,
    QualitySignals,
    QueryParameter,
    ResolvedRollbackTarget,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)

NOW = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
TENANT = TenantId("tenant-verification-evidence")
INCIDENT = IncidentId("incident-verification-evidence")
EXECUTION_ID = OpaqueIdentifier("execution-verification-evidence")
PRINCIPAL = Principal(ActorId("viewer-verification"), TENANT, frozenset({Role.VIEWER}))


def sample(offset: int) -> HealthVerificationSample:
    return HealthVerificationSample(
        NOW + timedelta(seconds=offset),
        50,
        400,
        True,
        SemanticVersion("1.0.0"),
        0,
    )


def observation(**overrides: Any) -> HealthVerificationObservation:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("observation-verification-evidence"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "action_execution_id": EXECUTION_ID,
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "expected_stable_version": SemanticVersion("1.0.0"),
        "window_started_at": NOW,
        "window_ended_at": NOW + timedelta(seconds=60),
        "samples": (sample(0), sample(30), sample(60)),
        "error_rate_evidence_id": EvidenceId("evidence-error-rate"),
        "p95_latency_evidence_id": EvidenceId("evidence-p95-latency"),
        "health_endpoint_evidence_id": EvidenceId("evidence-health-endpoint"),
        "deployed_version_evidence_id": EvidenceId("evidence-deployed-version"),
        "new_alerts_evidence_id": EvidenceId("evidence-new-alerts"),
        "collected_at": NOW + timedelta(seconds=61),
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return HealthVerificationObservation(**values)


def criteria() -> HealthVerificationCriteria:
    return HealthVerificationCriteria(
        TENANT,
        INCIDENT,
        EXECUTION_ID,
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


def execution() -> ActionExecution:
    target = ResolvedRollbackTarget(
        TENANT,
        "orders",
        PolicyEnvironment.PRODUCTION,
        OpaqueIdentifier("simulator-orders"),
        SemanticVersion("2.0.0"),
        SemanticVersion("1.0.0"),
    )
    before = ActionSnapshot(
        ArtifactId("verification-before-evidence"),
        TENANT,
        INCIDENT,
        "orders",
        PolicyEnvironment.PRODUCTION,
        OpaqueIdentifier("simulator-orders"),
        SemanticVersion("2.0.0"),
        NOW - timedelta(minutes=1),
        Sha256Digest("a" * 64),
    )
    after = replace(
        before,
        artifact_id=ArtifactId("verification-after-evidence"),
        deployed_version=SemanticVersion("1.0.0"),
        observed_at=NOW,
        content_hash=Sha256Digest("b" * 64),
    )
    started = ActionExecution(
        EXECUTION_ID,
        TENANT,
        INCIDENT,
        ApprovalId("approval-verification-evidence"),
        IdempotencyKey("rollback-verification-evidence"),
        ActorId("operator-verification-evidence"),
        Sha256Digest("c" * 64),
        Sha256Digest("d" * 64),
        target,
        before,
        ActionExecutionStatus.STARTED,
        AggregateVersion.initial(),
        NOW - timedelta(seconds=30),
    )
    return started.succeed(after_snapshot=after, at=NOW)


CONFIG: dict[
    HealthVerificationSignal,
    tuple[
        EvidenceSourceType,
        str,
        tuple[str, str] | None,
        str,
        Callable[[HealthVerificationSample], int | bool | str],
    ],
] = {
    HealthVerificationSignal.ERROR_RATE: (
        EvidenceSourceType.METRIC,
        "query_metrics",
        ("metric", "http_request_error_rate"),
        "error_rate_evidence_id",
        lambda item: item.error_rate_basis_points,
    ),
    HealthVerificationSignal.P95_LATENCY: (
        EvidenceSourceType.METRIC,
        "query_metrics",
        ("metric", "http_request_duration_p95"),
        "p95_latency_evidence_id",
        lambda item: item.p95_latency_ms,
    ),
    HealthVerificationSignal.HEALTH_ENDPOINT: (
        EvidenceSourceType.TRACE,
        "query_traces",
        ("endpoint", "/healthz"),
        "health_endpoint_evidence_id",
        lambda item: item.health_endpoint_healthy,
    ),
    HealthVerificationSignal.DEPLOYED_VERSION: (
        EvidenceSourceType.DEPLOYMENT,
        "query_deployments",
        None,
        "deployed_version_evidence_id",
        lambda item: item.deployed_version.value,
    ),
    HealthVerificationSignal.NEW_ALERTS: (
        EvidenceSourceType.LOG,
        "query_logs",
        ("record_kind", "alert"),
        "new_alerts_evidence_id",
        lambda item: item.new_alert_count,
    ),
}


def normalized(
    signal: HealthVerificationSignal,
    *,
    observed: HealthVerificationObservation | None = None,
    evidence_overrides: dict[str, Any] | None = None,
    payload_overrides: dict[str, Any] | None = None,
    query_overrides: dict[str, str] | None = None,
) -> NormalizedEvidence:
    observed = observation() if observed is None else observed
    source, tool, discriminator, id_field, value = CONFIG[signal]
    evidence_id = getattr(observed, id_field)
    query = {
        "end": observed.window_ended_at.isoformat(),
        "environment": observed.environment.value,
        "service": observed.service,
        "start": observed.window_started_at.isoformat(),
    }
    if discriminator is not None:
        query[discriminator[0]] = discriminator[1]
    query.update(query_overrides or {})
    request_values: dict[str, Any] = {
        "evidence_id": evidence_id,
        "artifact_id": ArtifactId(f"artifact-{evidence_id.value}"),
        "tenant_id": observed.tenant_id,
        "incident_id": observed.incident_id,
        "source_type": source,
        "source_instance": f"{source.value.lower()}-primary",
        "tool_name": tool,
        "tool_version": "1.0.0",
        "tool_schema_version": "1.0.0",
        "normalized_query": NormalizedQuery(
            tuple(QueryParameter(key, item) for key, item in query.items())
        ),
        "observed_from": observed.window_started_at,
        "observed_to": observed.window_ended_at,
        "collected_at": observed.collected_at,
        "expires_at": observed.expires_at,
        "artifact_expires_at": observed.expires_at + timedelta(minutes=1),
        "parser_version": "1.0.0",
        "normalizer_version": "1.0.0",
        "quality_signals": QualitySignals(True, True, len(observed.samples)),
        "lineage": EvidenceLineage(
            ToolCallId(f"call-{signal.value.lower()}"), WorkflowRunId("run-verification"), None
        ),
        "trust": TrustClassification.DIRECT_OBSERVATION,
        "prompt_injection_status": PromptInjectionStatus.NONE,
    }
    request_values.update(evidence_overrides or {})
    payload: dict[str, Any] = {
        "environment": observed.environment.value,
        "kind": "health-verification-signal",
        "samples": [
            {"observed_at": item.observed_at.isoformat(), "value": value(item)}
            for item in observed.samples
        ],
        "schema_version": HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION,
        "service": observed.service,
        "signal": signal.value,
        "window_ended_at": observed.window_ended_at.isoformat(),
        "window_started_at": observed.window_started_at.isoformat(),
    }
    payload.update(payload_overrides or {})
    return EvidenceNormalizer().normalize(EvidenceBuildRequest(**request_values), payload)


class Reader:
    def __init__(self, evidence: tuple[Evidence, ...]) -> None:
        self.values = {item.id: item for item in evidence}

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        del tenant_id, incident_id
        return self.values.get(evidence_id)


class Storage:
    def __init__(self, items: tuple[NormalizedEvidence, ...]) -> None:
        self.values = {
            item.artifact.id: ArtifactContent(item.artifact, item.content) for item in items
        }
        self.failure: Exception | None = None

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        del artifact, content
        raise AssertionError("verification evidence resolution is read-only")

    def retrieve(
        self,
        artifact_id: ArtifactId,
        *,
        incident_id: IncidentId,
        principal: Principal | None,
        at: datetime,
    ) -> ArtifactContent:
        assert incident_id == INCIDENT
        assert principal == PRINCIPAL
        assert at == NOW + timedelta(seconds=62)
        if self.failure is not None:
            raise self.failure
        return self.values[artifact_id]


def bundle(
    replacement: NormalizedEvidence | None = None,
) -> tuple[tuple[NormalizedEvidence, ...], Reader, Storage]:
    items = tuple(normalized(signal) for signal in HealthVerificationSignal)
    if replacement is not None:
        items = tuple(
            replacement if item.evidence.id == replacement.evidence.id else item for item in items
        )
    return items, Reader(tuple(item.evidence for item in items)), Storage(items)


@pytest.mark.anyio
async def test_complete_owned_artifact_series_allows_deterministic_evaluation() -> None:
    items, reader, storage = bundle()
    result = await evaluate_evidence_bound_health_verification(
        execution(),
        criteria(),
        observation(),
        decision_id=OpaqueIdentifier("decision-verification-evidence"),
        evaluated_at=NOW + timedelta(seconds=62),
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
    )
    assert result.resolution.verified_evidence == tuple(item.evidence for item in items)
    assert result.resolution.reasons == ()
    assert result.resolution.ready
    assert result.decision is not None
    assert result.decision.outcome is HealthVerificationOutcome.PASS


@pytest.mark.anyio
async def test_missing_and_unresolvable_artifacts_fail_closed_without_a_decision() -> None:
    items, reader, storage = bundle()
    reader.values.pop(items[0].evidence.id)
    storage.failure = ArtifactNotFoundError("missing")
    result = await evaluate_evidence_bound_health_verification(
        execution(),
        criteria(),
        observation(),
        decision_id=OpaqueIdentifier("decision-verification-evidence"),
        evaluated_at=NOW + timedelta(seconds=62),
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
    )
    assert result.decision is None
    assert [reason.code for reason in result.resolution.reasons] == [
        HealthVerificationEvidenceReasonCode.EVIDENCE_NOT_FOUND,
        HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE,
        HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE,
        HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE,
        HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("replacement", "code"),
    [
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                evidence_overrides={"expires_at": NOW + timedelta(seconds=62)},
            ),
            HealthVerificationEvidenceReasonCode.EVIDENCE_EXPIRED,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                evidence_overrides={"trust": TrustClassification.DERIVED_OBSERVATION},
            ),
            HealthVerificationEvidenceReasonCode.TRUST_NOT_DIRECT,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                evidence_overrides={"prompt_injection_status": PromptInjectionStatus.QUARANTINED},
            ),
            HealthVerificationEvidenceReasonCode.PROMPT_INJECTION_UNSAFE,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                evidence_overrides={
                    "quality_signals": QualitySignals(True, False, 3),
                },
            ),
            HealthVerificationEvidenceReasonCode.WINDOW_INCOMPLETE,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                evidence_overrides={"source_type": EvidenceSourceType.LOG},
            ),
            HealthVerificationEvidenceReasonCode.SOURCE_MISMATCH,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                query_overrides={"service": "payments"},
            ),
            HealthVerificationEvidenceReasonCode.QUERY_MISMATCH,
        ),
        (
            normalized(
                HealthVerificationSignal.ERROR_RATE,
                payload_overrides={"service": "payments"},
            ),
            HealthVerificationEvidenceReasonCode.OBSERVATION_MISMATCH,
        ),
    ],
)
async def test_each_evidence_precondition_fails_closed(
    replacement: NormalizedEvidence, code: HealthVerificationEvidenceReasonCode
) -> None:
    original_id = observation().error_rate_evidence_id
    replacement = replace(replacement, evidence=replace(replacement.evidence, id=original_id))
    _, reader, storage = bundle(replacement)
    result = await resolve_health_verification_evidence(
        observation(),
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
        at=NOW + timedelta(seconds=62),
    )
    assert result.reasons[0].code is code
    assert not result.ready
    assert len(result.verified_evidence) == 4


@pytest.mark.anyio
async def test_scope_substitution_is_rejected_before_artifact_access() -> None:
    items, reader, storage = bundle()
    expected = observation().error_rate_evidence_id
    reader.values[expected] = replace(items[0].evidence, id=EvidenceId("substituted-id"))
    result = await resolve_health_verification_evidence(
        observation(),
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
        at=NOW + timedelta(seconds=62),
    )
    assert result.reasons[0].code is HealthVerificationEvidenceReasonCode.OWNERSHIP_MISMATCH


@pytest.mark.anyio
async def test_malformed_utf8_and_tampered_hash_are_rejected() -> None:
    items, reader, storage = bundle()
    first = items[0]
    storage.values[first.artifact.id] = ArtifactContent(first.artifact, b"\xff")
    result = await resolve_health_verification_evidence(
        observation(),
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
        at=NOW + timedelta(seconds=62),
    )
    assert result.reasons[0].code is HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE

    for malformed in (b"{", b"\xff"):
        digest = Sha256Digest(hashlib.sha256(malformed).hexdigest())
        artifact = replace(first.artifact, content_hash=digest, size_bytes=len(malformed))
        reader.values[first.evidence.id] = replace(first.evidence, content_hash=digest)
        storage.values[first.artifact.id] = ArtifactContent(artifact, malformed)
        result = await resolve_health_verification_evidence(
            observation(),
            principal=PRINCIPAL,
            reader=reader,
            artifact_storage=storage,
            at=NOW + timedelta(seconds=62),
        )
        assert result.reasons[0].code is HealthVerificationEvidenceReasonCode.OBSERVATION_MISMATCH


def test_resolution_value_objects_reject_impossible_states() -> None:
    reason = HealthVerificationEvidenceReason(
        HealthVerificationEvidenceReasonCode.EVIDENCE_NOT_FOUND,
        EvidenceId("evidence-x"),
        HealthVerificationSignal.ERROR_RATE,
    )
    assert not HealthVerificationEvidenceResolution((), (reason,)).ready
    with pytest.raises(InvalidDomainValueError, match="reason"):
        HealthVerificationEvidenceReason("bad", reason.evidence_id, reason.signal)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="resolution"):
        HealthVerificationEvidenceResolution((object(),), ())  # type: ignore[arg-type]
    item = normalized(HealthVerificationSignal.ERROR_RATE).evidence
    with pytest.raises(InvalidDomainValueError, match="unique"):
        HealthVerificationEvidenceResolution((item, item), ())
    incomplete = HealthVerificationEvidenceResolution((), ())
    with pytest.raises(InvalidDomainValueError, match="resolution"):
        EvidenceBoundHealthVerification(object(), None)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="complete"):
        EvidenceBoundHealthVerification(incomplete, evaluate_placeholder())


def evaluate_placeholder() -> HealthVerificationDecision:
    items, reader, storage = bundle()
    del items, reader, storage
    from agentops_incident_commander.domain import evaluate_health_verification

    return evaluate_health_verification(
        execution(),
        criteria(),
        observation(),
        decision_id=OpaqueIdentifier("placeholder-decision"),
        evaluated_at=NOW + timedelta(seconds=62),
    )


@pytest.mark.anyio
async def test_resolver_rejects_invalid_top_level_inputs() -> None:
    _, reader, storage = bundle()
    with pytest.raises(InvalidDomainValueError, match="inputs"):
        await resolve_health_verification_evidence(
            object(),  # type: ignore[arg-type]
            principal=PRINCIPAL,
            reader=reader,
            artifact_storage=storage,
            at=NOW,
        )


def test_payload_fixture_is_canonical_json() -> None:
    item = normalized(HealthVerificationSignal.ERROR_RATE)
    assert json.loads(item.content)["schema_version"] == HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION
    assert item.evidence.quality == EvidenceQuality(
        10_000, ("source-available", "complete-window", "records-observed")
    )

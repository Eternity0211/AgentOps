"""Evidence Gate reference, ownership, and immutable Artifact resolution tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from agentops_incident_commander.application import (
    evaluate_evidence_characteristics,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    Artifact,
    ArtifactContent,
    ArtifactId,
    ArtifactNotFoundError,
    Evidence,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    IncidentId,
    InvalidDomainValueError,
    NormalizedQuery,
    Principal,
    PromptInjectionStatus,
    QueryParameter,
    RedactionStatus,
    RetentionClass,
    Role,
    RootCauseEvidenceClaim,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)

NOW = datetime(2026, 10, 4, 13, 0, tzinfo=UTC)
TENANT = TenantId("tenant-gate")
INCIDENT = IncidentId("incident-gate")
CONTENT = b"payload"
DIGEST = Sha256Digest(hashlib.sha256(CONTENT).hexdigest())
PRINCIPAL = Principal(ActorId("viewer-gate"), TENANT, frozenset({Role.VIEWER}))


def evidence(identifier: str, **overrides: Any) -> Evidence:
    values: dict[str, Any] = {
        "id": EvidenceId(identifier),
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "source_type": EvidenceSourceType.LOG,
        "source_instance": "loki-primary",
        "tool_name": "query_logs",
        "tool_version": "1.0.0",
        "tool_schema_version": "1.0.0",
        "normalized_query": NormalizedQuery((QueryParameter("service", "orders"),)),
        "observed_from": NOW - timedelta(minutes=10),
        "observed_to": NOW - timedelta(minutes=5),
        "collected_at": NOW - timedelta(minutes=4),
        "artifact_id": ArtifactId(f"artifact-{identifier}"),
        "content_hash": DIGEST,
        "parser_version": "1.0.0",
        "normalizer_version": "1.0.0",
        "quality": EvidenceQuality(9_000, ("source-available",)),
        "lineage": EvidenceLineage(
            ToolCallId(f"call-{identifier}"), WorkflowRunId("run-gate"), None
        ),
        "trust": TrustClassification.DIRECT_OBSERVATION,
        "prompt_injection_status": PromptInjectionStatus.NONE,
        "expires_at": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return Evidence(**values)


def artifact(item: Evidence, **overrides: Any) -> Artifact:
    values: dict[str, Any] = {
        "id": item.artifact_id,
        "tenant_id": item.tenant_id,
        "incident_id": item.incident_id,
        "locator": f"local-artifact:v1:{item.artifact_id.value}",
        "media_type": "application/json",
        "content_schema_version": "1.0.0",
        "content_hash": item.content_hash,
        "size_bytes": len(CONTENT),
        "retention_class": RetentionClass.INCIDENT,
        "created_at": NOW - timedelta(minutes=4),
        "expires_at": NOW + timedelta(days=1),
        "redaction_status": RedactionStatus.REDACTED,
        "encrypted": False,
    }
    values.update(overrides)
    return Artifact(**values)


class Reader:
    def __init__(self, values: dict[EvidenceId, Evidence]) -> None:
        self.values = values
        self.calls: list[tuple[EvidenceId, TenantId, IncidentId]] = []

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        self.calls.append((evidence_id, tenant_id, incident_id))
        return self.values.get(evidence_id)


class Storage:
    def __init__(self, values: dict[ArtifactId, ArtifactContent | Exception]) -> None:
        self.values = values

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        raise AssertionError("gate resolution is read-only")

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
        assert at == NOW
        result = self.values[artifact_id]
        if isinstance(result, Exception):
            raise result
        return result


def claim() -> RootCauseEvidenceClaim:
    return RootCauseEvidenceClaim(
        INCIDENT, "candidate-1", (EvidenceId("evidence-1"),), (EvidenceId("evidence-2"),)
    )


@pytest.mark.anyio
async def test_resolver_verifies_every_support_and_counter_reference() -> None:
    first = evidence("evidence-1")
    second = evidence("evidence-2")
    reader = Reader({first.id: first, second.id: second})
    storage = Storage(
        {
            first.artifact_id: ArtifactContent(artifact(first), CONTENT),
            second.artifact_id: ArtifactContent(artifact(second), CONTENT),
        }
    )
    result = await resolve_gate_evidence_references(
        claim(),
        tenant_id=TENANT,
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=storage,
        at=NOW,
    )
    assert result.verified_evidence == (first, second)
    assert result.reasons == ()
    assert reader.calls == [(first.id, TENANT, INCIDENT), (second.id, TENANT, INCIDENT)]


@pytest.mark.anyio
async def test_resolver_reports_missing_and_ownership_substitution_without_artifact_access() -> (
    None
):
    wrong = evidence("different-id", incident_id=IncidentId("other-incident"))
    reader = Reader({EvidenceId("evidence-2"): wrong})
    result = await resolve_gate_evidence_references(
        claim(),
        tenant_id=TENANT,
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=Storage({}),
        at=NOW,
    )
    assert result.verified_evidence == ()
    assert [item.code for item in result.reasons] == [
        EvidenceGateReasonCode.EVIDENCE_NOT_FOUND,
        EvidenceGateReasonCode.INCIDENT_OWNERSHIP_MISMATCH,
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [ArtifactNotFoundError("missing"), None])
async def test_resolver_rejects_missing_or_hash_invalid_artifacts(
    failure: Exception | None,
) -> None:
    first = evidence("evidence-1")
    value: ArtifactContent | Exception = (
        failure if failure is not None else ArtifactContent(artifact(first), b"altered")
    )
    reader = Reader({first.id: first})
    narrowed = RootCauseEvidenceClaim(INCIDENT, "candidate-1", (first.id,))
    result = await resolve_gate_evidence_references(
        narrowed,
        tenant_id=TENANT,
        principal=PRINCIPAL,
        reader=reader,
        artifact_storage=Storage({first.artifact_id: value}),
        at=NOW,
    )
    assert result.verified_evidence == ()
    assert result.reasons[0].code is EvidenceGateReasonCode.ARTIFACT_UNRESOLVABLE


def test_characteristics_accept_fresh_quality_independent_direct_sources() -> None:
    first = evidence("evidence-1")
    second = evidence(
        "evidence-2",
        source_type=EvidenceSourceType.METRIC,
        source_instance="prometheus-primary",
    )
    supporting = RootCauseEvidenceClaim(INCIDENT, "candidate-1", (first.id, second.id))
    assert (
        evaluate_evidence_characteristics(
            supporting, (first, second), rules=EvidenceGateRules(), at=NOW
        )
        == ()
    )


def test_characteristics_reports_time_expiry_quality_availability_and_source_count() -> None:
    stale = evidence(
        "evidence-1",
        observed_from=NOW - timedelta(hours=3),
        observed_to=NOW - timedelta(hours=2),
        collected_at=NOW - timedelta(hours=1, minutes=59),
        expires_at=NOW - timedelta(minutes=1),
        quality=EvidenceQuality(1_000, ("source-unavailable",)),
        trust=TrustClassification.DERIVED_OBSERVATION,
    )
    future = evidence(
        "evidence-2",
        observed_from=NOW + timedelta(minutes=1),
        observed_to=NOW + timedelta(minutes=2),
        collected_at=NOW + timedelta(minutes=3),
        expires_at=NOW + timedelta(days=1),
    )
    supporting = RootCauseEvidenceClaim(INCIDENT, "candidate-1", (stale.id, future.id))
    reasons = evaluate_evidence_characteristics(
        supporting, (stale, future), rules=EvidenceGateRules(), at=NOW
    )
    assert [item.code for item in reasons] == [
        EvidenceGateReasonCode.EVIDENCE_STALE,
        EvidenceGateReasonCode.EVIDENCE_EXPIRED,
        EvidenceGateReasonCode.QUALITY_BELOW_FLOOR,
        EvidenceGateReasonCode.SOURCE_UNAVAILABLE,
        EvidenceGateReasonCode.EVIDENCE_STALE,
        EvidenceGateReasonCode.INSUFFICIENT_INDEPENDENT_SOURCES,
    ]


def test_characteristics_rejects_duplicate_or_uncited_evidence_inputs() -> None:
    first = evidence("evidence-1")
    narrowed = RootCauseEvidenceClaim(INCIDENT, "candidate-1", (first.id,))
    for values in ((first, first), (first, evidence("evidence-2"))):
        with pytest.raises(InvalidDomainValueError, match="unique and cited"):
            evaluate_evidence_characteristics(narrowed, values, rules=EvidenceGateRules(), at=NOW)

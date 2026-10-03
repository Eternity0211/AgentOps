"""Evidence schema, provenance, quality, trust, and Artifact-binding tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    EVIDENCE_SCHEMA_VERSION,
    Artifact,
    ArtifactId,
    ArtifactIntegrityError,
    Evidence,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    IncidentId,
    InvalidDomainValueError,
    NormalizedQuery,
    PromptInjectionStatus,
    QueryParameter,
    RedactionStatus,
    RedactionTransformId,
    RetentionClass,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)

NOW = datetime(2026, 10, 3, 8, tzinfo=UTC)
DIGEST = Sha256Digest(hashlib.sha256(b"payload").hexdigest())


def evidence(**changes: Any) -> Evidence:
    defaults: dict[str, Any] = {
        "id": EvidenceId("evidence-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "source_type": EvidenceSourceType.LOG,
        "source_instance": "loki-primary",
        "tool_name": "query_logs",
        "tool_version": "1.2.0",
        "tool_schema_version": "1.0.0",
        "normalized_query": NormalizedQuery(
            (QueryParameter("service", "order"), QueryParameter("environment", "production"))
        ),
        "observed_from": NOW.astimezone(timezone(timedelta(hours=8))),
        "observed_to": NOW + timedelta(minutes=5),
        "collected_at": NOW + timedelta(minutes=6),
        "artifact_id": ArtifactId("artifact-1"),
        "content_hash": DIGEST,
        "parser_version": "2.0.0",
        "normalizer_version": "1.1.0",
        "quality": EvidenceQuality(8500, ("complete-window", "source-available")),
        "lineage": EvidenceLineage(
            ToolCallId("tool-call-1"),
            WorkflowRunId("workflow-1"),
            RedactionTransformId("redaction-1"),
            (EvidenceId("parent-1"),),
        ),
        "trust": TrustClassification.DIRECT_OBSERVATION,
        "prompt_injection_status": PromptInjectionStatus.NONE,
        "expires_at": NOW + timedelta(days=30),
    }
    defaults.update(changes)
    return Evidence(**defaults)


def artifact(**changes: Any) -> Artifact:
    defaults: dict[str, Any] = {
        "id": ArtifactId("artifact-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "locator": "local-artifact:v1:artifact-1",
        "media_type": "application/json",
        "content_schema_version": "1.0.0",
        "content_hash": DIGEST,
        "size_bytes": 7,
        "retention_class": RetentionClass.INCIDENT,
        "created_at": NOW,
        "expires_at": NOW + timedelta(days=30),
        "redaction_status": RedactionStatus.REDACTED,
        "encrypted": False,
    }
    defaults.update(changes)
    return Artifact(**defaults)


def test_evidence_normalizes_query_and_times_and_binds_artifact() -> None:
    value = evidence()
    assert list(value.normalized_query.as_dict()) == ["environment", "service"]
    assert value.observed_from == NOW
    assert value.schema_version == EVIDENCE_SCHEMA_VERSION
    value.verify_artifact(artifact())
    assert not value.is_expired(at=NOW)
    assert value.is_expired(at=value.expires_at)


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [("Bad Name", "x", "name"), ("ok", "", "query value"), ("ok", "x\n", "control")],
)
def test_query_parameter_rejects_unbounded_or_unsafe_values(
    name: str, value: str, message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        QueryParameter(name, value)


def test_query_parameter_normalizes_name_and_value() -> None:
    assert QueryParameter(" Service ", " order ") == QueryParameter("service", "order")


@pytest.mark.parametrize(
    "parameters",
    [(), tuple(QueryParameter(f"p{i}", "x") for i in range(33))],
)
def test_normalized_query_requires_bounded_parameters(
    parameters: tuple[QueryParameter, ...],
) -> None:
    with pytest.raises(InvalidDomainValueError, match="1-32"):
        NormalizedQuery(parameters)


def test_normalized_query_rejects_duplicate_names() -> None:
    with pytest.raises(InvalidDomainValueError, match="unique"):
        NormalizedQuery((QueryParameter("service", "a"), QueryParameter("service", "b")))


@pytest.mark.parametrize("score", [-1, 10001, True, 1.5])
def test_quality_score_is_integer_basis_points(score: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="basis points"):
        EvidenceQuality(score, ("reason",))


@pytest.mark.parametrize("reasons", [(), tuple(str(i) for i in range(17))])
def test_quality_requires_bounded_reasons(reasons: tuple[str, ...]) -> None:
    with pytest.raises(InvalidDomainValueError, match="1-16"):
        EvidenceQuality(1, reasons)


@pytest.mark.parametrize("reasons", [("",), ("bad\n",), ("same", "same")])
def test_quality_reasons_are_safe_and_unique(reasons: tuple[str, ...]) -> None:
    with pytest.raises(InvalidDomainValueError):
        EvidenceQuality(1, reasons)


def test_lineage_rejects_too_many_or_duplicate_parents() -> None:
    base = (ToolCallId("tool"), WorkflowRunId("run"), None)
    with pytest.raises(InvalidDomainValueError, match="32 parents"):
        EvidenceLineage(*base, tuple(EvidenceId(f"e{i}") for i in range(33)))
    with pytest.raises(InvalidDomainValueError, match="unique"):
        EvidenceLineage(*base, (EvidenceId("e1"), EvidenceId("e1")))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_instance": ""}, "source instance"),
        ({"tool_name": "Bad Tool"}, "tool name"),
        ({"tool_version": "bad version"}, "tool version"),
        ({"tool_schema_version": "bad version"}, "tool schema version"),
        ({"parser_version": "bad version"}, "parser version"),
        ({"normalizer_version": "bad version"}, "normalizer version"),
        ({"schema_version": "2.0.0"}, "schema version"),
        ({"observed_from": NOW + timedelta(minutes=6)}, "range is reversed"),
        ({"collected_at": NOW}, "collection predates"),
        ({"expires_at": NOW + timedelta(minutes=6)}, "expiry must follow"),
    ],
)
def test_evidence_rejects_invalid_contract(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        evidence(**changes)


@pytest.mark.parametrize(
    "changed_artifact",
    [
        artifact(id=ArtifactId("artifact-2"), locator="local-artifact:v1:artifact-2"),
        artifact(tenant_id=TenantId("tenant-2")),
        artifact(incident_id=IncidentId("incident-2")),
        artifact(content_hash=Sha256Digest("0" * 64)),
    ],
)
def test_evidence_rejects_unresolvable_or_substituted_artifact(
    changed_artifact: Artifact,
) -> None:
    with pytest.raises(ArtifactIntegrityError, match="owning Artifact"):
        evidence().verify_artifact(changed_artifact)

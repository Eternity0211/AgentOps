"""Deterministic Evidence normalization and validation tests."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agentops_incident_commander.domain import (
    MAX_NORMALIZATION_DEPTH,
    MAX_NORMALIZATION_NODES,
    ActorId,
    ArtifactContent,
    ArtifactId,
    ArtifactIntegrityError,
    EvidenceBuildRequest,
    EvidenceId,
    EvidenceLineage,
    EvidenceNormalizer,
    EvidenceSourceType,
    EvidenceValidationStatus,
    IncidentId,
    InvalidDomainValueError,
    JsonValue,
    NormalizedQuery,
    Principal,
    PromptInjectionStatus,
    QualitySignals,
    QueryParameter,
    RedactionStatus,
    RedactionTransformId,
    RetentionClass,
    Role,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
    assess_evidence_quality,
    normalize_json_payload,
    resolve_and_validate_evidence,
    validate_evidence_content,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage

NOW = datetime(2026, 10, 3, 8, tzinfo=UTC)


def request(**changes: Any) -> EvidenceBuildRequest:
    values: dict[str, Any] = {
        "evidence_id": EvidenceId("evidence-1"),
        "artifact_id": ArtifactId("artifact-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "source_type": EvidenceSourceType.LOG,
        "source_instance": "loki-primary",
        "tool_name": "query_logs",
        "tool_version": "1.0.0",
        "tool_schema_version": "1.0.0",
        "normalized_query": NormalizedQuery((QueryParameter("service", "order"),)),
        "observed_from": NOW,
        "observed_to": NOW + timedelta(minutes=1),
        "collected_at": NOW + timedelta(minutes=2),
        "expires_at": NOW + timedelta(days=7),
        "artifact_expires_at": NOW + timedelta(days=30),
        "parser_version": "1.0.0",
        "normalizer_version": "1.0.0",
        "quality_signals": QualitySignals(True, True, 2),
        "lineage": EvidenceLineage(
            ToolCallId("tool-call-1"),
            WorkflowRunId("workflow-1"),
            RedactionTransformId("redaction-1"),
        ),
        "trust": TrustClassification.DIRECT_OBSERVATION,
        "prompt_injection_status": PromptInjectionStatus.NONE,
        "retention_class": RetentionClass.INCIDENT,
        "redaction_status": RedactionStatus.REDACTED,
        "encrypted": False,
    }
    values.update(changes)
    return EvidenceBuildRequest(**values)


def test_normalization_is_canonical_unicode_preserving_and_type_stable() -> None:
    first = normalize_json_payload({"z": [True, None, 2, 1.5], "a": "超时"})
    second = normalize_json_payload({"a": "超时", "z": [True, None, 2, 1.5]})
    assert first == second == b'{"a":"\xe8\xb6\x85\xe6\x97\xb6","z":[true,null,2,1.5]}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_normalization_rejects_non_finite_numbers(value: float) -> None:
    with pytest.raises(InvalidDomainValueError, match="non-finite"):
        normalize_json_payload(value)


@pytest.mark.parametrize("payload", [{"": 1}, {1: "value"}])
def test_normalization_rejects_invalid_object_keys(payload: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="keys"):
        normalize_json_payload(payload)


def test_normalization_rejects_unsupported_values() -> None:
    with pytest.raises(InvalidDomainValueError, match="unsupported"):
        normalize_json_payload({"bad": {1, 2}})  # type: ignore[dict-item]


def test_normalization_enforces_depth_and_node_bounds() -> None:
    nested: Any = "leaf"
    for _ in range(MAX_NORMALIZATION_DEPTH + 1):
        nested = [nested]
    with pytest.raises(InvalidDomainValueError, match="depth"):
        normalize_json_payload(nested)
    with pytest.raises(InvalidDomainValueError, match="node"):
        normalize_json_payload([None] * MAX_NORMALIZATION_NODES)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_available": 1},
        {"complete_window": 0},
        {"records_seen": -1},
        {"records_dropped": True},
        {"parser_warning_count": 1.5},
    ],
)
def test_quality_signals_require_typed_nonnegative_facts(changes: dict[str, Any]) -> None:
    values = {
        "source_available": True,
        "complete_window": True,
        "records_seen": 1,
        "records_dropped": 0,
        "parser_warning_count": 0,
    }
    values.update(changes)
    with pytest.raises(InvalidDomainValueError, match="quality"):
        QualitySignals(**values)  # type: ignore[arg-type]


def test_quality_reasons_explain_every_deduction() -> None:
    quality = assess_evidence_quality(
        QualitySignals(False, False, 0, records_dropped=10, parser_warning_count=20),
        PromptInjectionStatus.NONE,
    )
    assert quality.score_basis_points == 0
    assert quality.reasons == (
        "source-unavailable",
        "incomplete-window",
        "no-records",
        "records-dropped",
        "parser-warnings",
    )


def test_quality_handles_small_loss_and_injection_classification() -> None:
    small_loss = assess_evidence_quality(
        QualitySignals(True, True, 1000, records_dropped=1, parser_warning_count=1),
        PromptInjectionStatus.NONE,
    )
    assert small_loss.score_basis_points == 9899
    assert "records-observed" in small_loss.reasons
    suspected = assess_evidence_quality(
        QualitySignals(True, True, 1), PromptInjectionStatus.SUSPECTED
    )
    assert suspected.score_basis_points == 0
    quarantined = assess_evidence_quality(
        QualitySignals(True, True, 1), PromptInjectionStatus.QUARANTINED
    )
    assert quarantined.score_basis_points == 2500


def test_normalizer_builds_reproducible_bound_artifact_and_evidence() -> None:
    payload: JsonValue = {"errors": [{"count": 3, "pattern": "timeout"}]}
    normalized = EvidenceNormalizer().normalize(request(), payload)
    repeated = EvidenceNormalizer().normalize(request(), payload)
    assert normalized == repeated
    assert normalized.artifact.content_hash == Sha256Digest(
        hashlib.sha256(normalized.content).hexdigest()
    )
    assert normalized.evidence.content_hash == normalized.artifact.content_hash
    assert normalized.evidence.quality.reasons == (
        "source-available",
        "complete-window",
        "records-observed",
    )


def test_normalizer_rejects_evidence_that_outlives_artifact() -> None:
    with pytest.raises(InvalidDomainValueError, match="cannot expire before"):
        EvidenceNormalizer().normalize(
            request(artifact_expires_at=NOW + timedelta(days=1)), {"value": 1}
        )


def test_normalizer_requires_suspected_injection_to_be_quarantined() -> None:
    with pytest.raises(InvalidDomainValueError, match="must be quarantined"):
        EvidenceNormalizer().normalize(
            request(prompt_injection_status=PromptInjectionStatus.SUSPECTED), {"value": 1}
        )


def test_resolver_authorizes_store_read_before_validation(tmp_path: Path) -> None:
    normalized = EvidenceNormalizer().normalize(request(), {"value": 1})
    store = LocalArtifactStorage(tmp_path)
    store.store(normalized.artifact, normalized.content)
    principal = Principal(ActorId("viewer"), TenantId("tenant-1"), frozenset({Role.VIEWER}))
    result = resolve_and_validate_evidence(normalized.evidence, store, principal=principal, at=NOW)
    assert result.status is EvidenceValidationStatus.VALID


def test_validation_verifies_content_and_reports_expiry_reasons() -> None:
    normalized = EvidenceNormalizer().normalize(request(), {"value": 1})
    content = ArtifactContent(normalized.artifact, normalized.content)
    valid = validate_evidence_content(normalized.evidence, content, at=NOW)
    assert valid.status is EvidenceValidationStatus.VALID
    assert valid.reasons == ("artifact-content-verified",)

    evidence_expired = validate_evidence_content(
        normalized.evidence, content, at=NOW + timedelta(days=8)
    )
    assert evidence_expired.status is EvidenceValidationStatus.EXPIRED
    assert evidence_expired.reasons == ("artifact-content-verified", "evidence-expired")

    both_expired = validate_evidence_content(
        normalized.evidence, content, at=NOW + timedelta(days=31)
    )
    assert both_expired.reasons == (
        "artifact-content-verified",
        "evidence-expired",
        "artifact-expired",
    )


def test_validation_can_report_artifact_expiry_independently() -> None:
    normalized = EvidenceNormalizer().normalize(request(), {"value": 1})
    long_lived_evidence = replace(normalized.evidence, expires_at=NOW + timedelta(days=60))
    result = validate_evidence_content(
        long_lived_evidence,
        ArtifactContent(normalized.artifact, normalized.content),
        at=NOW + timedelta(days=31),
    )
    assert result.reasons == ("artifact-content-verified", "artifact-expired")


def test_validation_rejects_hash_and_size_tampering() -> None:
    normalized = EvidenceNormalizer().normalize(request(), {"value": 1})
    with pytest.raises(ArtifactIntegrityError, match="hash or size"):
        validate_evidence_content(
            normalized.evidence,
            ArtifactContent(normalized.artifact, b"tampered"),
            at=NOW,
        )
    wrong_size = replace(normalized.artifact, size_bytes=len(normalized.content) + 1)
    with pytest.raises(ArtifactIntegrityError, match="hash or size"):
        validate_evidence_content(
            normalized.evidence,
            ArtifactContent(wrong_size, normalized.content),
            at=NOW,
        )

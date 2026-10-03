"""Deterministic Evidence normalization, quality, and validation services."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .artifacts import (
    Artifact,
    ArtifactContent,
    ArtifactStorage,
    RedactionStatus,
    RetentionClass,
)
from .auth import Principal
from .errors import ArtifactIntegrityError, InvalidDomainValueError
from .evidence import (
    Evidence,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    NormalizedQuery,
    PromptInjectionStatus,
    TrustClassification,
)
from .values import ArtifactId, EvidenceId, IncidentId, Sha256Digest, TenantId, as_utc

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
NORMALIZED_PAYLOAD_SCHEMA_VERSION = "1.0.0"
MAX_NORMALIZATION_DEPTH = 12
MAX_NORMALIZATION_NODES = 10_000


@dataclass(frozen=True, slots=True)
class QualitySignals:
    """Deterministic collector facts used to calculate Evidence quality."""

    source_available: bool
    complete_window: bool
    records_seen: int
    records_dropped: int = 0
    parser_warning_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_available, bool) or not isinstance(
            self.complete_window, bool
        ):
            raise InvalidDomainValueError("quality availability/window signals must be boolean")
        for name, value in (
            ("records seen", self.records_seen),
            ("records dropped", self.records_dropped),
            ("parser warning count", self.parser_warning_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise InvalidDomainValueError(f"quality {name} must be a non-negative integer")


def assess_evidence_quality(
    signals: QualitySignals, injection_status: PromptInjectionStatus
) -> EvidenceQuality:
    """Calculate a bounded score and stable, explainable reason codes."""
    score = 10_000
    reasons: list[str] = []
    if signals.source_available:
        reasons.append("source-available")
    else:
        score -= 5_000
        reasons.append("source-unavailable")
    if signals.complete_window:
        reasons.append("complete-window")
    else:
        score -= 2_500
        reasons.append("incomplete-window")
    if signals.records_seen == 0:
        score -= 2_000
        reasons.append("no-records")
    else:
        reasons.append("records-observed")
    if signals.records_dropped:
        total = signals.records_seen + signals.records_dropped
        score -= max(1, min(2_000, signals.records_dropped * 2_000 // total))
        reasons.append("records-dropped")
    if signals.parser_warning_count:
        score -= min(1_000, signals.parser_warning_count * 100)
        reasons.append("parser-warnings")
    if injection_status is PromptInjectionStatus.SUSPECTED:
        score = 0
        reasons.append("prompt-injection-suspected")
    elif injection_status is PromptInjectionStatus.QUARANTINED:
        score = min(score, 2_500)
        reasons.append("prompt-injection-quarantined")
    return EvidenceQuality(max(0, score), tuple(reasons))


def normalize_json_payload(payload: JsonValue) -> bytes:
    """Return bounded canonical UTF-8 JSON or reject unsafe/non-finite input."""
    node_count = 0

    def visit(value: JsonValue, depth: int) -> JsonValue:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NORMALIZATION_NODES:
            raise InvalidDomainValueError("evidence payload exceeds the normalization node limit")
        if depth > MAX_NORMALIZATION_DEPTH:
            raise InvalidDomainValueError("evidence payload exceeds the normalization depth limit")
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise InvalidDomainValueError("evidence payload cannot contain non-finite numbers")
            return value
        if isinstance(value, list):
            return [visit(item, depth + 1) for item in value]
        if isinstance(value, dict):
            if any(not isinstance(key, str) or not key for key in value):
                raise InvalidDomainValueError(
                    "evidence payload object keys must be non-empty strings"
                )
            return {key: visit(value[key], depth + 1) for key in sorted(value)}
        raise InvalidDomainValueError("evidence payload contains an unsupported value")

    normalized = visit(payload, 0)
    return json.dumps(
        normalized, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class EvidenceBuildRequest:
    evidence_id: EvidenceId
    artifact_id: ArtifactId
    tenant_id: TenantId
    incident_id: IncidentId
    source_type: EvidenceSourceType
    source_instance: str
    tool_name: str
    tool_version: str
    tool_schema_version: str
    normalized_query: NormalizedQuery
    observed_from: datetime
    observed_to: datetime
    collected_at: datetime
    expires_at: datetime
    artifact_expires_at: datetime
    parser_version: str
    normalizer_version: str
    quality_signals: QualitySignals
    lineage: EvidenceLineage
    trust: TrustClassification
    prompt_injection_status: PromptInjectionStatus
    retention_class: RetentionClass = RetentionClass.INCIDENT
    redaction_status: RedactionStatus = RedactionStatus.NOT_REQUIRED
    encrypted: bool = False


@dataclass(frozen=True, slots=True)
class NormalizedEvidence:
    artifact: Artifact
    evidence: Evidence
    content: bytes


class EvidenceNormalizer:
    """Build matching immutable Artifact and Evidence records from JSON-compatible data."""

    def normalize(self, request: EvidenceBuildRequest, payload: JsonValue) -> NormalizedEvidence:
        if request.prompt_injection_status is PromptInjectionStatus.SUSPECTED:
            raise InvalidDomainValueError(
                "suspected prompt injection must be quarantined before Evidence normalization"
            )
        content = normalize_json_payload(payload)
        digest = Sha256Digest(hashlib.sha256(content).hexdigest())
        collected_at = as_utc(request.collected_at)
        evidence_expiry = as_utc(request.expires_at)
        artifact_expiry = as_utc(request.artifact_expires_at)
        if artifact_expiry < evidence_expiry:
            raise InvalidDomainValueError("Artifact cannot expire before its Evidence reference")
        artifact = Artifact(
            id=request.artifact_id,
            tenant_id=request.tenant_id,
            incident_id=request.incident_id,
            locator=f"local-artifact:v1:{request.artifact_id.value}",
            media_type="application/json",
            content_schema_version=NORMALIZED_PAYLOAD_SCHEMA_VERSION,
            content_hash=digest,
            size_bytes=len(content),
            retention_class=request.retention_class,
            created_at=collected_at,
            expires_at=artifact_expiry,
            redaction_status=request.redaction_status,
            encrypted=request.encrypted,
        )
        evidence = Evidence(
            id=request.evidence_id,
            tenant_id=request.tenant_id,
            incident_id=request.incident_id,
            source_type=request.source_type,
            source_instance=request.source_instance,
            tool_name=request.tool_name,
            tool_version=request.tool_version,
            tool_schema_version=request.tool_schema_version,
            normalized_query=request.normalized_query,
            observed_from=request.observed_from,
            observed_to=request.observed_to,
            collected_at=collected_at,
            artifact_id=request.artifact_id,
            content_hash=digest,
            parser_version=request.parser_version,
            normalizer_version=request.normalizer_version,
            quality=assess_evidence_quality(
                request.quality_signals, request.prompt_injection_status
            ),
            lineage=request.lineage,
            trust=request.trust,
            prompt_injection_status=request.prompt_injection_status,
            expires_at=evidence_expiry,
        )
        evidence.verify_artifact(artifact)
        return NormalizedEvidence(artifact, evidence, content)


class EvidenceValidationStatus(StrEnum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True, slots=True)
class EvidenceValidation:
    status: EvidenceValidationStatus
    reasons: tuple[str, ...]


def validate_evidence_content(
    evidence: Evidence, artifact_content: ArtifactContent, *, at: datetime
) -> EvidenceValidation:
    """Resolve ownership/hash/content and deterministically evaluate expiry."""
    evidence.verify_artifact(artifact_content.artifact)
    digest = Sha256Digest(hashlib.sha256(artifact_content.content).hexdigest())
    if (
        digest != evidence.content_hash
        or len(artifact_content.content) != artifact_content.artifact.size_bytes
    ):
        raise ArtifactIntegrityError("Evidence Artifact content failed hash or size verification")
    current = as_utc(at)
    reasons = ["artifact-content-verified"]
    if evidence.is_expired(at=current):
        reasons.append("evidence-expired")
    if artifact_content.artifact.is_expired(at=current):
        reasons.append("artifact-expired")
    status = (
        EvidenceValidationStatus.EXPIRED if len(reasons) > 1 else EvidenceValidationStatus.VALID
    )
    return EvidenceValidation(status, tuple(reasons))


def resolve_and_validate_evidence(
    evidence: Evidence,
    storage: ArtifactStorage,
    *,
    principal: Principal | None,
    at: datetime,
) -> EvidenceValidation:
    """Authorize and resolve the immutable Artifact before validating Evidence."""
    content = storage.retrieve(
        evidence.artifact_id,
        incident_id=evidence.incident_id,
        principal=principal,
        at=at,
    )
    return validate_evidence_content(evidence, content, at=at)

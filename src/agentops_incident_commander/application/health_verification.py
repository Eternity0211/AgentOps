"""Evidence-bound application orchestration for deterministic health verification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from agentops_incident_commander.domain import (
    ActionExecution,
    ArtifactError,
    ArtifactStorage,
    Evidence,
    EvidenceId,
    EvidenceSourceType,
    EvidenceValidationStatus,
    HealthVerificationCriteria,
    HealthVerificationDecision,
    HealthVerificationObservation,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    PromptInjectionStatus,
    TrustClassification,
    as_utc,
    evaluate_health_verification,
    validate_evidence_content,
)

from .evidence_gate import EvidenceReader

HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION: Final = "1.0.0"


class HealthVerificationSignal(StrEnum):
    ERROR_RATE = "ERROR_RATE_BASIS_POINTS"
    P95_LATENCY = "P95_LATENCY_MS"
    HEALTH_ENDPOINT = "HEALTH_ENDPOINT_HEALTHY"
    DEPLOYED_VERSION = "DEPLOYED_VERSION"
    NEW_ALERTS = "NEW_ALERT_COUNT"


class HealthVerificationEvidenceReasonCode(StrEnum):
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    OWNERSHIP_MISMATCH = "OWNERSHIP_MISMATCH"
    ARTIFACT_UNRESOLVABLE = "ARTIFACT_UNRESOLVABLE"
    EVIDENCE_EXPIRED = "EVIDENCE_EXPIRED"
    TRUST_NOT_DIRECT = "TRUST_NOT_DIRECT"
    PROMPT_INJECTION_UNSAFE = "PROMPT_INJECTION_UNSAFE"
    WINDOW_INCOMPLETE = "WINDOW_INCOMPLETE"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"
    QUERY_MISMATCH = "QUERY_MISMATCH"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"


@dataclass(frozen=True, slots=True)
class HealthVerificationEvidenceReason:
    code: HealthVerificationEvidenceReasonCode
    evidence_id: EvidenceId
    signal: HealthVerificationSignal

    def __post_init__(self) -> None:
        if (
            not isinstance(self.code, HealthVerificationEvidenceReasonCode)
            or not isinstance(self.evidence_id, EvidenceId)
            or not isinstance(self.signal, HealthVerificationSignal)
        ):
            raise InvalidDomainValueError("health verification evidence reason is invalid")


@dataclass(frozen=True, slots=True)
class HealthVerificationEvidenceResolution:
    verified_evidence: tuple[Evidence, ...]
    reasons: tuple[HealthVerificationEvidenceReason, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(item, Evidence) for item in self.verified_evidence) or any(
            not isinstance(item, HealthVerificationEvidenceReason) for item in self.reasons
        ):
            raise InvalidDomainValueError("health verification evidence resolution is invalid")
        ids = tuple(item.id for item in self.verified_evidence)
        if len(ids) != len(set(ids)):
            raise InvalidDomainValueError("verified health verification evidence must be unique")

    @property
    def ready(self) -> bool:
        return not self.reasons and len(self.verified_evidence) == len(HealthVerificationSignal)


@dataclass(frozen=True, slots=True)
class EvidenceBoundHealthVerification:
    resolution: HealthVerificationEvidenceResolution
    decision: HealthVerificationDecision | None

    def __post_init__(self) -> None:
        if not isinstance(self.resolution, HealthVerificationEvidenceResolution):
            raise InvalidDomainValueError(
                "evidence-bound health verification resolution is invalid"
            )
        if (self.decision is not None) != self.resolution.ready:
            raise InvalidDomainValueError("health decision requires a complete evidence resolution")


@dataclass(frozen=True, slots=True)
class _SignalContract:
    signal: HealthVerificationSignal
    evidence_id: EvidenceId
    source_type: EvidenceSourceType
    tool_name: str
    query_discriminator: tuple[str, str] | None
    values: tuple[int | bool | str, ...]


async def resolve_health_verification_evidence(
    observation: HealthVerificationObservation,
    *,
    principal: Principal,
    reader: EvidenceReader,
    artifact_storage: ArtifactStorage,
    at: datetime,
) -> HealthVerificationEvidenceResolution:
    """Resolve and compare every observation value with its immutable Artifact series."""

    if not isinstance(observation, HealthVerificationObservation) or not isinstance(
        principal, Principal
    ):
        raise InvalidDomainValueError("health verification resolution inputs are invalid")
    current = as_utc(at)
    verified: list[Evidence] = []
    reasons: list[HealthVerificationEvidenceReason] = []
    for contract in _contracts(observation):
        evidence = await reader.get(
            contract.evidence_id,
            tenant_id=observation.tenant_id,
            incident_id=observation.incident_id,
        )
        if evidence is None:
            reasons.append(
                _reason(contract, HealthVerificationEvidenceReasonCode.EVIDENCE_NOT_FOUND)
            )
            continue
        if (
            evidence.id != contract.evidence_id
            or evidence.tenant_id != observation.tenant_id
            or evidence.incident_id != observation.incident_id
        ):
            reasons.append(
                _reason(contract, HealthVerificationEvidenceReasonCode.OWNERSHIP_MISMATCH)
            )
            continue
        try:
            content = artifact_storage.retrieve(
                evidence.artifact_id,
                incident_id=observation.incident_id,
                principal=principal,
                at=current,
            )
            validation = validate_evidence_content(evidence, content, at=current)
        except ArtifactError:
            reasons.append(
                _reason(contract, HealthVerificationEvidenceReasonCode.ARTIFACT_UNRESOLVABLE)
            )
            continue
        failure = _metadata_failure(evidence, observation, contract, validation.status)
        if failure is None:
            failure = _payload_failure(content.content, observation, contract)
        if failure is not None:
            reasons.append(_reason(contract, failure))
            continue
        verified.append(evidence)
    return HealthVerificationEvidenceResolution(tuple(verified), tuple(reasons))


async def evaluate_evidence_bound_health_verification(
    execution: ActionExecution,
    criteria: HealthVerificationCriteria,
    observation: HealthVerificationObservation,
    *,
    decision_id: OpaqueIdentifier,
    evaluated_at: datetime,
    principal: Principal,
    reader: EvidenceReader,
    artifact_storage: ArtifactStorage,
) -> EvidenceBoundHealthVerification:
    """Evaluate only after all five real Artifact series match the typed observation."""

    resolution = await resolve_health_verification_evidence(
        observation,
        principal=principal,
        reader=reader,
        artifact_storage=artifact_storage,
        at=evaluated_at,
    )
    if not resolution.ready:
        return EvidenceBoundHealthVerification(resolution, None)
    decision = evaluate_health_verification(
        execution,
        criteria,
        observation,
        decision_id=decision_id,
        evaluated_at=evaluated_at,
    )
    return EvidenceBoundHealthVerification(resolution, decision)


def _contracts(observation: HealthVerificationObservation) -> tuple[_SignalContract, ...]:
    samples = observation.samples
    return (
        _SignalContract(
            HealthVerificationSignal.ERROR_RATE,
            observation.error_rate_evidence_id,
            EvidenceSourceType.METRIC,
            "query_metrics",
            ("metric", "http_request_error_rate"),
            tuple(item.error_rate_basis_points for item in samples),
        ),
        _SignalContract(
            HealthVerificationSignal.P95_LATENCY,
            observation.p95_latency_evidence_id,
            EvidenceSourceType.METRIC,
            "query_metrics",
            ("metric", "http_request_duration_p95"),
            tuple(item.p95_latency_ms for item in samples),
        ),
        _SignalContract(
            HealthVerificationSignal.HEALTH_ENDPOINT,
            observation.health_endpoint_evidence_id,
            EvidenceSourceType.TRACE,
            "query_traces",
            ("endpoint", "/healthz"),
            tuple(item.health_endpoint_healthy for item in samples),
        ),
        _SignalContract(
            HealthVerificationSignal.DEPLOYED_VERSION,
            observation.deployed_version_evidence_id,
            EvidenceSourceType.DEPLOYMENT,
            "query_deployments",
            None,
            tuple(item.deployed_version.value for item in samples),
        ),
        _SignalContract(
            HealthVerificationSignal.NEW_ALERTS,
            observation.new_alerts_evidence_id,
            EvidenceSourceType.LOG,
            "query_logs",
            ("record_kind", "alert"),
            tuple(item.new_alert_count for item in samples),
        ),
    )


def _metadata_failure(
    evidence: Evidence,
    observation: HealthVerificationObservation,
    contract: _SignalContract,
    validation_status: EvidenceValidationStatus,
) -> HealthVerificationEvidenceReasonCode | None:
    if validation_status is EvidenceValidationStatus.EXPIRED:
        return HealthVerificationEvidenceReasonCode.EVIDENCE_EXPIRED
    if evidence.trust is not TrustClassification.DIRECT_OBSERVATION:
        return HealthVerificationEvidenceReasonCode.TRUST_NOT_DIRECT
    if evidence.prompt_injection_status is not PromptInjectionStatus.NONE:
        return HealthVerificationEvidenceReasonCode.PROMPT_INJECTION_UNSAFE
    if (
        evidence.observed_from > observation.window_started_at
        or evidence.observed_to < observation.window_ended_at
        or "complete-window" not in evidence.quality.reasons
        or "source-available" not in evidence.quality.reasons
    ):
        return HealthVerificationEvidenceReasonCode.WINDOW_INCOMPLETE
    if evidence.source_type is not contract.source_type or evidence.tool_name != contract.tool_name:
        return HealthVerificationEvidenceReasonCode.SOURCE_MISMATCH
    query = evidence.normalized_query.as_dict()
    required = {
        "environment": observation.environment.value,
        "service": observation.service,
        "start": observation.window_started_at.isoformat(),
        "end": observation.window_ended_at.isoformat(),
    }
    if any(query.get(key) != value for key, value in required.items()) or (
        contract.query_discriminator is not None
        and query.get(contract.query_discriminator[0]) != contract.query_discriminator[1]
    ):
        return HealthVerificationEvidenceReasonCode.QUERY_MISMATCH
    return None


def _payload_failure(
    content: bytes,
    observation: HealthVerificationObservation,
    contract: _SignalContract,
) -> HealthVerificationEvidenceReasonCode | None:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return HealthVerificationEvidenceReasonCode.OBSERVATION_MISMATCH
    expected = {
        "environment": observation.environment.value,
        "kind": "health-verification-signal",
        "samples": [
            {"observed_at": sample.observed_at.isoformat(), "value": value}
            for sample, value in zip(observation.samples, contract.values, strict=True)
        ],
        "schema_version": HEALTH_VERIFICATION_SIGNAL_SCHEMA_VERSION,
        "service": observation.service,
        "signal": contract.signal.value,
        "window_ended_at": observation.window_ended_at.isoformat(),
        "window_started_at": observation.window_started_at.isoformat(),
    }
    if payload != expected:
        return HealthVerificationEvidenceReasonCode.OBSERVATION_MISMATCH
    return None


def _reason(
    contract: _SignalContract, code: HealthVerificationEvidenceReasonCode
) -> HealthVerificationEvidenceReason:
    return HealthVerificationEvidenceReason(code, contract.evidence_id, contract.signal)

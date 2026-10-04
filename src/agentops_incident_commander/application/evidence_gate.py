"""Application orchestration for deterministic Evidence Gate resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ArtifactError,
    ArtifactStorage,
    Evidence,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    Principal,
    RootCauseEvidenceClaim,
    TenantId,
    TrustClassification,
    as_utc,
    validate_evidence_content,
)


class EvidenceReader(Protocol):
    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None: ...


@dataclass(frozen=True, slots=True)
class EvidenceReferenceResolution:
    verified_evidence: tuple[Evidence, ...]
    reasons: tuple[EvidenceGateReason, ...]


def evaluate_evidence_characteristics(
    claim: RootCauseEvidenceClaim,
    evidence: tuple[Evidence, ...],
    *,
    rules: EvidenceGateRules,
    at: datetime,
) -> tuple[EvidenceGateReason, ...]:
    """Evaluate time, expiry, quality, availability, and source independence."""
    current = as_utc(at)
    by_id = {item.id: item for item in evidence}
    if len(by_id) != len(evidence) or not set(by_id) <= set(claim.all_evidence_ids):
        raise InvalidDomainValueError("gate evidence must be unique and cited by the claim")
    reasons: list[EvidenceGateReason] = []
    for item in evidence:
        if item.observed_to > current or current - item.observed_to > rules.maximum_evidence_age:
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.EVIDENCE_STALE,
                    "Evidence observation is outside the configured relevance window.",
                    (item.id,),
                )
            )
        if item.is_expired(at=current):
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.EVIDENCE_EXPIRED,
                    "Evidence expired before gate evaluation.",
                    (item.id,),
                )
            )
        if item.quality.score_basis_points < rules.minimum_quality_basis_points:
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.QUALITY_BELOW_FLOOR,
                    "Evidence quality is below the configured floor.",
                    (item.id,),
                )
            )
        if (
            "source-available" not in item.quality.reasons
            or "source-unavailable" in item.quality.reasons
        ):
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.SOURCE_UNAVAILABLE,
                    "Evidence does not attest that its source was available.",
                    (item.id,),
                )
            )
    supporting = (by_id[item] for item in claim.supporting_evidence_ids if item in by_id)
    independent = {
        (item.source_type, item.source_instance)
        for item in supporting
        if item.trust is TrustClassification.DIRECT_OBSERVATION
    }
    if len(independent) < rules.minimum_independent_sources:
        reasons.append(
            EvidenceGateReason(
                EvidenceGateReasonCode.INSUFFICIENT_INDEPENDENT_SOURCES,
                "Supporting evidence does not meet the independent-source minimum.",
                claim.supporting_evidence_ids,
            )
        )
    return tuple(reasons)


async def resolve_gate_evidence_references(
    claim: RootCauseEvidenceClaim,
    *,
    tenant_id: TenantId,
    principal: Principal,
    reader: EvidenceReader,
    artifact_storage: ArtifactStorage,
    at: datetime,
) -> EvidenceReferenceResolution:
    """Resolve every cited ID and fail closed on ownership or Artifact binding failures."""
    verified: list[Evidence] = []
    reasons: list[EvidenceGateReason] = []
    for evidence_id in claim.all_evidence_ids:
        evidence = await reader.get(
            evidence_id,
            tenant_id=tenant_id,
            incident_id=claim.incident_id,
        )
        if evidence is None:
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.EVIDENCE_NOT_FOUND,
                    "Cited Evidence ID was not found in the owning Incident scope.",
                    (evidence_id,),
                )
            )
            continue
        if (
            evidence.id != evidence_id
            or evidence.tenant_id != tenant_id
            or evidence.incident_id != claim.incident_id
        ):
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.INCIDENT_OWNERSHIP_MISMATCH,
                    "Resolved Evidence does not match the cited tenant or Incident scope.",
                    (evidence_id,),
                )
            )
            continue
        try:
            content = artifact_storage.retrieve(
                evidence.artifact_id,
                incident_id=claim.incident_id,
                principal=principal,
                at=at,
            )
            validate_evidence_content(evidence, content, at=at)
        except ArtifactError:
            reasons.append(
                EvidenceGateReason(
                    EvidenceGateReasonCode.ARTIFACT_UNRESOLVABLE,
                    "Evidence Artifact could not be resolved with a valid immutable binding.",
                    (evidence_id,),
                )
            )
            continue
        verified.append(evidence)
    return EvidenceReferenceResolution(tuple(verified), tuple(reasons))

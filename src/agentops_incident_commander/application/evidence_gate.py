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
    EvidenceId,
    IncidentId,
    Principal,
    RootCauseEvidenceClaim,
    TenantId,
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

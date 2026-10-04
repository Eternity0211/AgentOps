"""Application orchestration for deterministic Evidence Gate resolution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ArtifactError,
    ArtifactStorage,
    Evidence,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    Principal,
    RootCauseEvidenceClaim,
    Sha256Digest,
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


def evaluate_evidence_gate(
    claim: RootCauseEvidenceClaim,
    resolution: EvidenceReferenceResolution,
    *,
    rules: EvidenceGateRules,
    at: datetime,
) -> EvidenceGateDecision:
    """Produce a deterministic decision from resolved evidence and versioned rules."""
    current = as_utc(at)
    reasons = [
        *resolution.reasons,
        *evaluate_evidence_characteristics(
            claim,
            resolution.verified_evidence,
            rules=rules,
            at=current,
        ),
    ]
    if (
        claim.counter_evidence_ids
        and rules.require_counter_evidence_resolution
        and not claim.counter_evidence_resolved
    ):
        reasons.append(
            EvidenceGateReason(
                EvidenceGateReasonCode.UNRESOLVED_COUNTER_EVIDENCE,
                "Material counter-evidence has not been explicitly resolved.",
                claim.counter_evidence_ids,
            )
        )
    if claim.missing_evidence and rules.fail_on_declared_missing_evidence:
        reasons.append(
            EvidenceGateReason(
                EvidenceGateReasonCode.MISSING_EVIDENCE_DECLARED,
                "The candidate declares evidence still required for a safe conclusion.",
            )
        )
    return EvidenceGateDecision(
        incident_id=claim.incident_id,
        candidate_id=claim.candidate_id,
        outcome=EvidenceGateOutcome.FAIL if reasons else EvidenceGateOutcome.PASS,
        reasons=tuple(reasons),
        evaluated_evidence_ids=tuple(item.id for item in resolution.verified_evidence),
        rules_version=rules.version,
        input_fingerprint=evidence_gate_input_fingerprint(
            claim,
            resolution.verified_evidence,
            rules=rules,
            evaluated_at=current,
        ),
        evaluated_at=current,
        model_confidence_basis_points=claim.model_confidence_basis_points,
    )


def evidence_gate_input_snapshot(
    claim: RootCauseEvidenceClaim,
    evidence: tuple[Evidence, ...],
    *,
    rules: EvidenceGateRules,
    evaluated_at: datetime,
) -> dict[str, object]:
    """Return the canonical, non-secret inputs needed to reproduce a gate decision."""
    current = as_utc(evaluated_at)
    return {
        "claim": {
            "candidate_id": claim.candidate_id,
            "counter_evidence_ids": [item.value for item in claim.counter_evidence_ids],
            "counter_evidence_resolved": claim.counter_evidence_resolved,
            "incident_id": claim.incident_id.value,
            "missing_evidence": list(claim.missing_evidence),
            "model_confidence_basis_points": claim.model_confidence_basis_points,
            "supporting_evidence_ids": [item.value for item in claim.supporting_evidence_ids],
        },
        "evaluated_at": current.isoformat(),
        "evidence": [
            {
                "content_hash": item.content_hash.value,
                "expires_at": item.expires_at.isoformat(),
                "id": item.id.value,
                "observed_from": item.observed_from.isoformat(),
                "observed_to": item.observed_to.isoformat(),
                "quality_reasons": list(item.quality.reasons),
                "quality_score_basis_points": item.quality.score_basis_points,
                "source_instance": item.source_instance,
                "source_type": item.source_type.value,
                "trust": item.trust.value,
            }
            for item in sorted(evidence, key=lambda value: value.id.value)
        ],
        "rules": {
            "fail_on_declared_missing_evidence": rules.fail_on_declared_missing_evidence,
            "maximum_evidence_age_seconds": int(rules.maximum_evidence_age.total_seconds()),
            "minimum_independent_sources": rules.minimum_independent_sources,
            "minimum_quality_basis_points": rules.minimum_quality_basis_points,
            "require_counter_evidence_resolution": rules.require_counter_evidence_resolution,
            "schema_version": rules.schema_version,
            "version": rules.version,
        },
    }


def evidence_gate_decision_fingerprint(decision: EvidenceGateDecision) -> Sha256Digest:
    """Hash the complete immutable decision for audit result binding."""
    document = {
        "candidate_id": decision.candidate_id,
        "evaluated_at": decision.evaluated_at.isoformat(),
        "evaluated_evidence_ids": [item.value for item in decision.evaluated_evidence_ids],
        "incident_id": decision.incident_id.value,
        "input_fingerprint": decision.input_fingerprint.value,
        "model_confidence_basis_points": decision.model_confidence_basis_points,
        "outcome": decision.outcome.value,
        "reasons": [
            {
                "code": reason.code.value,
                "detail": reason.detail,
                "evidence_ids": [item.value for item in reason.evidence_ids],
            }
            for reason in decision.reasons
        ],
        "rules_version": decision.rules_version,
        "schema_version": decision.schema_version,
    }
    return _canonical_sha256(document)


def evidence_gate_input_fingerprint(
    claim: RootCauseEvidenceClaim,
    evidence: tuple[Evidence, ...],
    *,
    rules: EvidenceGateRules,
    evaluated_at: datetime,
) -> Sha256Digest:
    document = evidence_gate_input_snapshot(
        claim,
        evidence,
        rules=rules,
        evaluated_at=evaluated_at,
    )
    return _canonical_sha256(document)


def _canonical_sha256(document: object) -> Sha256Digest:
    canonical = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return Sha256Digest(hashlib.sha256(canonical.encode("utf-8")).hexdigest())


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

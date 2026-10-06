"""Deterministic Evidence Gate admission for Remediation Agent proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentops_incident_commander.domain import (
    EvidenceGateDecision,
    EvidenceGateOutcome,
    IncidentId,
    InvalidDomainValueError,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.workflows import RemediationProposal

from .evidence_gate import evidence_gate_decision_fingerprint


class RemediationEvidenceGateStore(Protocol):
    async def get(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        candidate_id: str,
        input_fingerprint: Sha256Digest,
    ) -> EvidenceGateDecision | None: ...


@dataclass(frozen=True, slots=True)
class EvidenceBoundRemediationProposal:
    tenant_id: TenantId
    proposal: RemediationProposal
    evidence_gate_decision: EvidenceGateDecision


class RemediationEvidenceGate:
    """Resolve and verify the immutable passing decision before remediation continues."""

    def __init__(self, store: RemediationEvidenceGateStore) -> None:
        self._store = store

    async def admit(
        self,
        proposal: RemediationProposal,
        *,
        tenant_id: TenantId,
    ) -> EvidenceBoundRemediationProposal:
        if not isinstance(proposal, RemediationProposal) or not isinstance(tenant_id, TenantId):
            raise InvalidDomainValueError("remediation evidence admission scope is invalid")
        incident_id = IncidentId(proposal.incident_id)
        input_fingerprint = Sha256Digest(proposal.evidence_gate_input_fingerprint)
        decision = await self._store.get(
            tenant_id=tenant_id,
            incident_id=incident_id,
            candidate_id=proposal.candidate_id,
            input_fingerprint=input_fingerprint,
        )
        if decision is None:
            raise InvalidDomainValueError(
                "remediation requires a stored passing Evidence Gate decision"
            )
        expected_scope = (incident_id, proposal.candidate_id, input_fingerprint)
        actual_scope = (
            decision.incident_id,
            decision.candidate_id,
            decision.input_fingerprint,
        )
        if actual_scope != expected_scope:
            raise InvalidDomainValueError(
                "stored Evidence Gate decision does not match the remediation proposal"
            )
        if decision.outcome is not EvidenceGateOutcome.PASS:
            raise InvalidDomainValueError(
                "remediation requires a stored passing Evidence Gate decision"
            )
        expected_decision_fingerprint = evidence_gate_decision_fingerprint(decision)
        if expected_decision_fingerprint.value != proposal.evidence_gate_decision_fingerprint:
            raise InvalidDomainValueError(
                "stored Evidence Gate decision fingerprint does not match the proposal"
            )
        return EvidenceBoundRemediationProposal(tenant_id, proposal, decision)

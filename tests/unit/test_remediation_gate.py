"""Remediation requires an exact immutable passing Evidence Gate decision."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    RemediationEvidenceGate,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.workflows import (
    REMEDIATION_PROPOSAL_SCHEMA_VERSION,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
TENANT = TenantId("tenant-remediation")
INCIDENT = IncidentId("incident-remediation")
INPUT_FINGERPRINT = Sha256Digest("a" * 64)


def decision(*, passing: bool = True, **overrides: Any) -> EvidenceGateDecision:
    values: dict[str, object] = {
        "incident_id": INCIDENT,
        "candidate_id": "candidate-deployment",
        "outcome": EvidenceGateOutcome.PASS if passing else EvidenceGateOutcome.FAIL,
        "reasons": (
            ()
            if passing
            else (
                EvidenceGateReason(
                    EvidenceGateReasonCode.MISSING_EVIDENCE_DECLARED,
                    "Deployment evidence is missing.",
                ),
            )
        ),
        "evaluated_evidence_ids": (
            EvidenceId("evidence-deployment"),
            EvidenceId("evidence-current-version"),
        ),
        "rules_version": "1.1.0",
        "input_fingerprint": INPUT_FINGERPRINT,
        "evaluated_at": NOW,
    }
    values.update(overrides)
    return EvidenceGateDecision(**cast(Any, values))


def proposal(bound_decision: EvidenceGateDecision, **overrides: Any) -> RemediationProposal:
    values: dict[str, object] = {
        "schema_version": REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": "remediation-1",
        "proposal_version": 1,
        "incident_id": INCIDENT.value,
        "candidate_id": "candidate-deployment",
        "evidence_gate_input_fingerprint": bound_decision.input_fingerprint.value,
        "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(
            bound_decision
        ).value,
        "action": RecoveryAction.ROLLBACK_SERVICE,
        "parameters": RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-deployment",
        ),
        "prerequisites": RollbackPrerequisites(
            current_version_evidence_id="evidence-current-version"
        ),
        "verification_conditions": RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        "failure_handling": RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ),
        "risk_assumptions": ("The deployment Evidence identifies the active faulty version.",),
    }
    values.update(overrides)
    return RemediationProposal.model_validate(values)


class Store:
    def __init__(self, value: EvidenceGateDecision | None) -> None:
        self.value = value
        self.calls: list[tuple[TenantId, IncidentId, str, Sha256Digest]] = []

    async def get(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        candidate_id: str,
        input_fingerprint: Sha256Digest,
    ) -> EvidenceGateDecision | None:
        self.calls.append((tenant_id, incident_id, candidate_id, input_fingerprint))
        return self.value


@pytest.mark.anyio
async def test_exact_stored_passing_decision_admits_bound_proposal() -> None:
    stored = decision()
    candidate = proposal(stored)
    store = Store(stored)
    admitted = await RemediationEvidenceGate(store).admit(candidate, tenant_id=TENANT)
    assert admitted.tenant_id == TENANT
    assert admitted.proposal == candidate
    assert admitted.evidence_gate_decision == stored
    assert store.calls == [(TENANT, INCIDENT, stored.candidate_id, stored.input_fingerprint)]


@pytest.mark.anyio
async def test_missing_or_failed_decision_refuses_even_with_high_model_confidence() -> None:
    passing = decision()
    candidate = proposal(passing)
    for stored in (None, decision(passing=False, model_confidence_basis_points=10_000)):
        with pytest.raises(InvalidDomainValueError, match="stored passing"):
            await RemediationEvidenceGate(Store(stored)).admit(candidate, tenant_id=TENANT)


@pytest.mark.anyio
async def test_mismatched_stored_scope_or_decision_fingerprint_fails_closed() -> None:
    passing = decision()
    candidate = proposal(passing)
    mismatches = (
        replace(passing, incident_id=IncidentId("incident-other")),
        replace(passing, candidate_id="candidate-other"),
        replace(passing, input_fingerprint=Sha256Digest("b" * 64)),
    )
    for stored in mismatches:
        with pytest.raises(InvalidDomainValueError, match="does not match"):
            await RemediationEvidenceGate(Store(stored)).admit(candidate, tenant_id=TENANT)

    forged = proposal(passing, evidence_gate_decision_fingerprint="f" * 64)
    with pytest.raises(InvalidDomainValueError, match="fingerprint"):
        await RemediationEvidenceGate(Store(passing)).admit(forged, tenant_id=TENANT)


@pytest.mark.anyio
async def test_invalid_admission_types_fail_before_storage_access() -> None:
    stored = decision()
    store = Store(stored)
    gate = RemediationEvidenceGate(store)
    with pytest.raises(InvalidDomainValueError, match="scope"):
        await gate.admit(cast(RemediationProposal, object()), tenant_id=TENANT)
    with pytest.raises(InvalidDomainValueError, match="scope"):
        await gate.admit(proposal(stored), tenant_id=cast(TenantId, "tenant"))
    assert store.calls == []

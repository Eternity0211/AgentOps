"""Single deterministic route from authorized rollback execution to verified outcome."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    CausationId,
    CorrelationId,
    HealthVerificationDecision,
    HealthVerificationOutcome,
    Incident,
    IncidentId,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyDecision,
    PolicyEvaluationInput,
    Principal,
    RollbackServiceRequest,
)
from agentops_incident_commander.workflows import RemediationProposal


class RollbackRecoveryOutcome(StrEnum):
    """Closed result set for one deterministic rollback recovery attempt."""

    EXECUTION_NOT_SUCCEEDED = "EXECUTION_NOT_SUCCEEDED"
    CLOSED = "CLOSED"
    REDIAGNOSE = "REDIAGNOSE"
    NEEDS_HUMAN = "NEEDS_HUMAN"


@dataclass(frozen=True, slots=True)
class RollbackRecoveryResult:
    """Observable result without treating mutation success as service recovery."""

    execution: ActionExecution
    outcome: RollbackRecoveryOutcome
    verification: HealthVerificationDecision | None = None
    incident: Incident | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ActionExecution) or not isinstance(
            self.outcome, RollbackRecoveryOutcome
        ):
            raise InvalidDomainValueError("rollback recovery result is invalid")
        if self.outcome is RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED:
            if (
                self.execution.status is ActionExecutionStatus.SUCCEEDED
                or self.verification is not None
                or self.incident is not None
            ):
                raise InvalidDomainValueError("non-successful execution result is inconsistent")
            return
        if (
            self.execution.status is not ActionExecutionStatus.SUCCEEDED
            or not isinstance(self.verification, HealthVerificationDecision)
            or not isinstance(self.incident, Incident)
        ):
            raise InvalidDomainValueError("verified rollback recovery result is incomplete")
        expected = {
            RollbackRecoveryOutcome.CLOSED: (
                HealthVerificationOutcome.PASS,
                IncidentState.CLOSED,
            ),
            RollbackRecoveryOutcome.REDIAGNOSE: (
                HealthVerificationOutcome.FAIL,
                IncidentState.INVESTIGATING,
            ),
            RollbackRecoveryOutcome.NEEDS_HUMAN: (
                HealthVerificationOutcome.FAIL,
                IncidentState.NEEDS_HUMAN,
            ),
        }[self.outcome]
        if (self.verification.outcome, self.incident.state) != expected:
            raise InvalidDomainValueError("verified rollback recovery outcome is inconsistent")


class RollbackExecutor(Protocol):
    async def execute(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> ActionExecution: ...


class PersistedRollbackHealthVerifier(Protocol):
    async def verify(
        self,
        execution: ActionExecution,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> HealthVerificationDecision: ...


class PassingVerificationRouter(Protocol):
    async def close(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident: ...


class FailingVerificationRouter(Protocol):
    async def route(
        self,
        decision_id: OpaqueIdentifier,
        incident_id: IncidentId,
        proposal: RemediationProposal,
        *,
        used_rediagnosis_attempts: int,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> Incident: ...


class RollbackRecoveryCoordinator:
    """Execute once, verify deterministically, then select exactly one safe route."""

    def __init__(
        self,
        executor: RollbackExecutor,
        verifier: PersistedRollbackHealthVerifier,
        success_router: PassingVerificationRouter,
        failure_router: FailingVerificationRouter,
    ) -> None:
        self._executor = executor
        self._verifier = verifier
        self._success_router = success_router
        self._failure_router = failure_router

    async def recover(
        self,
        request: RollbackServiceRequest,
        proposal: RemediationProposal,
        policy_input: PolicyEvaluationInput,
        policy_decision: PolicyDecision,
        *,
        used_rediagnosis_attempts: int,
        principal: Principal | None,
        correlation_id: CorrelationId,
        causation_id: CausationId,
    ) -> RollbackRecoveryResult:
        if (
            not isinstance(request, RollbackServiceRequest)
            or not isinstance(proposal, RemediationProposal)
            or not isinstance(policy_input, PolicyEvaluationInput)
            or not isinstance(policy_decision, PolicyDecision)
            or not isinstance(correlation_id, CorrelationId)
            or not isinstance(causation_id, CausationId)
            or not isinstance(used_rediagnosis_attempts, int)
            or isinstance(used_rediagnosis_attempts, bool)
            or used_rediagnosis_attempts < 0
        ):
            raise InvalidDomainValueError("rollback recovery inputs are invalid")
        execution = await self._executor.execute(
            request,
            proposal,
            policy_input,
            policy_decision,
            principal=principal,
            correlation_id=correlation_id,
            causation_id=causation_id,
        )
        if not isinstance(execution, ActionExecution):
            raise InvalidDomainValueError("rollback executor returned an invalid result")
        if (
            execution.tenant_id != policy_input.tenant_id
            or execution.incident_id != request.incident_id
            or execution.approval_id != request.approval_id
            or execution.idempotency_key != request.idempotency_key
            or proposal.incident_id != request.incident_id.value
            or policy_input.incident_id != request.incident_id
            or execution.proposal_fingerprint != proposal.fingerprint
            or policy_decision.input_fingerprint != policy_input.fingerprint
            or policy_decision.proposal_fingerprint != proposal.fingerprint
            or execution.policy_decision_fingerprint != policy_decision.fingerprint
        ):
            raise InvalidDomainValueError("rollback execution authority scope is inconsistent")
        if execution.status is not ActionExecutionStatus.SUCCEEDED:
            return RollbackRecoveryResult(
                execution,
                RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED,
            )
        decision = await self._verifier.verify(
            execution,
            principal=principal,
            correlation_id=correlation_id,
        )
        if not isinstance(decision, HealthVerificationDecision) or (
            decision.tenant_id != execution.tenant_id
            or decision.incident_id != execution.incident_id
            or decision.action_execution_id != execution.id
            or decision.execution_fingerprint != execution.fingerprint
        ):
            raise InvalidDomainValueError("health verification does not bind the execution")
        if decision.outcome is HealthVerificationOutcome.PASS:
            incident = await self._success_router.close(
                decision.id,
                execution.incident_id,
                principal=principal,
                correlation_id=correlation_id,
            )
            outcome = RollbackRecoveryOutcome.CLOSED
        else:
            incident = await self._failure_router.route(
                decision.id,
                execution.incident_id,
                proposal,
                used_rediagnosis_attempts=used_rediagnosis_attempts,
                principal=principal,
                correlation_id=correlation_id,
            )
            if not isinstance(incident, Incident):
                raise InvalidDomainValueError("verification failure router returned invalid result")
            if incident.state is IncidentState.INVESTIGATING:
                outcome = RollbackRecoveryOutcome.REDIAGNOSE
            elif incident.state is IncidentState.NEEDS_HUMAN:
                outcome = RollbackRecoveryOutcome.NEEDS_HUMAN
            else:
                raise InvalidDomainValueError(
                    "verification failure router returned an unsafe Incident state"
                )
        if not isinstance(incident, Incident):
            raise InvalidDomainValueError("health verification router returned invalid result")
        if incident.tenant_id != execution.tenant_id or incident.id != execution.incident_id:
            raise InvalidDomainValueError("health verification route changed Incident scope")
        return RollbackRecoveryResult(execution, outcome, decision, incident)

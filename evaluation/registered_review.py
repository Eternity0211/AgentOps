"""Compose registered remediation and a committed SQL human review request."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import ApprovalLifecycleManager, PolicyRules
from agentops_incident_commander.application.remediation_gate import (
    EvidenceBoundRemediationProposal,
)
from agentops_incident_commander.domain import (
    ActorId,
    Approval,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    EvidenceGateDecision,
    OpaqueIdentifier,
    PolicyDecision,
    PolicyEvaluationInput,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    ApprovalLifecycleRepository,
    AuditRepository,
    EvidenceGateRepository,
)
from evaluation.registered_model import RegisteredModelInvoker
from evaluation.registered_remediation import (
    propose_registered_remediation,
    request_remediation_review,
)


async def propose_and_request_sql_review(
    sessions: async_sessionmaker[AsyncSession],
    invoker: RegisteredModelInvoker,
    gate: EvidenceGateDecision,
    context: dict[str, Any],
    policy_input: Callable[[EvidenceBoundRemediationProposal], PolicyEvaluationInput],
    rules: PolicyRules,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[EvidenceBoundRemediationProposal, PolicyDecision, Approval | None]:
    """Server owns Policy inputs; provider work never holds a SQL transaction.

    A successful result is only a PENDING review request. No approver identity, executor,
    health verifier or Incident-close capability is provided to this composition.
    """

    class GateReader:
        async def get(self, **scope: Any) -> EvidenceGateDecision | None:
            async with sessions() as session:
                return await EvidenceGateRepository(session).get(**scope)

    admitted = await propose_registered_remediation(invoker, GateReader(), gate, context)
    value = policy_input(admitted)
    async with sessions.begin() as session:
        policy, approval = await request_remediation_review(
            admitted,
            value,
            rules=rules,
            decision_id=OpaqueIdentifier(f"lab-policy-{uuid4().hex}"),
            evaluated_at=clock(),
            approvals=ApprovalLifecycleManager(
                ApprovalLifecycleRepository(session),
                clock=clock,
                approval_id_factory=lambda: f"lab-review-{uuid4().hex}",
                audit_id_factory=lambda: f"lab-review-audit-{uuid4().hex}",
                expiry_actor_id=ActorId("lab-approval-expiry-worker"),
            ),
            principal=invoker.principal,
            correlation_id=invoker.correlation,
            causation_id=invoker.causation,
        )
        await AuditRepository(session).append(
            AuditEvent(
                id=AuditEventId(f"lab-policy-audit-{uuid4().hex}"),
                tenant_id=invoker.principal.tenant_id,
                type=f"evaluation.policy_{policy.outcome.value.lower()}",
                event_version=1,
                payload_schema_version="policy/v1",
                actor_id=invoker.principal.actor_id,
                correlation_id=invoker.correlation,
                causation_id=invoker.causation,
                target=AuditTarget("evaluation.policy", policy.id),
                occurred_at=policy.evaluated_at,
                request_hash=value.fingerprint,
                result_hash=policy.fingerprint,
            )
        )
    return admitted, policy, approval

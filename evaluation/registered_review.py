"""Compose registered remediation and a committed SQL human review request."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
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
    Permission,
    PolicyDecision,
    PolicyEvaluationInput,
    Sha256Digest,
    require_permission,
)
from agentops_incident_commander.infrastructure.persistence.models import EvidenceGateDecisionRow
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
from evaluation.rollback_roles import rollback_roles, validate_rollback_roles
from evaluation.structured_model import fingerprint


async def propose_and_request_sql_review(
    sessions: async_sessionmaker[AsyncSession],
    invoker: RegisteredModelInvoker,
    gate: EvidenceGateDecision,
    context: dict[str, Any],
    policy_input: Callable[[EvidenceBoundRemediationProposal], PolicyEvaluationInput],
    rules: PolicyRules,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    before_policy: Callable[[], Awaitable[None]] | None = None,
) -> tuple[EvidenceBoundRemediationProposal, PolicyDecision, Approval | None]:
    """Server owns Policy inputs; provider work never holds a SQL transaction.

    A successful result is only a PENDING review request. No approver identity, executor,
    health verifier or Incident-close capability is provided to this composition.
    """

    class GateReader:
        async def get(self, **scope: Any) -> EvidenceGateDecision | None:
            async with sessions() as session:
                return await EvidenceGateRepository(session).get(**scope)

    require_permission(
        invoker.principal, Permission.REMEDIATION_REQUEST, tenant_id=invoker.principal.tenant_id
    )

    async def refuse(reason: str) -> None:
        async with sessions.begin() as session:
            await AuditRepository(session).append(
                AuditEvent(
                    id=AuditEventId(f"rollback-role-audit-{uuid4().hex}"),
                    tenant_id=invoker.principal.tenant_id,
                    type="evaluation.rollback_evidence_refused",
                    event_version=1,
                    payload_schema_version="rollback_roles/v1",
                    actor_id=invoker.principal.actor_id,
                    correlation_id=invoker.correlation,
                    causation_id=invoker.causation,
                    target=AuditTarget(
                        "evidence.gate_decision", OpaqueIdentifier(gate.input_fingerprint.value)
                    ),
                    occurred_at=clock(),
                    request_hash=gate.input_fingerprint,
                    result_hash=Sha256Digest(fingerprint(reason)),
                )
            )
        raise ValueError(reason)

    async with sessions() as session:
        stored = await EvidenceGateRepository(session).get(
            tenant_id=invoker.principal.tenant_id,
            incident_id=invoker.incident,
            candidate_id=gate.candidate_id,
            input_fingerprint=gate.input_fingerprint,
        )
        row = await session.scalar(
            select(EvidenceGateDecisionRow).where(
                EvidenceGateDecisionRow.tenant_id == invoker.principal.tenant_id.value,
                EvidenceGateDecisionRow.incident_id == invoker.incident.value,
                EvidenceGateDecisionRow.candidate_id == gate.candidate_id,
                EvidenceGateDecisionRow.input_fingerprint == gate.input_fingerprint.value,
            )
        )
        if (
            stored != gate
            or row is None
            or fingerprint(row.input_snapshot) != gate.input_fingerprint.value
        ):
            raise ValueError("ROLLBACK_GATE_SNAPSHOT_BINDING_INVALID")
        roles = rollback_roles(row.input_snapshot)
    introducing = [identifier for identifier, role in roles.items() if role == "DEPLOYMENT"]
    current = [identifier for identifier, role in roles.items() if role in {"METRIC", "DEPLOYMENT"}]
    if not any(a != b for a in introducing for b in current):
        await refuse("ROLLBACK_DISTINCT_VERSION_EVIDENCE_REQUIRED")
    bound_context = {
        **context,
        "allowed_introducing_deployment_evidence_ids": introducing,
        "allowed_current_version_evidence_ids": current,
    }
    admitted = await propose_registered_remediation(invoker, GateReader(), gate, bound_context)
    try:
        validate_rollback_roles(admitted.proposal, roles)
    except ValueError as error:
        await refuse(str(error))
    value = policy_input(admitted)
    if before_policy is not None:
        await before_policy()
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

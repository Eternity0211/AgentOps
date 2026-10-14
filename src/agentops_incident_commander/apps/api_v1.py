"""Versioned tenant-scoped HTTP contracts for incidents and audit history."""

import base64
import hashlib
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    ApprovalLifecycleManager,
    ApprovalReviewSnapshot,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    ArtifactExpiredError,
    ArtifactId,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStorage,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    AuthenticationError,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    EvidenceGateDecision,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    Permission,
    Principal,
    Sha256Digest,
    as_utc,
    require_authenticated,
    require_permission,
    utc_now,
)
from agentops_incident_commander.infrastructure.persistence.diagnosis_progress import (
    diagnosis_progress_from_row,
)
from agentops_incident_commander.infrastructure.persistence.models import (
    ApprovalInvalidationRow,
    ApprovalRow,
    AuditEventRow,
    DiagnosisProgressRow,
    EvidenceRow,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentRow,
    IncidentTransitionRow,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    ApprovalLifecycleRepository,
    AuditRepository,
    DiagnosisReportRepository,
    IncidentRepository,
)
from agentops_incident_commander.workflows import DiagnosisReportRecord, RemediationProposal

from .api_errors import common_error_responses, problem

PrincipalResolver = Callable[[Request], Awaitable[Principal | None]]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
SessionFactory = async_sessionmaker[AsyncSession]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentView(ApiModel):
    id: str
    service: str
    severity: str
    state: str
    version: int
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_requested_at: datetime | None


class SessionView(ApiModel):
    actor_id: str
    tenant_id: str
    roles: list[str]
    permissions: list[str]


class IncidentPage(ApiModel):
    items: list[IncidentView]
    next_cursor: str | None


class EvidenceView(ApiModel):
    id: str
    incident_id: str
    source_type: str
    source_instance: str
    tool_name: str
    tool_version: str
    tool_schema_version: str
    normalized_query: dict[str, str]
    observed_from: datetime
    observed_to: datetime
    collected_at: datetime
    artifact_id: str
    content_hash: str
    parser_version: str
    normalizer_version: str
    quality_score_basis_points: int
    quality_reasons: list[str]
    tool_call_id: str
    workflow_run_id: str
    redaction_transform_id: str | None
    parent_evidence_ids: list[str]
    trust: str
    prompt_injection_status: str
    expires_at: datetime
    expired: bool
    schema_version: str


class EvidencePage(ApiModel):
    items: list[EvidenceView]
    next_cursor: str | None


class TimelineEventView(ApiModel):
    kind: Literal["transition", "cancellation_request"]
    prior_version: int
    new_version: int
    actor_id: str
    reason: str
    correlation_id: str
    causation_id: str
    occurred_at: datetime
    prior_state: str | None = None
    new_state: str | None = None
    state_when_requested: str | None = None
    disposition: str | None = None


class TimelinePage(ApiModel):
    items: list[TimelineEventView]
    next_cursor: str | None


class BudgetCounterView(ApiModel):
    used: int
    maximum: int
    remaining: int


class InvestigationBudgetsView(ApiModel):
    steps: BudgetCounterView
    replans: BudgetCounterView
    tool_calls: BudgetCounterView
    model_calls: BudgetCounterView
    tokens: BudgetCounterView
    cost_nanounits: BudgetCounterView


class InvestigationStepView(ApiModel):
    position: int
    step_id: str
    objective: str
    expected_source: str
    depends_on: list[str]
    parallel_group: int
    tool_call_id: str
    tool_name: str
    tool_version: str
    status: str
    failure_code: str | None
    started_at: datetime | None
    completed_at: datetime | None


class InvestigationPlanView(ApiModel):
    attempt: int
    plan_id: str
    summary: str
    model_call_id: str
    created_at: datetime
    steps: list[InvestigationStepView]


class ReplanView(ApiModel):
    completed_attempt: int
    next_attempt: int
    decision_fingerprint: str
    reason_code: str
    occurred_at: datetime


class InvestigationProgressView(ApiModel):
    schema_version: str
    workflow_run_id: str
    graph_version: str
    phase: str
    status: str
    budgets: InvestigationBudgetsView
    plans: list[InvestigationPlanView]
    replans: list[ReplanView]
    checkpoint_sequence: int
    error_code: str | None
    updated_at: datetime


class InvestigationProgressEnvelope(ApiModel):
    run: InvestigationProgressView | None


class EvidenceGateReasonView(ApiModel):
    code: str
    detail: str
    evidence_ids: list[str]


class EvidenceGateDecisionView(ApiModel):
    outcome: str
    reasons: list[EvidenceGateReasonView]
    evaluated_evidence_ids: list[str]
    rules_version: str
    input_fingerprint: str
    decision_fingerprint: str
    evaluated_at: datetime
    model_confidence_basis_points: int | None
    schema_version: str


class RootCauseCandidateView(ApiModel):
    candidate_id: str
    rank: int
    statement: str
    supporting_evidence_ids: list[str]
    counter_evidence_ids: list[str]
    counter_evidence_treatment: str
    counter_evidence_explanation: str | None
    missing_evidence: list[str]
    uncertainty: str
    confidence_basis_points: int
    gate: EvidenceGateDecisionView | None


class DiagnosisResultView(ApiModel):
    workflow_run_id: str
    model_call_id: str
    report_fingerprint: str
    produced_at: datetime
    disposition: str
    candidates: list[RootCauseCandidateView]
    missing_evidence: list[str]
    explanation: str
    schema_version: str


class DiagnosisResultEnvelope(ApiModel):
    result: DiagnosisResultView | None


class AuditEventView(ApiModel):
    sequence: int
    id: str
    type: str
    event_version: int
    payload_schema_version: str
    actor_id: str
    correlation_id: str
    causation_id: str
    target_type: str
    target_id: str
    request_hash: str | None
    result_hash: str | None
    occurred_at: datetime


class AuditPage(ApiModel):
    items: list[AuditEventView]
    next_after_sequence: int | None


class ControlRequest(ApiModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=128)
    causation_id: str = Field(min_length=1, max_length=128)


class ControlResult(ApiModel):
    incident: IncidentView
    cancellation_disposition: str | None = None


class ApprovalSeparationView(ApiModel):
    required: bool
    satisfied: bool
    code: str
    detail: str


class ApprovalSummaryView(ApiModel):
    id: str
    incident_id: str
    proposal_id: str
    proposal_version: int
    proposal_fingerprint: str
    policy_decision_fingerprint: str
    proposer_actor_id: str
    risk_level: str
    status: str
    version: int
    requested_at: datetime
    expires_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None
    expired: bool
    invalidated: bool
    separation_of_duties: ApprovalSeparationView
    schema_version: str


class ApprovalPage(ApiModel):
    items: list[ApprovalSummaryView]
    next_cursor: str | None


class PolicyReasonView(ApiModel):
    code: str
    detail: str


class ApprovalPolicyView(ApiModel):
    decision_id: str
    policy_version: str
    outcome: str
    risk_level: str
    reasons: list[PolicyReasonView]
    environment: str
    blast_radius: str
    maintenance_window: str
    service: str
    requester_roles: list[str]
    separation_of_duties_required: bool
    evaluated_at: datetime
    approval_ttl_seconds: int
    input_fingerprint: str
    decision_fingerprint: str
    schema_version: str


class ProposalDiffEntry(ApiModel):
    path: str
    before: object | None
    after: object | None


class ApprovalInvalidationView(ApiModel):
    invalidated_by: str
    invalidated_at: datetime
    replacement_proposal_id: str
    replacement_proposal_version: int
    replacement_proposal_fingerprint: str
    schema_version: str


class ApprovalDetailView(ApiModel):
    approval: ApprovalSummaryView
    proposal: dict[str, object]
    policy: ApprovalPolicyView
    review_fingerprint: str
    replacement_proposal: dict[str, object] | None
    proposal_diff: list[ProposalDiffEntry]
    invalidation: ApprovalInvalidationView | None


class ApprovalDecisionRequest(ApiModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=512)
    correlation_id: str = Field(min_length=1, max_length=128)
    causation_id: str = Field(min_length=1, max_length=128)


class ApprovalDecisionResult(ApiModel):
    approval: ApprovalSummaryView


def _approval_summary_view(
    approval: Approval,
    *,
    principal: Principal,
    at: datetime,
    invalidated: bool,
) -> ApprovalSummaryView:
    independent = approval.independent_approver_required
    same_actor = approval.proposer_actor_id == principal.actor_id
    if not independent:
        separation = ApprovalSeparationView(
            required=False,
            satisfied=True,
            code="NOT_REQUIRED",
            detail="Policy permits the assigned approver to decide this low-risk request.",
        )
    elif same_actor:
        separation = ApprovalSeparationView(
            required=True,
            satisfied=False,
            code="SELF_APPROVAL_FORBIDDEN",
            detail="A different approver must decide this request.",
        )
    else:
        separation = ApprovalSeparationView(
            required=True,
            satisfied=True,
            code="INDEPENDENT_APPROVER_PRESENT",
            detail="The current approver is independent from the proposer.",
        )
    return ApprovalSummaryView(
        id=approval.id.value,
        incident_id=approval.incident_id.value,
        proposal_id=approval.proposal_id.value,
        proposal_version=approval.proposal_version,
        proposal_fingerprint=approval.proposal_fingerprint.value,
        policy_decision_fingerprint=approval.policy_decision_fingerprint.value,
        proposer_actor_id=approval.proposer_actor_id.value,
        risk_level=approval.risk_level.value,
        status=approval.status.value,
        version=approval.version.value,
        requested_at=approval.requested_at,
        expires_at=approval.expires_at,
        decided_at=approval.decided_at,
        decided_by=None if approval.decided_by is None else approval.decided_by.value,
        decision_reason=(
            None if approval.decision_reason is None else approval.decision_reason.value
        ),
        expired=approval.status is ApprovalStatus.EXPIRED or at >= approval.expires_at,
        invalidated=invalidated,
        separation_of_duties=separation,
        schema_version=approval.schema_version,
    )


def _proposal_diff(before: object, after: object, *, path: str = "$") -> list[ProposalDiffEntry]:
    if isinstance(before, dict) and isinstance(after, dict):
        entries: list[ProposalDiffEntry] = []
        for key in sorted(set(before) | set(after)):
            child = f"{path}.{key}"
            if key not in before:
                entries.append(ProposalDiffEntry(path=child, before=None, after=after[key]))
            elif key not in after:
                entries.append(ProposalDiffEntry(path=child, before=before[key], after=None))
            else:
                entries.extend(_proposal_diff(before[key], after[key], path=child))
        return entries
    if before != after:
        return [ProposalDiffEntry(path=path, before=before, after=after)]
    return []


def _approval_detail_view(
    approval: Approval,
    snapshot: ApprovalReviewSnapshot,
    *,
    principal: Principal,
    at: datetime,
    invalidation: ApprovalInvalidation | None,
    replacement: RemediationProposal | None,
) -> ApprovalDetailView:
    if (
        snapshot.policy_input.tenant_id != approval.tenant_id
        or snapshot.policy_input.incident_id != approval.incident_id
        or snapshot.policy_input.proposal_id != approval.proposal_id
        or snapshot.policy_input.proposal_version != approval.proposal_version
        or snapshot.policy_input.proposal_fingerprint != approval.proposal_fingerprint
        or snapshot.policy_input.fingerprint != approval.policy_input_fingerprint
        or snapshot.policy_decision.id != approval.policy_decision_id
        or snapshot.policy_decision.fingerprint != approval.policy_decision_fingerprint
        or snapshot.policy_decision.risk_level != approval.risk_level
    ):
        raise InvalidDomainValueError("Approval review snapshot does not match Approval")
    proposal = snapshot.proposal.model_dump(mode="json")
    replacement_document = None if replacement is None else replacement.model_dump(mode="json")
    decision = snapshot.policy_decision
    value = snapshot.policy_input
    if decision.approval_ttl is None:  # pragma: no cover - snapshot invariant
        raise InvalidDomainValueError("Approval review decision has no lifetime")
    return ApprovalDetailView(
        approval=_approval_summary_view(
            approval,
            principal=principal,
            at=at,
            invalidated=invalidation is not None,
        ),
        proposal=proposal,
        policy=ApprovalPolicyView(
            decision_id=decision.id.value,
            policy_version=decision.policy_version.value,
            outcome=decision.outcome.value,
            risk_level=decision.risk_level.value,
            reasons=[
                PolicyReasonView(code=reason.code.value, detail=reason.detail)
                for reason in decision.reasons
            ],
            environment=value.environment.value,
            blast_radius=value.blast_radius.value,
            maintenance_window=value.maintenance_window.value,
            service=value.service,
            requester_roles=sorted(role.value for role in value.requester_roles),
            separation_of_duties_required=value.separation_of_duties_required,
            evaluated_at=decision.evaluated_at,
            approval_ttl_seconds=int(decision.approval_ttl.total_seconds()),
            input_fingerprint=value.fingerprint.value,
            decision_fingerprint=decision.fingerprint.value,
            schema_version=decision.schema_version,
        ),
        review_fingerprint=snapshot.fingerprint.value,
        replacement_proposal=replacement_document,
        proposal_diff=(
            [] if replacement_document is None else _proposal_diff(proposal, replacement_document)
        ),
        invalidation=(
            None
            if invalidation is None
            else ApprovalInvalidationView(
                invalidated_by=invalidation.invalidated_by.value,
                invalidated_at=invalidation.invalidated_at,
                replacement_proposal_id=invalidation.replacement_proposal_id.value,
                replacement_proposal_version=invalidation.replacement_proposal_version,
                replacement_proposal_fingerprint=(
                    invalidation.replacement_proposal_fingerprint.value
                ),
                schema_version=invalidation.schema_version,
            )
        ),
    )


def _encode_cursor(parts: list[str | int]) -> str:
    payload = json.dumps(parts, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str, *, expected_parts: int) -> list[str | int]:
    try:
        padding = "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(value + padding))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor") from exc
    if not isinstance(decoded, list) or len(decoded) != expected_parts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor")
    return decoded


def _incident_view(row: IncidentRow) -> IncidentView:
    return IncidentView(
        id=row.id,
        service=row.service,
        severity=row.severity,
        state=row.state,
        version=row.version,
        opened_at=row.opened_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        cancelled_at=row.cancelled_at,
        cancellation_requested_at=row.cancellation_requested_at,
    )


def _evidence_view(row: EvidenceRow, *, at: datetime) -> EvidenceView:
    return EvidenceView(
        id=row.id,
        incident_id=row.incident_id,
        source_type=row.source_type,
        source_instance=row.source_instance,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        tool_schema_version=row.tool_schema_version,
        normalized_query=row.normalized_query,
        observed_from=row.observed_from,
        observed_to=row.observed_to,
        collected_at=row.collected_at,
        artifact_id=row.artifact_id,
        content_hash=row.content_hash,
        parser_version=row.parser_version,
        normalizer_version=row.normalizer_version,
        quality_score_basis_points=row.quality_score_basis_points,
        quality_reasons=row.quality_reasons,
        tool_call_id=row.tool_call_id,
        workflow_run_id=row.workflow_run_id,
        redaction_transform_id=row.redaction_transform_id,
        parent_evidence_ids=row.parent_evidence_ids,
        trust=row.trust,
        prompt_injection_status=row.prompt_injection_status,
        expires_at=row.expires_at,
        expired=as_utc(at) >= as_utc(row.expires_at),
        schema_version=row.schema_version,
    )


def _budget_counter(used: int, maximum: int) -> BudgetCounterView:
    return BudgetCounterView(used=used, maximum=maximum, remaining=maximum - used)


def _investigation_progress_view(row: DiagnosisProgressRow) -> InvestigationProgressView:
    snapshot = diagnosis_progress_from_row(row)
    budgets = snapshot.budgets
    return InvestigationProgressView(
        schema_version=snapshot.schema_version,
        workflow_run_id=snapshot.workflow_run_id,
        graph_version=snapshot.graph_version,
        phase=snapshot.phase.value,
        status=snapshot.status.value,
        budgets=InvestigationBudgetsView(
            steps=_budget_counter(budgets.used_steps, budgets.max_steps),
            replans=_budget_counter(budgets.used_replans, budgets.max_replans),
            tool_calls=_budget_counter(budgets.used_tool_calls, budgets.max_tool_calls),
            model_calls=_budget_counter(budgets.used_model_calls, budgets.max_model_calls),
            tokens=_budget_counter(budgets.used_tokens, budgets.max_tokens),
            cost_nanounits=_budget_counter(budgets.used_cost_nanounits, budgets.max_cost_nanounits),
        ),
        plans=[
            InvestigationPlanView(
                attempt=plan.attempt,
                plan_id=plan.plan_id,
                summary=plan.summary,
                model_call_id=plan.model_call_id,
                created_at=plan.created_at,
                steps=[
                    InvestigationStepView(
                        position=step.position,
                        step_id=step.step_id,
                        objective=step.objective,
                        expected_source=step.expected_source,
                        depends_on=list(step.depends_on),
                        parallel_group=step.parallel_group,
                        tool_call_id=step.tool_call_id,
                        tool_name=step.tool_name,
                        tool_version=step.tool_version,
                        status=step.status.value,
                        failure_code=step.failure_code,
                        started_at=step.started_at,
                        completed_at=step.completed_at,
                    )
                    for step in plan.steps
                ],
            )
            for plan in snapshot.plans
        ],
        replans=[
            ReplanView(
                completed_attempt=item.completed_attempt,
                next_attempt=item.next_attempt,
                decision_fingerprint=item.decision_fingerprint,
                reason_code=item.reason_code,
                occurred_at=item.occurred_at,
            )
            for item in snapshot.replans
        ],
        checkpoint_sequence=snapshot.checkpoint_sequence,
        error_code=snapshot.error_code,
        updated_at=snapshot.updated_at,
    )


def _gate_view(decision: EvidenceGateDecision) -> EvidenceGateDecisionView:
    return EvidenceGateDecisionView(
        outcome=decision.outcome.value,
        reasons=[
            EvidenceGateReasonView(
                code=reason.code.value,
                detail=reason.detail,
                evidence_ids=[item.value for item in reason.evidence_ids],
            )
            for reason in decision.reasons
        ],
        evaluated_evidence_ids=[item.value for item in decision.evaluated_evidence_ids],
        rules_version=decision.rules_version,
        input_fingerprint=decision.input_fingerprint.value,
        decision_fingerprint=evidence_gate_decision_fingerprint(decision).value,
        evaluated_at=decision.evaluated_at,
        model_confidence_basis_points=decision.model_confidence_basis_points,
        schema_version=decision.schema_version,
    )


def _diagnosis_result_view(
    record: DiagnosisReportRecord,
    decisions: tuple[EvidenceGateDecision, ...],
) -> DiagnosisResultView:
    report = record.report
    gate_by_candidate = {decision.candidate_id: decision for decision in decisions}
    return DiagnosisResultView(
        workflow_run_id=record.workflow_run_id.value,
        model_call_id=record.model_call_id.value,
        report_fingerprint=record.report_fingerprint.value,
        produced_at=record.produced_at,
        disposition=report.disposition.value,
        candidates=[
            RootCauseCandidateView(
                candidate_id=candidate.candidate_id,
                rank=candidate.rank,
                statement=candidate.statement,
                supporting_evidence_ids=list(candidate.supporting_evidence_ids),
                counter_evidence_ids=list(candidate.counter_evidence_ids),
                counter_evidence_treatment=candidate.counter_evidence_treatment.value,
                counter_evidence_explanation=candidate.counter_evidence_explanation,
                missing_evidence=list(candidate.missing_evidence),
                uncertainty=candidate.uncertainty,
                confidence_basis_points=candidate.confidence_basis_points,
                gate=(
                    _gate_view(gate_by_candidate[candidate.candidate_id])
                    if candidate.candidate_id in gate_by_candidate
                    else None
                ),
            )
            for candidate in report.candidates
        ],
        missing_evidence=list(report.missing_evidence),
        explanation=report.explanation,
        schema_version=report.schema_version,
    )


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _authorized(principal: Principal, permission: Permission) -> Principal:
    return require_permission(principal, permission, tenant_id=principal.tenant_id)


def new_identifier() -> str:
    return uuid4().hex


async def deny_unconfigured_authentication(_: Request) -> Principal | None:
    """Fail closed until a deployment injects a validated identity adapter."""
    return None


def build_api_v1_router(
    session_factory: SessionFactory,
    *,
    principal_resolver: PrincipalResolver = deny_unconfigured_authentication,
    clock: Clock = utc_now,
    id_factory: IdFactory = new_identifier,
    artifact_storage: ArtifactStorage | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", responses=common_error_responses())

    async def session_dependency() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    async def principal_dependency(request: Request) -> Principal:
        try:
            return require_authenticated(await principal_resolver(request))
        except AuthenticationError as exc:
            raise problem(
                status.HTTP_401_UNAUTHORIZED,
                "AUTHENTICATION_REQUIRED",
                "Authentication required",
                str(exc),
            ) from exc

    Session = Annotated[AsyncSession, Depends(session_dependency)]
    Authenticated = Annotated[Principal, Depends(principal_dependency)]
    PageLimit = Annotated[int, Query(ge=1, le=100)]
    IdempotencyKey = Annotated[
        str,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        ),
    ]

    @router.get("/session", response_model=SessionView)
    async def get_session(principal: Authenticated) -> SessionView:
        return SessionView(
            actor_id=principal.actor_id.value,
            tenant_id=principal.tenant_id.value,
            roles=sorted(role.value for role in principal.roles),
            permissions=sorted(permission.value for permission in principal.permissions),
        )

    @router.get("/approvals", response_model=ApprovalPage)
    async def list_approvals(
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        cursor: str | None = None,
        approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    ) -> ApprovalPage:
        _authorized(principal, Permission.APPROVAL_DECIDE)
        statement = select(ApprovalRow).where(ApprovalRow.tenant_id == principal.tenant_id.value)
        if approval_status is not None:
            statement = statement.where(ApprovalRow.status == approval_status.value)
        if cursor is not None:
            requested_raw, approval_id = _decode_cursor(cursor, expected_parts=2)
            if not isinstance(requested_raw, str) or not isinstance(approval_id, str):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor")
            try:
                requested_at = as_utc(datetime.fromisoformat(requested_raw))
            except ValueError as error:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "invalid pagination cursor"
                ) from error
            statement = statement.where(
                or_(
                    ApprovalRow.requested_at < requested_at,
                    and_(
                        ApprovalRow.requested_at == requested_at,
                        ApprovalRow.id < approval_id,
                    ),
                )
            )
        rows = (
            await session.scalars(
                statement.order_by(ApprovalRow.requested_at.desc(), ApprovalRow.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        visible = rows[:limit]
        invalidated_ids = set(
            (
                await session.scalars(
                    select(ApprovalInvalidationRow.approval_id).where(
                        ApprovalInvalidationRow.tenant_id == principal.tenant_id.value,
                        ApprovalInvalidationRow.approval_id.in_([row.id for row in visible]),
                    )
                )
            ).all()
        )
        repository = ApprovalLifecycleRepository(session)
        approvals: list[Approval] = []
        for row in visible:
            approval = await repository.get(ApprovalId(row.id), tenant_id=principal.tenant_id)
            if approval is None:  # pragma: no cover - selected in the same read transaction
                raise RuntimeError("listed Approval disappeared")
            approvals.append(approval)
        next_cursor = None
        if len(rows) > limit:
            last = visible[-1]
            next_cursor = _encode_cursor([last.requested_at.isoformat(), last.id])
        at = as_utc(clock())
        return ApprovalPage(
            items=[
                _approval_summary_view(
                    approval,
                    principal=principal,
                    at=at,
                    invalidated=approval.id.value in invalidated_ids,
                )
                for approval in approvals
            ],
            next_cursor=next_cursor,
        )

    async def approval_detail(
        approval_id: str,
        *,
        session: AsyncSession,
        principal: Principal,
    ) -> ApprovalDetailView:
        _authorized(principal, Permission.APPROVAL_DECIDE)
        repository = ApprovalLifecycleRepository(session)
        approval = await repository.get(ApprovalId(approval_id), tenant_id=principal.tenant_id)
        if approval is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
        try:
            snapshot = await repository.get_review_snapshot(
                approval.id, tenant_id=principal.tenant_id
            )
            if snapshot is None:
                raise InvalidDomainValueError("Approval review snapshot is unavailable")
            invalidation = await repository.get_invalidation(
                approval.id, tenant_id=principal.tenant_id
            )
            replacement = await repository.get_replacement_proposal(
                approval.id, tenant_id=principal.tenant_id
            )
            return _approval_detail_view(
                approval,
                snapshot,
                principal=principal,
                at=as_utc(clock()),
                invalidation=invalidation,
                replacement=replacement,
            )
        except InvalidDomainValueError as error:
            raise problem(
                status.HTTP_409_CONFLICT,
                "APPROVAL_REVIEW_INTEGRITY_FAILED",
                "Approval review integrity failed",
                "the persisted Approval review could not be verified",
            ) from error

    @router.get("/approvals/{approval_id}", response_model=ApprovalDetailView)
    async def get_approval(
        approval_id: str, session: Session, principal: Authenticated
    ) -> ApprovalDetailView:
        return await approval_detail(approval_id, session=session, principal=principal)

    async def run_approval_decision(
        *,
        operation: Literal["approve", "reject"],
        approval_id: str,
        command: ApprovalDecisionRequest,
        idempotency_key: str,
        session: AsyncSession,
        principal: Principal,
        response: Response,
    ) -> ApprovalDecisionResult:
        _authorized(principal, Permission.APPROVAL_DECIDE)
        request_body = {
            "operation": operation,
            "approval_id": approval_id,
            "command": command.model_dump(mode="json"),
        }
        request_hash = _canonical_hash(request_body)
        at = as_utc(clock())
        durable_operation = f"approval:{operation}:{approval_id}"
        async with session.begin():
            inserted = await session.scalar(
                pg_insert(IdempotencyRecordRow)
                .values(
                    tenant_id=principal.tenant_id.value,
                    actor_id=principal.actor_id.value,
                    operation=durable_operation,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    created_at=at,
                )
                .on_conflict_do_nothing(constraint="uq_idempotency_command")
                .returning(IdempotencyRecordRow.sequence)
            )
            record = await session.scalar(
                select(IdempotencyRecordRow)
                .where(
                    IdempotencyRecordRow.tenant_id == principal.tenant_id.value,
                    IdempotencyRecordRow.actor_id == principal.actor_id.value,
                    IdempotencyRecordRow.operation == durable_operation,
                    IdempotencyRecordRow.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if record is None:  # pragma: no cover - database invariant
                raise RuntimeError("idempotency record was not materialized")
            if inserted is None:
                if record.request_hash != request_hash:
                    raise problem(
                        status.HTTP_409_CONFLICT,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency conflict",
                        "idempotency key was already used with a different request",
                    )
                if record.response_body is None:
                    raise RuntimeError("committed idempotency record has no response")
                response.headers["Idempotency-Replayed"] = "true"
                return ApprovalDecisionResult.model_validate(record.response_body)

            repository = ApprovalLifecycleRepository(session)
            approval = await repository.get(ApprovalId(approval_id), tenant_id=principal.tenant_id)
            if approval is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
            if (
                await repository.get_invalidation(approval.id, tenant_id=principal.tenant_id)
                is not None
            ):
                raise problem(
                    status.HTTP_409_CONFLICT,
                    "APPROVAL_INVALIDATED",
                    "Approval invalidated",
                    "a material proposal revision requires a new Approval",
                )
            lifecycle = ApprovalLifecycleManager(
                repository,
                clock=clock,
                approval_id_factory=id_factory,
                audit_id_factory=id_factory,
                expiry_actor_id=ActorId("approval-expiry-worker"),
            )
            try:
                method = lifecycle.approve if operation == "approve" else lifecycle.reject
                decided = await method(
                    approval.id,
                    principal=principal,
                    reason=EventReason(command.reason),
                    correlation_id=CorrelationId(command.correlation_id),
                    causation_id=CausationId(command.causation_id),
                    expected_version=AggregateVersion(command.expected_version),
                )
            except InvalidDomainValueError as error:
                raise problem(
                    status.HTTP_409_CONFLICT,
                    "APPROVAL_STATE_CONFLICT",
                    "Approval state conflict",
                    str(error),
                ) from error
            result = ApprovalDecisionResult(
                approval=_approval_summary_view(
                    decided,
                    principal=principal,
                    at=at,
                    invalidated=False,
                )
            )
            record.response_status = status.HTTP_200_OK
            record.response_body = result.model_dump(mode="json")
            record.completed_at = at
            response.headers["Idempotency-Replayed"] = "false"
            return result

    @router.post("/approvals/{approval_id}/approve", response_model=ApprovalDecisionResult)
    async def approve_approval(
        approval_id: str,
        command: ApprovalDecisionRequest,
        idempotency_key: IdempotencyKey,
        session: Session,
        principal: Authenticated,
        response: Response,
    ) -> ApprovalDecisionResult:
        return await run_approval_decision(
            operation="approve",
            approval_id=approval_id,
            command=command,
            idempotency_key=idempotency_key,
            session=session,
            principal=principal,
            response=response,
        )

    @router.post("/approvals/{approval_id}/reject", response_model=ApprovalDecisionResult)
    async def reject_approval(
        approval_id: str,
        command: ApprovalDecisionRequest,
        idempotency_key: IdempotencyKey,
        session: Session,
        principal: Authenticated,
        response: Response,
    ) -> ApprovalDecisionResult:
        return await run_approval_decision(
            operation="reject",
            approval_id=approval_id,
            command=command,
            idempotency_key=idempotency_key,
            session=session,
            principal=principal,
            response=response,
        )

    @router.get("/incidents", response_model=IncidentPage)
    async def list_incidents(
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        cursor: str | None = None,
        severity: IncidentSeverity | None = None,
        state: IncidentState | None = None,
        service: Annotated[
            str | None,
            Query(
                min_length=1,
                max_length=128,
                pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
            ),
        ] = None,
    ) -> IncidentPage:
        _authorized(principal, Permission.INCIDENT_READ)
        statement = select(IncidentRow).where(IncidentRow.tenant_id == principal.tenant_id.value)
        if severity is not None:
            statement = statement.where(IncidentRow.severity == severity.value)
        if state is not None:
            statement = statement.where(IncidentRow.state == state.value)
        if service is not None:
            statement = statement.where(IncidentRow.service == service)
        if cursor is not None:
            opened_raw, incident_id = _decode_cursor(cursor, expected_parts=2)
            if not isinstance(opened_raw, str) or not isinstance(incident_id, str):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor")
            try:
                opened_at = as_utc(datetime.fromisoformat(opened_raw))
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "invalid pagination cursor"
                ) from exc
            statement = statement.where(
                or_(
                    IncidentRow.opened_at < opened_at,
                    and_(IncidentRow.opened_at == opened_at, IncidentRow.id < incident_id),
                )
            )
        rows = (
            await session.scalars(
                statement.order_by(IncidentRow.opened_at.desc(), IncidentRow.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = visible[-1]
            next_cursor = _encode_cursor([last.opened_at.isoformat(), last.id])
        return IncidentPage(items=[_incident_view(row) for row in visible], next_cursor=next_cursor)

    @router.get("/incidents/{incident_id}", response_model=IncidentView)
    async def get_incident(
        incident_id: str, session: Session, principal: Authenticated
    ) -> IncidentView:
        _authorized(principal, Permission.INCIDENT_READ)
        row = await session.scalar(
            select(IncidentRow).where(
                IncidentRow.id == incident_id,
                IncidentRow.tenant_id == principal.tenant_id.value,
            )
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
        return _incident_view(row)

    @router.get(
        "/incidents/{incident_id}/investigation",
        response_model=InvestigationProgressEnvelope,
    )
    async def get_investigation_progress(
        incident_id: str, session: Session, principal: Authenticated
    ) -> InvestigationProgressEnvelope:
        _authorized(principal, Permission.INCIDENT_READ)
        owned = await session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == incident_id,
                IncidentRow.tenant_id == principal.tenant_id.value,
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
        row = await session.scalar(
            select(DiagnosisProgressRow)
            .where(
                DiagnosisProgressRow.incident_id == incident_id,
                DiagnosisProgressRow.tenant_id == principal.tenant_id.value,
            )
            .order_by(
                DiagnosisProgressRow.updated_at.desc(),
                DiagnosisProgressRow.workflow_run_id.desc(),
            )
            .limit(1)
        )
        if row is None:
            return InvestigationProgressEnvelope(run=None)
        try:
            return InvestigationProgressEnvelope(run=_investigation_progress_view(row))
        except InvalidDomainValueError as error:
            raise problem(
                status.HTTP_409_CONFLICT,
                "INVESTIGATION_PROGRESS_INTEGRITY_FAILED",
                "Investigation progress integrity failed",
                "the persisted investigation progress could not be verified",
            ) from error

    @router.get(
        "/incidents/{incident_id}/diagnosis",
        response_model=DiagnosisResultEnvelope,
    )
    async def get_diagnosis_result(
        incident_id: str, session: Session, principal: Authenticated
    ) -> DiagnosisResultEnvelope:
        _authorized(principal, Permission.EVIDENCE_READ)
        owned = await session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == incident_id,
                IncidentRow.tenant_id == principal.tenant_id.value,
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
        repository = DiagnosisReportRepository(session)
        try:
            record = await repository.latest(
                tenant_id=principal.tenant_id,
                incident_id=IncidentId(incident_id),
            )
            if record is None:
                return DiagnosisResultEnvelope(result=None)
            decisions = await repository.matching_gate_decisions(record)
            return DiagnosisResultEnvelope(result=_diagnosis_result_view(record, decisions))
        except InvalidDomainValueError as error:
            raise problem(
                status.HTTP_409_CONFLICT,
                "DIAGNOSIS_RESULT_INTEGRITY_FAILED",
                "Diagnosis result integrity failed",
                "the persisted diagnosis result could not be verified",
            ) from error

    @router.get("/incidents/{incident_id}/evidence", response_model=EvidencePage)
    async def list_evidence(
        incident_id: str,
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        cursor: str | None = None,
    ) -> EvidencePage:
        _authorized(principal, Permission.EVIDENCE_READ)
        owned = await session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == incident_id,
                IncidentRow.tenant_id == principal.tenant_id.value,
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
        statement = select(EvidenceRow).where(
            EvidenceRow.tenant_id == principal.tenant_id.value,
            EvidenceRow.incident_id == incident_id,
        )
        if cursor is not None:
            collected_raw, evidence_id = _decode_cursor(cursor, expected_parts=2)
            if not isinstance(collected_raw, str) or not isinstance(evidence_id, str):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor")
            try:
                collected_at = as_utc(datetime.fromisoformat(collected_raw))
            except ValueError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "invalid pagination cursor"
                ) from exc
            statement = statement.where(
                or_(
                    EvidenceRow.collected_at < collected_at,
                    and_(EvidenceRow.collected_at == collected_at, EvidenceRow.id < evidence_id),
                )
            )
        rows = (
            await session.scalars(
                statement.order_by(EvidenceRow.collected_at.desc(), EvidenceRow.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        visible = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = visible[-1]
            next_cursor = _encode_cursor([last.collected_at.isoformat(), last.id])
        now = clock()
        return EvidencePage(
            items=[_evidence_view(row, at=now) for row in visible], next_cursor=next_cursor
        )

    async def scoped_evidence(
        *, incident_id: str, evidence_id: str, session: AsyncSession, principal: Principal
    ) -> EvidenceRow:
        _authorized(principal, Permission.EVIDENCE_READ)
        row = await session.scalar(
            select(EvidenceRow).where(
                EvidenceRow.id == evidence_id,
                EvidenceRow.tenant_id == principal.tenant_id.value,
                EvidenceRow.incident_id == incident_id,
            )
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "evidence not found")
        return row

    @router.get("/incidents/{incident_id}/evidence/{evidence_id}", response_model=EvidenceView)
    async def get_evidence(
        incident_id: str, evidence_id: str, session: Session, principal: Authenticated
    ) -> EvidenceView:
        row = await scoped_evidence(
            incident_id=incident_id,
            evidence_id=evidence_id,
            session=session,
            principal=principal,
        )
        return _evidence_view(row, at=clock())

    @router.get(
        "/incidents/{incident_id}/evidence/{evidence_id}/artifact",
        response_class=Response,
    )
    async def get_evidence_artifact(
        incident_id: str, evidence_id: str, session: Session, principal: Authenticated
    ) -> Response:
        row = await scoped_evidence(
            incident_id=incident_id,
            evidence_id=evidence_id,
            session=session,
            principal=principal,
        )
        now = clock()
        if as_utc(now) >= as_utc(row.expires_at):
            raise problem(
                status.HTTP_410_GONE,
                "EVIDENCE_EXPIRED",
                "Evidence expired",
                "evidence content is no longer available",
            )
        if artifact_storage is None:
            raise problem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "ARTIFACT_STORAGE_UNAVAILABLE",
                "Artifact storage unavailable",
                "artifact content retrieval is not configured",
            )
        try:
            content = artifact_storage.retrieve(
                ArtifactId(row.artifact_id),
                incident_id=IncidentId(incident_id),
                principal=principal,
                at=now,
            )
        except ArtifactNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "artifact not found") from exc
        except ArtifactExpiredError as exc:
            raise problem(
                status.HTTP_410_GONE,
                "ARTIFACT_EXPIRED",
                "Artifact expired",
                "artifact content is no longer available",
            ) from exc
        except ArtifactIntegrityError as exc:
            raise problem(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_INTEGRITY_FAILED",
                "Artifact integrity failed",
                "artifact content could not be verified",
            ) from exc
        artifact = content.artifact
        if (
            artifact.id.value != row.artifact_id
            or artifact.tenant_id != principal.tenant_id
            or artifact.incident_id.value != incident_id
            or artifact.content_hash.value != row.content_hash
        ):
            raise problem(
                status.HTTP_409_CONFLICT,
                "ARTIFACT_BINDING_MISMATCH",
                "Artifact binding mismatch",
                "artifact metadata does not match the evidence record",
            )
        return Response(
            content=content.content,
            media_type=artifact.media_type,
            headers={
                "Cache-Control": "private, no-store",
                "ETag": f'"sha256:{artifact.content_hash.value}"',
                "X-Artifact-ID": artifact.id.value,
                "X-Content-SHA256": artifact.content_hash.value,
                "X-Content-Schema-Version": artifact.content_schema_version,
                "X-Redaction-Status": artifact.redaction_status.value,
            },
        )

    @router.get("/incidents/{incident_id}/timeline", response_model=TimelinePage)
    async def get_timeline(
        incident_id: str,
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        cursor: str | None = None,
    ) -> TimelinePage:
        _authorized(principal, Permission.INCIDENT_READ)
        owned = await session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == incident_id,
                IncidentRow.tenant_id == principal.tenant_id.value,
            )
        )
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
        after = (0, -1)
        if cursor is not None:
            version, rank = _decode_cursor(cursor, expected_parts=2)
            if (
                not isinstance(version, int)
                or version < 0
                or not isinstance(rank, int)
                or rank not in (0, 1)
            ):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid pagination cursor")
            after = (version, rank)
        transitions = (
            await session.scalars(
                select(IncidentTransitionRow)
                .where(
                    IncidentTransitionRow.incident_id == incident_id,
                    IncidentTransitionRow.new_version >= after[0],
                )
                .order_by(IncidentTransitionRow.new_version)
                .limit(limit + 1)
            )
        ).all()
        cancellations = (
            await session.scalars(
                select(IncidentCancellationRequestRow)
                .where(
                    IncidentCancellationRequestRow.incident_id == incident_id,
                    IncidentCancellationRequestRow.new_version >= after[0],
                )
                .order_by(IncidentCancellationRequestRow.new_version)
                .limit(limit + 1)
            )
        ).all()
        events: list[tuple[tuple[int, int], TimelineEventView]] = []
        for row in transitions:
            events.append(
                (
                    (row.new_version, 1),
                    TimelineEventView(
                        kind="transition",
                        prior_version=row.prior_version,
                        new_version=row.new_version,
                        actor_id=row.actor_id,
                        reason=row.reason,
                        correlation_id=row.correlation_id,
                        causation_id=row.causation_id,
                        occurred_at=row.occurred_at,
                        prior_state=row.prior_state,
                        new_state=row.new_state,
                    ),
                )
            )
        for cancellation in cancellations:
            events.append(
                (
                    (cancellation.new_version, 0),
                    TimelineEventView(
                        kind="cancellation_request",
                        prior_version=cancellation.prior_version,
                        new_version=cancellation.new_version,
                        actor_id=cancellation.actor_id,
                        reason=cancellation.reason,
                        correlation_id=cancellation.correlation_id,
                        causation_id=cancellation.causation_id,
                        occurred_at=cancellation.occurred_at,
                        state_when_requested=cancellation.state_when_requested,
                        disposition=cancellation.disposition,
                    ),
                )
            )
        ordered = sorted((item for item in events if item[0] > after), key=lambda item: item[0])
        visible = ordered[:limit]
        next_cursor = _encode_cursor(list(visible[-1][0])) if len(ordered) > limit else None
        return TimelinePage(items=[item[1] for item in visible], next_cursor=next_cursor)

    @router.get("/audit", response_model=AuditPage)
    async def list_audit(
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        after_sequence: Annotated[int, Query(ge=0)] = 0,
    ) -> AuditPage:
        _authorized(principal, Permission.AUDIT_READ)
        rows = (
            await session.scalars(
                select(AuditEventRow)
                .where(
                    AuditEventRow.tenant_id == principal.tenant_id.value,
                    AuditEventRow.sequence > after_sequence,
                )
                .order_by(AuditEventRow.sequence)
                .limit(limit + 1)
            )
        ).all()
        visible = rows[:limit]
        return AuditPage(
            items=[
                AuditEventView(
                    sequence=row.sequence,
                    id=row.id,
                    type=row.event_type,
                    event_version=row.event_version,
                    payload_schema_version=row.payload_schema_version,
                    actor_id=row.actor_id,
                    correlation_id=row.correlation_id,
                    causation_id=row.causation_id,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    request_hash=row.request_hash,
                    result_hash=row.result_hash,
                    occurred_at=row.occurred_at,
                )
                for row in visible
            ],
            next_after_sequence=visible[-1].sequence if len(rows) > limit else None,
        )

    async def run_control(
        *,
        operation: str,
        incident_id: str,
        command: ControlRequest,
        idempotency_key: str,
        session: AsyncSession,
        principal: Principal,
        response: Response,
    ) -> ControlResult:
        permission = (
            Permission.INVESTIGATION_START
            if operation == "start-investigation"
            else Permission.INVESTIGATION_CANCEL
        )
        _authorized(principal, permission)
        request_payload = {
            "operation": operation,
            "incident_id": incident_id,
            "command": command.model_dump(mode="json"),
        }
        request_hash = _canonical_hash(request_payload)
        now = as_utc(clock())
        async with session.begin():
            inserted = await session.scalar(
                pg_insert(IdempotencyRecordRow)
                .values(
                    tenant_id=principal.tenant_id.value,
                    actor_id=principal.actor_id.value,
                    operation=f"incident:{operation}:{incident_id}",
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    created_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_idempotency_command")
                .returning(IdempotencyRecordRow.sequence)
            )
            record = await session.scalar(
                select(IdempotencyRecordRow)
                .where(
                    IdempotencyRecordRow.tenant_id == principal.tenant_id.value,
                    IdempotencyRecordRow.actor_id == principal.actor_id.value,
                    IdempotencyRecordRow.operation == f"incident:{operation}:{incident_id}",
                    IdempotencyRecordRow.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
            if record is None:
                raise RuntimeError(  # pragma: no cover - single-transaction database invariant
                    "idempotency record was not materialized"
                )
            if inserted is None:
                if record.request_hash != request_hash:
                    raise problem(
                        status.HTTP_409_CONFLICT,
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency conflict",
                        "idempotency key was already used with a different request",
                    )
                if record.response_body is None:
                    raise RuntimeError("committed idempotency record has no response")
                response.headers["Idempotency-Replayed"] = "true"
                return ControlResult.model_validate(record.response_body)

            repository = IncidentRepository(session)
            incident = await repository.get_for_tenant(IncidentId(incident_id), principal.tenant_id)
            if incident is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "incident not found")
            metadata = EventMetadata(
                actor_id=principal.actor_id,
                reason=EventReason(command.reason),
                correlation_id=CorrelationId(command.correlation_id),
                causation_id=CausationId(command.causation_id),
                occurred_at=now,
            )
            if operation == "start-investigation":
                change = incident.transition(
                    IncidentState.INVESTIGATING,
                    expected_version=AggregateVersion(command.expected_version),
                    metadata=metadata,
                )
                disposition = None
                event_type = "incident.investigation_started"
            else:
                change = incident.request_cancellation(
                    expected_version=AggregateVersion(command.expected_version), metadata=metadata
                )
                disposition = (
                    None
                    if change.cancellation_request is None
                    else change.cancellation_request.disposition.value
                )
                event_type = "incident.cancellation_requested"
            await repository.apply(change)
            result_row = await session.scalar(
                select(IncidentRow).where(IncidentRow.id == incident_id)
            )
            if result_row is None:
                raise RuntimeError(  # pragma: no cover - update and read share one transaction
                    "updated incident disappeared"
                )
            result = ControlResult(
                incident=_incident_view(result_row), cancellation_disposition=disposition
            )
            result_body = result.model_dump(mode="json")
            await AuditRepository(session).append(
                AuditEvent(
                    id=AuditEventId(id_factory()),
                    tenant_id=principal.tenant_id,
                    type=event_type,
                    event_version=1,
                    payload_schema_version="incident-control/v1",
                    actor_id=ActorId(principal.actor_id.value),
                    correlation_id=CorrelationId(command.correlation_id),
                    causation_id=CausationId(command.causation_id),
                    target=AuditTarget("incident.lifecycle", IncidentId(incident_id)),
                    occurred_at=now,
                    request_hash=Sha256Digest(request_hash),
                    result_hash=Sha256Digest(_canonical_hash(result_body)),
                )
            )
            record.response_status = status.HTTP_200_OK
            record.response_body = result_body
            record.completed_at = now
            response.headers["Idempotency-Replayed"] = "false"
            return result

    @router.post(
        "/incidents/{incident_id}/controls/start-investigation", response_model=ControlResult
    )
    async def start_investigation(
        incident_id: str,
        command: ControlRequest,
        idempotency_key: IdempotencyKey,
        session: Session,
        principal: Authenticated,
        response: Response,
    ) -> ControlResult:
        return await run_control(
            operation="start-investigation",
            incident_id=incident_id,
            command=command,
            idempotency_key=idempotency_key,
            session=session,
            principal=principal,
            response=response,
        )

    @router.post("/incidents/{incident_id}/controls/cancel", response_model=ControlResult)
    async def cancel_incident(
        incident_id: str,
        command: ControlRequest,
        idempotency_key: IdempotencyKey,
        session: Session,
        principal: Authenticated,
        response: Response,
    ) -> ControlResult:
        return await run_control(
            operation="cancel",
            incident_id=incident_id,
            command=command,
            idempotency_key=idempotency_key,
            session=session,
            principal=principal,
            response=response,
        )

    return router

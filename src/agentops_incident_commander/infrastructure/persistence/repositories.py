"""Async PostgreSQL repositories preserving pure-domain invariants."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta
from math import isclose
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application import (
    HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION,
    ApprovalLifecycleChange,
    PromptLifecycleChange,
    evidence_gate_decision_fingerprint,
    evidence_gate_input_fingerprint,
    evidence_gate_input_snapshot,
    health_verification_closure_fingerprint,
    model_call_trace_fingerprint,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    Alert,
    AlertFingerprint,
    AlertGroup,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    AlertTriageDecision,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    Artifact,
    ArtifactId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    AuthorizationError,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    Evidence,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateReason,
    EvidenceGateReasonCode,
    EvidenceGateRules,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    HealthVerificationCriteria,
    HealthVerificationDecision,
    HealthVerificationObservation,
    HealthVerificationOutcome,
    HealthVerificationReasonCode,
    HealthVerificationSample,
    HealthVerificationScenario,
    IdempotencyKey,
    Incident,
    IncidentChange,
    IncidentId,
    IncidentMemoryConfirmationSource,
    IncidentMemoryEmbedding,
    IncidentMemoryId,
    IncidentMemoryOutcome,
    IncidentMemoryProjection,
    IncidentMemorySearchQuery,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    Job,
    JobFailureRoute,
    JobId,
    JobLease,
    JobLeaseError,
    JobStatus,
    ModelCallId,
    ModelCallStatus,
    ModelCallTrace,
    ModelCost,
    ModelCostSource,
    ModelMetering,
    ModelMeteringUnavailableReason,
    ModelTokenUsage,
    NormalizedQuery,
    OpaqueIdentifier,
    OptimisticVersionError,
    OutboxClaim,
    OutboxEvent,
    OutboxEventId,
    OutboxLeaseError,
    OutboxPayload,
    PolicyEnvironment,
    PromptDefinition,
    PromptId,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    QueryParameter,
    RedactionTransformId,
    ResolvedRollbackTarget,
    RiskLevel,
    RootCauseEvidenceClaim,
    SemanticVersion,
    Sha256Digest,
    SimilarIncidentReference,
    StoredAuditEvent,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
    as_utc,
    evaluate_health_verification,
    select_alert_group,
)

from .models import (
    ActionExecutionEventRow,
    ActionExecutionLockRow,
    ActionExecutionRow,
    AlertGroupRow,
    AlertRow,
    ApprovalInvalidationRow,
    ApprovalLifecycleEventRow,
    ApprovalRow,
    AuditEventRow,
    EvidenceGateDecisionRow,
    EvidenceRow,
    HealthVerificationRunRow,
    IncidentCancellationRequestRow,
    IncidentMemoryEmbeddingRow,
    IncidentMemoryProjectionRow,
    IncidentRow,
    IncidentTransitionRow,
    JobRow,
    ModelCallTraceRow,
    OutboxEventRow,
    PromptLifecycleEventRow,
    PromptVersionRow,
)


def _evidence_from_row(row: EvidenceRow) -> Evidence:
    return Evidence(
        id=EvidenceId(row.id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        source_type=EvidenceSourceType(row.source_type),
        source_instance=row.source_instance,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        tool_schema_version=row.tool_schema_version,
        normalized_query=NormalizedQuery(
            tuple(QueryParameter(name, value) for name, value in row.normalized_query.items())
        ),
        observed_from=row.observed_from,
        observed_to=row.observed_to,
        collected_at=row.collected_at,
        artifact_id=ArtifactId(row.artifact_id),
        content_hash=Sha256Digest(row.content_hash),
        parser_version=row.parser_version,
        normalizer_version=row.normalizer_version,
        quality=EvidenceQuality(row.quality_score_basis_points, tuple(row.quality_reasons)),
        lineage=EvidenceLineage(
            ToolCallId(row.tool_call_id),
            WorkflowRunId(row.workflow_run_id),
            (
                RedactionTransformId(row.redaction_transform_id)
                if row.redaction_transform_id is not None
                else None
            ),
            tuple(EvidenceId(value) for value in row.parent_evidence_ids),
        ),
        trust=TrustClassification(row.trust),
        prompt_injection_status=PromptInjectionStatus(row.prompt_injection_status),
        expires_at=row.expires_at,
        schema_version=row.schema_version,
    )


class EvidenceRepository:
    """Persist immutable Evidence after resolving its exact Artifact binding."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, evidence: Evidence, artifact: Artifact) -> None:
        evidence.verify_artifact(artifact)
        self._session.add(
            EvidenceRow(
                id=evidence.id.value,
                tenant_id=evidence.tenant_id.value,
                incident_id=evidence.incident_id.value,
                source_type=evidence.source_type.value,
                source_instance=evidence.source_instance,
                tool_name=evidence.tool_name,
                tool_version=evidence.tool_version,
                tool_schema_version=evidence.tool_schema_version,
                normalized_query=evidence.normalized_query.as_dict(),
                observed_from=evidence.observed_from,
                observed_to=evidence.observed_to,
                collected_at=evidence.collected_at,
                artifact_id=evidence.artifact_id.value,
                content_hash=evidence.content_hash.value,
                parser_version=evidence.parser_version,
                normalizer_version=evidence.normalizer_version,
                quality_score_basis_points=evidence.quality.score_basis_points,
                quality_reasons=list(evidence.quality.reasons),
                tool_call_id=evidence.lineage.tool_call_id.value,
                workflow_run_id=evidence.lineage.workflow_run_id.value,
                redaction_transform_id=(
                    evidence.lineage.redaction_transform_id.value
                    if evidence.lineage.redaction_transform_id is not None
                    else None
                ),
                parent_evidence_ids=[value.value for value in evidence.lineage.parent_evidence_ids],
                trust=evidence.trust.value,
                prompt_injection_status=evidence.prompt_injection_status.value,
                expires_at=evidence.expires_at,
                schema_version=evidence.schema_version,
            )
        )
        await self._session.flush()

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        row = await self._session.scalar(
            select(EvidenceRow).where(
                EvidenceRow.id == evidence_id.value,
                EvidenceRow.tenant_id == tenant_id.value,
                EvidenceRow.incident_id == incident_id.value,
            )
        )
        return _evidence_from_row(row) if row is not None else None


def _job_from_row(row: JobRow) -> Job:
    return Job(
        id=JobId(row.id),
        type=row.type,
        schema_version=row.schema_version,
        payload_ref=OpaqueIdentifier(row.payload_ref),
        correlation_id=CorrelationId(row.correlation_id),
        causation_id=CausationId(row.causation_id),
        priority=row.priority,
        created_at=row.created_at,
        available_at=row.available_at,
        max_attempts=row.max_attempts,
        failure_route=JobFailureRoute(row.failure_route),
    )


class JobRepository:
    """Coordinate bounded durable jobs through PostgreSQL row leases."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, job: Job) -> int:
        row = JobRow(
            id=job.id.value,
            type=job.type,
            schema_version=job.schema_version,
            payload_ref=job.payload_ref.value,
            correlation_id=job.correlation_id.value,
            causation_id=job.causation_id.value,
            priority=job.priority,
            status=JobStatus.PENDING.value,
            created_at=job.created_at,
            available_at=job.available_at,
            max_attempts=job.max_attempts,
            attempt_count=0,
            failure_route=job.failure_route.value,
        )
        self._session.add(row)
        await self._session.flush()
        return row.sequence

    async def claim(
        self,
        worker_id: OpaqueIdentifier,
        *,
        now: datetime,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[JobLease, ...]:
        current = as_utc(now)
        if lease_duration <= timedelta(0):
            raise InvalidDomainValueError("job lease duration must be positive")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise InvalidDomainValueError("job claim limit must be between 1 and 100")
        await self._route_exhausted_stale_leases(current)
        rows = (
            await self._session.scalars(
                select(JobRow)
                .where(
                    JobRow.available_at <= current,
                    JobRow.attempt_count < JobRow.max_attempts,
                    or_(
                        JobRow.status == JobStatus.PENDING.value,
                        (JobRow.status == JobStatus.LEASED.value)
                        & (JobRow.lease_expires_at <= current),
                    ),
                )
                .order_by(JobRow.priority.desc(), JobRow.sequence)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        expires_at = current + lease_duration
        leases: list[JobLease] = []
        for row in rows:
            row.status = JobStatus.LEASED.value
            row.attempt_count += 1
            row.lease_owner = worker_id.value
            row.leased_at = current
            row.heartbeat_at = current
            row.lease_expires_at = expires_at
            leases.append(
                JobLease(
                    job=_job_from_row(row),
                    attempt=row.attempt_count,
                    worker_id=worker_id,
                    leased_at=current,
                    heartbeat_at=current,
                    expires_at=expires_at,
                )
            )
        await self._session.flush()
        return tuple(leases)

    async def heartbeat(
        self,
        job_id: JobId,
        worker_id: OpaqueIdentifier,
        *,
        now: datetime,
        lease_duration: timedelta,
    ) -> JobLease:
        current = as_utc(now)
        if lease_duration <= timedelta(0):
            raise InvalidDomainValueError("job heartbeat duration must be positive")
        row = await self._owned_job(job_id, worker_id, current)
        if row.heartbeat_at is None or current < row.heartbeat_at:
            raise InvalidDomainValueError("job heartbeat cannot move backward")
        row.heartbeat_at = current
        row.lease_expires_at = current + lease_duration
        await self._session.flush()
        return JobLease(
            job=_job_from_row(row),
            attempt=row.attempt_count,
            worker_id=worker_id,
            leased_at=cast(datetime, row.leased_at),
            heartbeat_at=current,
            expires_at=row.lease_expires_at,
        )

    async def complete(
        self, job_id: JobId, worker_id: OpaqueIdentifier, *, completed_at: datetime
    ) -> None:
        current = as_utc(completed_at)
        row = await self._owned_job(job_id, worker_id, current)
        self._terminalize(row, JobStatus.COMPLETED, current)
        await self._session.flush()

    async def fail(
        self,
        job_id: JobId,
        worker_id: OpaqueIdentifier,
        *,
        failed_at: datetime,
        retry_at: datetime,
        error: str,
    ) -> JobStatus:
        current = as_utc(failed_at)
        next_attempt = as_utc(retry_at)
        if next_attempt < current:
            raise InvalidDomainValueError("job retry cannot predate failure")
        bounded_error = error.strip()
        if (
            not bounded_error
            or len(bounded_error) > 512
            or any(ord(character) < 32 for character in bounded_error)
        ):
            raise InvalidDomainValueError("job failure must be bounded printable text")
        row = await self._owned_job(job_id, worker_id, current)
        row.last_error = bounded_error
        if row.attempt_count >= row.max_attempts:
            status = JobStatus(row.failure_route)
            self._terminalize(row, status, current)
        else:
            status = JobStatus.PENDING
            row.status = status.value
            row.available_at = next_attempt
            self._clear_lease(row)
        await self._session.flush()
        return status

    async def _route_exhausted_stale_leases(self, current: datetime) -> None:
        for route in JobFailureRoute:
            await self._session.execute(
                update(JobRow)
                .where(
                    JobRow.status == JobStatus.LEASED.value,
                    JobRow.lease_expires_at <= current,
                    JobRow.attempt_count >= JobRow.max_attempts,
                    JobRow.failure_route == route.value,
                )
                .values(
                    status=route.value,
                    terminal_at=current,
                    lease_owner=None,
                    leased_at=None,
                    heartbeat_at=None,
                    lease_expires_at=None,
                    last_error="lease expired after final attempt",
                )
            )

    async def _owned_job(
        self, job_id: JobId, worker_id: OpaqueIdentifier, current: datetime
    ) -> JobRow:
        row = await self._session.scalar(
            select(JobRow).where(JobRow.id == job_id.value).with_for_update()
        )
        if (
            row is None
            or row.status != JobStatus.LEASED.value
            or row.lease_owner != worker_id.value
            or row.lease_expires_at is None
            or row.lease_expires_at <= current
        ):
            raise JobLeaseError("job has no active lease owned by this worker")
        return row

    @staticmethod
    def _clear_lease(row: JobRow) -> None:
        row.lease_owner = None
        row.leased_at = None
        row.heartbeat_at = None
        row.lease_expires_at = None

    @classmethod
    def _terminalize(cls, row: JobRow, status: JobStatus, current: datetime) -> None:
        row.status = status.value
        row.terminal_at = current
        cls._clear_lease(row)


def _outbox_event_from_row(row: OutboxEventRow) -> OutboxEvent:
    payload = OutboxPayload.from_mapping(row.payload)
    if payload.sha256.value != row.payload_hash:
        raise InvalidDomainValueError("outbox payload hash does not match stored payload")
    return OutboxEvent(
        id=OutboxEventId(row.id),
        topic=row.topic,
        schema_version=row.schema_version,
        aggregate_type=row.aggregate_type,
        aggregate_id=OpaqueIdentifier(row.aggregate_id),
        aggregate_version=row.aggregate_version,
        correlation_id=CorrelationId(row.correlation_id),
        causation_id=CausationId(row.causation_id),
        payload=payload,
        occurred_at=row.occurred_at,
        available_at=row.available_at,
        max_attempts=row.max_attempts,
    )


class OutboxRepository:
    """Stage event intent transactionally and coordinate reliable publication."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue(self, event: OutboxEvent) -> int:
        """Stage one idempotent event intent in the caller-owned transaction."""
        row = OutboxEventRow(
            id=event.id.value,
            topic=event.topic,
            schema_version=event.schema_version,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id.value,
            aggregate_version=event.aggregate_version,
            correlation_id=event.correlation_id.value,
            causation_id=event.causation_id.value,
            payload=event.payload.as_mapping(),
            payload_hash=event.payload.sha256.value,
            occurred_at=event.occurred_at,
            available_at=event.available_at,
            max_attempts=event.max_attempts,
            attempt_count=0,
        )
        self._session.add(row)
        await self._session.flush()
        return row.sequence

    async def claim(
        self,
        worker_id: OpaqueIdentifier,
        *,
        now: datetime,
        lease_duration: timedelta,
        limit: int,
    ) -> tuple[OutboxClaim, ...]:
        """Claim available intents with SKIP LOCKED and reclaim expired leases."""
        current = as_utc(now)
        if lease_duration <= timedelta(0):
            raise InvalidDomainValueError("outbox lease duration must be positive")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise InvalidDomainValueError("outbox claim limit must be between 1 and 100")
        rows = (
            await self._session.scalars(
                select(OutboxEventRow)
                .where(
                    OutboxEventRow.published_at.is_(None),
                    OutboxEventRow.dead_lettered_at.is_(None),
                    OutboxEventRow.available_at <= current,
                    OutboxEventRow.attempt_count < OutboxEventRow.max_attempts,
                    or_(
                        OutboxEventRow.lease_expires_at.is_(None),
                        OutboxEventRow.lease_expires_at <= current,
                    ),
                )
                .order_by(OutboxEventRow.sequence)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        lease_expires_at = current + lease_duration
        claims: list[OutboxClaim] = []
        for row in rows:
            row.attempt_count += 1
            row.lease_owner = worker_id.value
            row.lease_expires_at = lease_expires_at
            claims.append(
                OutboxClaim(
                    sequence=row.sequence,
                    event=_outbox_event_from_row(row),
                    attempt=row.attempt_count,
                    worker_id=worker_id,
                    lease_expires_at=lease_expires_at,
                )
            )
        await self._session.flush()
        return tuple(claims)

    async def mark_published(
        self, event_id: OutboxEventId, worker_id: OpaqueIdentifier, *, published_at: datetime
    ) -> None:
        """Acknowledge publication only while the caller owns an active lease."""
        completed_at = as_utc(published_at)
        row = await self._locked_owned_row(event_id, worker_id, completed_at)
        row.published_at = completed_at
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error = None
        await self._session.flush()

    async def mark_failed(
        self,
        event_id: OutboxEventId,
        worker_id: OpaqueIdentifier,
        *,
        failed_at: datetime,
        retry_at: datetime,
        error: str,
    ) -> None:
        """Release a failed attempt for retry or dead-letter it at its bounded limit."""
        failure_time = as_utc(failed_at)
        next_attempt = as_utc(retry_at)
        if next_attempt < failure_time:
            raise InvalidDomainValueError("outbox retry cannot predate failure")
        bounded_error = error.strip()
        if (
            not bounded_error
            or len(bounded_error) > 512
            or any(ord(character) < 32 for character in bounded_error)
        ):
            raise InvalidDomainValueError("outbox failure must be bounded printable text")
        row = await self._locked_owned_row(event_id, worker_id, failure_time)
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error = bounded_error
        if row.attempt_count >= row.max_attempts:
            row.dead_lettered_at = failure_time
        else:
            row.available_at = next_attempt
        await self._session.flush()

    async def _locked_owned_row(
        self, event_id: OutboxEventId, worker_id: OpaqueIdentifier, at: datetime
    ) -> OutboxEventRow:
        row = await self._session.scalar(
            select(OutboxEventRow).where(OutboxEventRow.id == event_id.value).with_for_update()
        )
        if (
            row is None
            or row.lease_owner != worker_id.value
            or row.lease_expires_at is None
            or row.lease_expires_at <= at
        ):
            raise OutboxLeaseError("outbox event has no active lease owned by this worker")
        return row


def _audit_from_row(row: AuditEventRow) -> StoredAuditEvent:
    return StoredAuditEvent(
        sequence=row.sequence,
        event=AuditEvent(
            id=AuditEventId(row.id),
            tenant_id=TenantId(row.tenant_id),
            type=row.event_type,
            event_version=row.event_version,
            payload_schema_version=row.payload_schema_version,
            actor_id=ActorId(row.actor_id),
            correlation_id=CorrelationId(row.correlation_id),
            causation_id=CausationId(row.causation_id),
            target=AuditTarget(row.target_type, OpaqueIdentifier(row.target_id)),
            request_hash=None if row.request_hash is None else Sha256Digest(row.request_hash),
            result_hash=None if row.result_hash is None else Sha256Digest(row.result_hash),
            occurred_at=row.occurred_at,
        ),
    )


class AuditRepository:
    """The only application adapter permitted to append and read audit events."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, event: AuditEvent) -> StoredAuditEvent:
        """Append one immutable event and return its global database sequence."""
        row = AuditEventRow(
            id=event.id.value,
            tenant_id=event.tenant_id.value,
            event_type=event.type,
            event_version=event.event_version,
            payload_schema_version=event.payload_schema_version,
            actor_id=event.actor_id.value,
            correlation_id=event.correlation_id.value,
            causation_id=event.causation_id.value,
            target_type=event.target.type,
            target_id=event.target.id.value,
            request_hash=None if event.request_hash is None else event.request_hash.value,
            result_hash=None if event.result_hash is None else event.result_hash.value,
            occurred_at=event.occurred_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _audit_from_row(row)

    async def by_correlation(self, correlation_id: CorrelationId) -> tuple[StoredAuditEvent, ...]:
        """Read one correlation timeline in immutable sequence order."""
        rows = (
            await self._session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.correlation_id == correlation_id.value)
                .order_by(AuditEventRow.sequence)
            )
        ).all()
        return tuple(_audit_from_row(row) for row in rows)


def _gate_decision_from_row(row: EvidenceGateDecisionRow) -> EvidenceGateDecision:
    reasons = tuple(
        EvidenceGateReason(
            EvidenceGateReasonCode(cast(str, value["code"])),
            cast(str, value["detail"]),
            tuple(EvidenceId(item) for item in cast(list[str], value["evidence_ids"])),
        )
        for value in row.reasons
    )
    return EvidenceGateDecision(
        incident_id=IncidentId(row.incident_id),
        candidate_id=row.candidate_id,
        outcome=EvidenceGateOutcome(row.outcome),
        reasons=reasons,
        evaluated_evidence_ids=tuple(EvidenceId(value) for value in row.evaluated_evidence_ids),
        rules_version=row.rules_version,
        input_fingerprint=Sha256Digest(row.input_fingerprint),
        evaluated_at=row.evaluated_at,
        model_confidence_basis_points=row.model_confidence_basis_points,
        schema_version=row.schema_version,
    )


class EvidenceGateRepository:
    """Persist one immutable decision and its audit binding in the caller transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        tenant_id: TenantId,
        claim: RootCauseEvidenceClaim,
        evidence: tuple[Evidence, ...],
        rules: EvidenceGateRules,
        decision: EvidenceGateDecision,
        audit_event: AuditEvent,
    ) -> EvidenceGateDecision:
        snapshot = evidence_gate_input_snapshot(
            claim,
            evidence,
            rules=rules,
            evaluated_at=decision.evaluated_at,
        )
        expected_input = evidence_gate_input_fingerprint(
            claim,
            evidence,
            rules=rules,
            evaluated_at=decision.evaluated_at,
        )
        expected_result = evidence_gate_decision_fingerprint(decision)
        evidence_ids = tuple(sorted((item.id for item in evidence), key=lambda item: item.value))
        if any(
            (item.tenant_id, item.incident_id) != (tenant_id, claim.incident_id)
            for item in evidence
        ):
            raise InvalidDomainValueError(
                "Evidence Gate decision does not match its input snapshot"
            )
        decision_binding = (
            decision.incident_id,
            decision.candidate_id,
            decision.rules_version,
            decision.model_confidence_basis_points,
            decision.evaluated_evidence_ids,
            decision.input_fingerprint,
        )
        expected_decision_binding = (
            claim.incident_id,
            claim.candidate_id,
            rules.version,
            claim.model_confidence_basis_points,
            evidence_ids,
            expected_input,
        )
        if decision_binding != expected_decision_binding:
            raise InvalidDomainValueError(
                "Evidence Gate decision does not match its input snapshot"
            )
        audit_binding = (
            audit_event.tenant_id,
            audit_event.type,
            audit_event.payload_schema_version,
            audit_event.target.type,
            audit_event.target.id.value,
            audit_event.request_hash,
            audit_event.result_hash,
            audit_event.occurred_at,
        )
        expected_audit_binding = (
            tenant_id,
            "evidence.gate_decided",
            "evidence_gate/v1",
            "evidence.gate_decision",
            decision.input_fingerprint.value,
            expected_input,
            expected_result,
            decision.evaluated_at,
        )
        if audit_binding != expected_audit_binding:
            raise InvalidDomainValueError("Evidence Gate audit event does not bind the decision")
        existing = await self._session.scalar(
            select(EvidenceGateDecisionRow).where(
                EvidenceGateDecisionRow.tenant_id == tenant_id.value,
                EvidenceGateDecisionRow.incident_id == decision.incident_id.value,
                EvidenceGateDecisionRow.candidate_id == decision.candidate_id,
                EvidenceGateDecisionRow.input_fingerprint == decision.input_fingerprint.value,
            )
        )
        if existing is not None:
            stored = _gate_decision_from_row(existing)
            if stored != decision or existing.input_snapshot != snapshot:
                raise InvalidDomainValueError(
                    "Evidence Gate input fingerprint conflicts with storage"
                )
            return stored
        self._session.add(
            EvidenceGateDecisionRow(
                tenant_id=tenant_id.value,
                incident_id=decision.incident_id.value,
                candidate_id=decision.candidate_id,
                outcome=decision.outcome.value,
                reasons=[
                    {
                        "code": reason.code.value,
                        "detail": reason.detail,
                        "evidence_ids": [item.value for item in reason.evidence_ids],
                    }
                    for reason in decision.reasons
                ],
                evaluated_evidence_ids=[item.value for item in decision.evaluated_evidence_ids],
                rules_version=decision.rules_version,
                input_fingerprint=decision.input_fingerprint.value,
                input_snapshot=snapshot,
                evaluated_at=decision.evaluated_at,
                model_confidence_basis_points=decision.model_confidence_basis_points,
                schema_version=decision.schema_version,
            )
        )
        await self._session.flush()
        await AuditRepository(self._session).append(audit_event)
        return decision

    async def get(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        candidate_id: str,
        input_fingerprint: Sha256Digest,
    ) -> EvidenceGateDecision | None:
        row = await self._session.scalar(
            select(EvidenceGateDecisionRow).where(
                EvidenceGateDecisionRow.tenant_id == tenant_id.value,
                EvidenceGateDecisionRow.incident_id == incident_id.value,
                EvidenceGateDecisionRow.candidate_id == candidate_id,
                EvidenceGateDecisionRow.input_fingerprint == input_fingerprint.value,
            )
        )
        return _gate_decision_from_row(row) if row is not None else None


def _prompt_from_row(row: PromptVersionRow) -> PromptDefinition:
    params = row.model_parameters
    compatibility = row.schema_compatibility
    trace = row.trace
    predecessor = row.rollback_predecessor
    return PromptDefinition(
        prompt_id=PromptId(row.prompt_id),
        version=SemanticVersion(row.version),
        purpose=PromptPurpose(row.purpose),
        content=row.content,
        content_fingerprint=Sha256Digest(row.content_fingerprint),
        model_parameters=PromptModelParameters(
            cast(str, params["provider"]),
            cast(str, params["model"]),
            cast(int, params["temperature_basis_points"]),
            cast(int, params["top_p_basis_points"]),
            cast(int, params["max_output_tokens"]),
            cast(int | None, params["seed"]),
        ),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion(cast(str, compatibility["input_version"])),
            SemanticVersion(cast(str, compatibility["output_version"])),
            (
                SemanticVersion(cast(str, compatibility["memory_context_version"]))
                if compatibility.get("memory_context_version") is not None
                else None
            ),
        ),
        trace=PromptTraceLink(
            ActorId(cast(str, trace["actor_id"])),
            CorrelationId(cast(str, trace["correlation_id"])),
            CausationId(cast(str, trace["causation_id"])),
            datetime.fromisoformat(cast(str, trace["created_at"])),
        ),
        status=PromptLifecycleStatus(row.status),
        rollback_predecessor=(
            None
            if predecessor is None
            else PromptVersionReference(
                PromptId(cast(str, predecessor["prompt_id"])),
                SemanticVersion(cast(str, predecessor["version"])),
            )
        ),
        schema_version=row.schema_version,
    )


def _prompt_row(tenant_id: TenantId, value: PromptDefinition) -> PromptVersionRow:
    params = value.model_parameters
    compatibility = value.schema_compatibility
    trace = value.trace
    predecessor = value.rollback_predecessor
    return PromptVersionRow(
        tenant_id=tenant_id.value,
        prompt_id=value.prompt_id.value,
        version=value.version.value,
        purpose=value.purpose.value,
        content=value.content,
        content_fingerprint=value.content_fingerprint.value,
        model_parameters={
            "provider": params.provider,
            "model": params.model,
            "temperature_basis_points": params.temperature_basis_points,
            "top_p_basis_points": params.top_p_basis_points,
            "max_output_tokens": params.max_output_tokens,
            "seed": params.seed,
        },
        schema_compatibility={
            "input_version": compatibility.input_version.value,
            "output_version": compatibility.output_version.value,
            "memory_context_version": (
                compatibility.memory_context_version.value
                if compatibility.memory_context_version is not None
                else None
            ),
        },
        trace={
            "actor_id": trace.actor_id.value,
            "correlation_id": trace.correlation_id.value,
            "causation_id": trace.causation_id.value,
            "created_at": trace.created_at.isoformat(),
        },
        status=value.status.value,
        rollback_predecessor=(
            None
            if predecessor is None
            else {"prompt_id": predecessor.prompt_id.value, "version": predecessor.version.value}
        ),
        schema_version=value.schema_version,
    )


def _prompt_state(values: tuple[PromptDefinition, ...]) -> list[dict[str, object]]:
    return [
        {
            "prompt_id": item.prompt_id.value,
            "version": item.version.value,
            "status": item.status.value,
            "content_fingerprint": item.content_fingerprint.value,
        }
        for item in values
    ]


class PromptLifecycleRepository:
    """PostgreSQL implementation of the atomic Prompt lifecycle store port."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        row = await self._session.scalar(
            select(PromptVersionRow).where(
                PromptVersionRow.tenant_id == tenant_id.value,
                PromptVersionRow.prompt_id == prompt_id.value,
                PromptVersionRow.version == version.value,
            )
        )
        return _prompt_from_row(row) if row is not None else None

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        row = await self._session.scalar(
            select(PromptVersionRow).where(
                PromptVersionRow.tenant_id == tenant_id.value,
                PromptVersionRow.prompt_id == prompt_id.value,
                PromptVersionRow.status == PromptLifecycleStatus.ACTIVE.value,
            )
        )
        return _prompt_from_row(row) if row is not None else None

    async def apply(self, change: PromptLifecycleChange, audit_event: AuditEvent) -> None:
        locked: dict[tuple[str, str], PromptVersionRow] = {}
        for expected in change.before:
            row = await self._session.scalar(
                select(PromptVersionRow)
                .where(
                    PromptVersionRow.tenant_id == audit_event.tenant_id.value,
                    PromptVersionRow.prompt_id == expected.prompt_id.value,
                    PromptVersionRow.version == expected.version.value,
                )
                .with_for_update()
            )
            if row is None or _prompt_from_row(row) != expected:
                raise InvalidDomainValueError("stale Prompt lifecycle state")
            locked[(row.prompt_id, row.version)] = row
        for value in change.after:
            row = locked.get((value.prompt_id.value, value.version.value))
            if row is None:
                self._session.add(_prompt_row(audit_event.tenant_id, value))
            else:
                row.status = value.status.value
        target = change.after[-1]
        evaluation = change.evaluation
        self._session.add(
            PromptLifecycleEventRow(
                tenant_id=audit_event.tenant_id.value,
                prompt_id=target.prompt_id.value,
                version=target.version.value,
                action=change.action,
                before_state=_prompt_state(change.before),
                after_state=_prompt_state(change.after),
                regression_evaluation=(
                    None
                    if evaluation is None
                    else {
                        "suite_version": evaluation.suite_version.value,
                        "evaluated_at": evaluation.evaluated_at.isoformat(),
                        "results": [
                            {
                                "authorization_violations": item.authorization_violations,
                                "context": item.context.value,
                                "fabricated_references": item.fabricated_references,
                                "fixture_id": item.fixture_id,
                                "ground_truth_visible": item.ground_truth_visible,
                                "passed": item.passed,
                                "unsupported_conclusions": item.unsupported_conclusions,
                            }
                            for item in evaluation.results
                        ],
                    }
                ),
                audit_event_id=audit_event.id.value,
                occurred_at=audit_event.occurred_at,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()


def _approval_from_row(row: ApprovalRow) -> Approval:
    return Approval(
        id=ApprovalId(row.id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        proposal_id=OpaqueIdentifier(row.proposal_id),
        proposal_version=row.proposal_version,
        proposal_fingerprint=Sha256Digest(row.proposal_fingerprint),
        policy_decision_id=OpaqueIdentifier(row.policy_decision_id),
        policy_decision_fingerprint=Sha256Digest(row.policy_decision_fingerprint),
        policy_input_fingerprint=Sha256Digest(row.policy_input_fingerprint),
        proposer_actor_id=ActorId(row.proposer_actor_id),
        risk_level=RiskLevel(row.risk_level),
        independent_approver_required=row.independent_approver_required,
        status=ApprovalStatus(row.status),
        version=AggregateVersion(row.version),
        requested_at=row.requested_at,
        expires_at=row.expires_at,
        decided_at=row.decided_at,
        decided_by=None if row.decided_by is None else ActorId(row.decided_by),
        decision_reason=(None if row.decision_reason is None else EventReason(row.decision_reason)),
        schema_version=row.schema_version,
    )


def _approval_row(value: Approval) -> ApprovalRow:
    return ApprovalRow(
        id=value.id.value,
        tenant_id=value.tenant_id.value,
        incident_id=value.incident_id.value,
        proposal_id=value.proposal_id.value,
        proposal_version=value.proposal_version,
        proposal_fingerprint=value.proposal_fingerprint.value,
        policy_decision_id=value.policy_decision_id.value,
        policy_decision_fingerprint=value.policy_decision_fingerprint.value,
        policy_input_fingerprint=value.policy_input_fingerprint.value,
        proposer_actor_id=value.proposer_actor_id.value,
        risk_level=value.risk_level.value,
        independent_approver_required=value.independent_approver_required,
        status=value.status.value,
        version=value.version.value,
        requested_at=value.requested_at,
        expires_at=value.expires_at,
        decided_at=value.decided_at,
        decided_by=None if value.decided_by is None else value.decided_by.value,
        decision_reason=(None if value.decision_reason is None else value.decision_reason.value),
        schema_version=value.schema_version,
    )


def _approval_state(value: Approval | None) -> dict[str, object] | None:
    if value is None:
        return None
    return {
        "fingerprint": value.fingerprint.value,
        "status": value.status.value,
        "version": value.version.value,
    }


def _approval_binding(value: Approval) -> tuple[object, ...]:
    return (
        value.id,
        value.tenant_id,
        value.incident_id,
        value.proposal_id,
        value.proposal_version,
        value.proposal_fingerprint,
        value.policy_decision_id,
        value.policy_decision_fingerprint,
        value.policy_input_fingerprint,
        value.proposer_actor_id,
        value.risk_level,
        value.independent_approver_required,
        value.requested_at,
        value.expires_at,
        value.schema_version,
    )


def _validate_approval_change(
    change: ApprovalLifecycleChange,
    audit_event: AuditEvent,
) -> None:
    expected_status = {
        "approved": ApprovalStatus.APPROVED,
        "rejected": ApprovalStatus.REJECTED,
        "expired": ApprovalStatus.EXPIRED,
    }
    if change.before is None:
        valid_transition = (
            change.action == "requested"
            and change.after.status is ApprovalStatus.PENDING
            and change.after.version == AggregateVersion.initial()
        )
        request_hash = change.after.policy_decision_fingerprint
    else:
        valid_transition = (
            change.before.status is ApprovalStatus.PENDING
            and expected_status.get(change.action) is change.after.status
            and change.after.version == change.before.version.next()
            and _approval_binding(change.before) == _approval_binding(change.after)
        )
        request_hash = change.before.fingerprint
    expected_time = (
        change.after.requested_at
        if change.before is None
        else change.after.decided_at or change.after.requested_at
    )
    if not valid_transition:
        raise InvalidDomainValueError("invalid Approval lifecycle transition")
    if (
        audit_event.tenant_id != change.after.tenant_id
        or audit_event.type != f"approval.{change.action}"
        or audit_event.target
        != AuditTarget("approval.record", OpaqueIdentifier(change.after.id.value))
        or audit_event.request_hash != request_hash
        or audit_event.result_hash != change.after.fingerprint
        or audit_event.occurred_at != expected_time
    ):
        raise InvalidDomainValueError("Approval lifecycle audit event is not bound to the change")


class ApprovalLifecycleRepository:
    """PostgreSQL implementation of atomic Approval state and audit persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None:
        row = await self._session.scalar(
            select(ApprovalRow).where(
                ApprovalRow.id == approval_id.value,
                ApprovalRow.tenant_id == tenant_id.value,
            )
        )
        return None if row is None else _approval_from_row(row)

    async def apply(
        self,
        change: ApprovalLifecycleChange,
        audit_event: AuditEvent,
    ) -> None:
        _validate_approval_change(change, audit_event)
        row = await self._session.scalar(
            select(ApprovalRow)
            .where(
                ApprovalRow.id == change.after.id.value,
                ApprovalRow.tenant_id == change.after.tenant_id.value,
            )
            .with_for_update()
        )
        if change.before is None:
            if row is not None:
                raise InvalidDomainValueError("Approval already exists")
            self._session.add(_approval_row(change.after))
            await self._session.flush()
        else:
            if row is None or _approval_from_row(row) != change.before:
                raise InvalidDomainValueError("stale Approval lifecycle state")
            row.status = change.after.status.value
            row.version = change.after.version.value
            row.decided_at = change.after.decided_at
            row.decided_by = (
                None if change.after.decided_by is None else change.after.decided_by.value
            )
            row.decision_reason = (
                None if change.after.decision_reason is None else change.after.decision_reason.value
            )
        self._session.add(
            ApprovalLifecycleEventRow(
                tenant_id=change.after.tenant_id.value,
                approval_id=change.after.id.value,
                action=change.action,
                before_state=_approval_state(change.before),
                after_state=cast(dict[str, object], _approval_state(change.after)),
                audit_event_id=audit_event.id.value,
                occurred_at=audit_event.occurred_at,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()

    async def get_invalidation(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
    ) -> ApprovalInvalidation | None:
        row = await self._session.scalar(
            select(ApprovalInvalidationRow).where(
                ApprovalInvalidationRow.approval_id == approval_id.value,
                ApprovalInvalidationRow.tenant_id == tenant_id.value,
            )
        )
        if row is None:
            return None
        return ApprovalInvalidation(
            approval_id=ApprovalId(row.approval_id),
            tenant_id=TenantId(row.tenant_id),
            incident_id=IncidentId(row.incident_id),
            approval_fingerprint=Sha256Digest(row.approval_fingerprint),
            prior_proposal_fingerprint=Sha256Digest(row.prior_proposal_fingerprint),
            replacement_proposal_id=OpaqueIdentifier(row.replacement_proposal_id),
            replacement_proposal_version=row.replacement_proposal_version,
            replacement_proposal_fingerprint=Sha256Digest(row.replacement_proposal_fingerprint),
            replacement_material_fingerprint=Sha256Digest(row.replacement_material_fingerprint),
            invalidated_by=ActorId(row.invalidated_by),
            invalidated_at=row.invalidated_at,
            schema_version=row.schema_version,
        )

    async def record_invalidation(
        self,
        approval: Approval,
        invalidation: ApprovalInvalidation,
        audit_event: AuditEvent,
    ) -> None:
        row = await self._session.scalar(
            select(ApprovalRow)
            .where(
                ApprovalRow.id == approval.id.value,
                ApprovalRow.tenant_id == approval.tenant_id.value,
            )
            .with_for_update()
        )
        if row is None or _approval_from_row(row) != approval:
            raise InvalidDomainValueError("stale Approval invalidation state")
        existing = await self.get_invalidation(approval.id, tenant_id=approval.tenant_id)
        if existing is not None:
            raise InvalidDomainValueError("Approval is already invalidated")
        if (
            invalidation.approval_id != approval.id
            or invalidation.tenant_id != approval.tenant_id
            or invalidation.incident_id != approval.incident_id
            or invalidation.approval_fingerprint != approval.fingerprint
            or invalidation.prior_proposal_fingerprint != approval.proposal_fingerprint
            or audit_event.tenant_id != approval.tenant_id
            or audit_event.type != "approval.invalidated"
            or audit_event.target
            != AuditTarget("approval.record", OpaqueIdentifier(approval.id.value))
            or audit_event.occurred_at != invalidation.invalidated_at
            or audit_event.request_hash != approval.fingerprint
            or audit_event.result_hash != invalidation.fingerprint
        ):
            raise InvalidDomainValueError("Approval invalidation is not hash-bound")
        self._session.add(
            ApprovalInvalidationRow(
                approval_id=invalidation.approval_id.value,
                tenant_id=invalidation.tenant_id.value,
                incident_id=invalidation.incident_id.value,
                approval_fingerprint=invalidation.approval_fingerprint.value,
                prior_proposal_fingerprint=invalidation.prior_proposal_fingerprint.value,
                replacement_proposal_id=invalidation.replacement_proposal_id.value,
                replacement_proposal_version=invalidation.replacement_proposal_version,
                replacement_proposal_fingerprint=(
                    invalidation.replacement_proposal_fingerprint.value
                ),
                replacement_material_fingerprint=(
                    invalidation.replacement_material_fingerprint.value
                ),
                invalidated_by=invalidation.invalidated_by.value,
                invalidated_at=invalidation.invalidated_at,
                audit_event_id=audit_event.id.value,
                schema_version=invalidation.schema_version,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()


def _action_snapshot_from_row(
    row: ActionExecutionRow,
    *,
    after: bool,
) -> ActionSnapshot | None:
    artifact_id = row.after_artifact_id if after else row.before_artifact_id
    if artifact_id is None:
        return None
    content_hash = row.after_content_hash if after else row.before_content_hash
    deployed_version = row.after_version if after else row.expected_current_version
    observed_at = row.after_observed_at if after else row.before_observed_at
    assert content_hash is not None and deployed_version is not None and observed_at is not None
    return ActionSnapshot(
        artifact_id=ArtifactId(artifact_id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        service=row.target_service,
        environment=PolicyEnvironment(row.target_environment),
        target_reference=OpaqueIdentifier(row.target_reference),
        deployed_version=SemanticVersion(deployed_version),
        observed_at=observed_at,
        content_hash=Sha256Digest(content_hash),
    )


def _action_execution_from_row(row: ActionExecutionRow) -> ActionExecution:
    before = _action_snapshot_from_row(row, after=False)
    assert before is not None
    execution = ActionExecution(
        id=OpaqueIdentifier(row.id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        approval_id=ApprovalId(row.approval_id),
        idempotency_key=IdempotencyKey(row.idempotency_key),
        actor_id=ActorId(row.actor_id),
        proposal_fingerprint=Sha256Digest(row.proposal_fingerprint),
        policy_decision_fingerprint=Sha256Digest(row.policy_decision_fingerprint),
        target=ResolvedRollbackTarget(
            tenant_id=TenantId(row.tenant_id),
            service=row.target_service,
            environment=PolicyEnvironment(row.target_environment),
            target_reference=OpaqueIdentifier(row.target_reference),
            expected_current_version=SemanticVersion(row.expected_current_version),
            stable_version=SemanticVersion(row.stable_version),
        ),
        before_snapshot=before,
        status=ActionExecutionStatus(row.status),
        version=AggregateVersion(row.version),
        started_at=row.started_at,
        completed_at=row.completed_at,
        after_snapshot=_action_snapshot_from_row(row, after=True),
        failure_code=row.failure_code,
        schema_version=row.schema_version,
    )
    if execution.request_fingerprint.value != row.request_fingerprint:
        raise InvalidDomainValueError("stored action execution request fingerprint is invalid")
    return execution


def _action_target_key(execution: ActionExecution) -> Sha256Digest:
    canonical = json.dumps(
        {
            "environment": execution.target.environment.value,
            "service": execution.target.service,
            "target_reference": execution.target.target_reference.value,
            "tenant_id": execution.tenant_id.value,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())


def _validate_action_audit(
    execution: ActionExecution,
    audit_event: AuditEvent,
    *,
    event_type: str,
    request_hash: Sha256Digest,
    result_hash: Sha256Digest,
) -> None:
    if (
        audit_event.tenant_id != execution.tenant_id
        or audit_event.type != event_type
        or audit_event.target != AuditTarget("action.execution", execution.id)
        or audit_event.actor_id != execution.actor_id
        or audit_event.request_hash != request_hash
        or audit_event.result_hash != result_hash
    ):
        raise InvalidDomainValueError("action execution audit event is not hash-bound")


class ActionExecutionRepository:
    """Serialize target claims and atomically persist replayable action results."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        execution_id: OpaqueIdentifier,
        *,
        tenant_id: TenantId,
    ) -> ActionExecution | None:
        row = await self._session.scalar(
            select(ActionExecutionRow).where(
                ActionExecutionRow.id == execution_id.value,
                ActionExecutionRow.tenant_id == tenant_id.value,
            )
        )
        return None if row is None else _action_execution_from_row(row)

    async def claim(
        self,
        execution: ActionExecution,
        audit_event: AuditEvent,
    ) -> tuple[ActionExecution, bool]:
        if execution.status is not ActionExecutionStatus.STARTED:
            raise InvalidDomainValueError("only a started action execution can be claimed")
        _validate_action_audit(
            execution,
            audit_event,
            event_type="action.execution_started",
            request_hash=execution.request_fingerprint,
            result_hash=execution.fingerprint,
        )
        target_key = _action_target_key(execution)
        lock_values = sorted(
            (
                target_key.value,
                hashlib.sha256(
                    (
                        f"{execution.tenant_id.value}:{execution.actor_id.value}:"
                        f"{execution.incident_id.value}:{execution.idempotency_key.value}"
                    ).encode()
                ).hexdigest(),
            )
        )
        for value in lock_values:
            lock_key = int.from_bytes(bytes.fromhex(value[:16]), signed=True)
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
            )
        existing = await self._session.scalar(
            select(ActionExecutionRow)
            .where(
                ActionExecutionRow.tenant_id == execution.tenant_id.value,
                ActionExecutionRow.actor_id == execution.actor_id.value,
                ActionExecutionRow.incident_id == execution.incident_id.value,
                ActionExecutionRow.idempotency_key == execution.idempotency_key.value,
            )
            .with_for_update()
        )
        if existing is not None:
            stored = _action_execution_from_row(existing)
            if stored.request_fingerprint != execution.request_fingerprint:
                raise InvalidDomainValueError(
                    "action idempotency key was reused with a different request"
                )
            return stored, True
        active_lock = await self._session.get(
            ActionExecutionLockRow,
            target_key.value,
            with_for_update=True,
        )
        if active_lock is not None:
            raise InvalidDomainValueError("rollback target already has an active execution")
        approval_execution = await self._session.scalar(
            select(ActionExecutionRow.id).where(
                ActionExecutionRow.tenant_id == execution.tenant_id.value,
                ActionExecutionRow.approval_id == execution.approval_id.value,
            )
        )
        if approval_execution is not None:
            raise InvalidDomainValueError("Approval already has an action execution")
        before = execution.before_snapshot
        target = execution.target
        execution_row = ActionExecutionRow(
            id=execution.id.value,
            tenant_id=execution.tenant_id.value,
            incident_id=execution.incident_id.value,
            approval_id=execution.approval_id.value,
            idempotency_key=execution.idempotency_key.value,
            actor_id=execution.actor_id.value,
            proposal_fingerprint=execution.proposal_fingerprint.value,
            policy_decision_fingerprint=execution.policy_decision_fingerprint.value,
            request_fingerprint=execution.request_fingerprint.value,
            target_service=target.service,
            target_environment=target.environment.value,
            target_reference=target.target_reference.value,
            expected_current_version=target.expected_current_version.value,
            stable_version=target.stable_version.value,
            before_artifact_id=before.artifact_id.value,
            before_content_hash=before.content_hash.value,
            before_observed_at=before.observed_at,
            status=execution.status.value,
            version=execution.version.value,
            started_at=execution.started_at,
            completed_at=None,
            after_artifact_id=None,
            after_content_hash=None,
            after_version=None,
            after_observed_at=None,
            failure_code=None,
            schema_version=execution.schema_version,
        )
        self._session.add(execution_row)
        await self._session.flush()
        self._session.add(
            ActionExecutionLockRow(
                target_key=target_key.value,
                execution_id=execution.id.value,
                tenant_id=execution.tenant_id.value,
                service=target.service,
                environment=target.environment.value,
                target_reference=target.target_reference.value,
                acquired_at=execution.started_at,
            )
        )
        self._session.add(
            ActionExecutionEventRow(
                tenant_id=execution.tenant_id.value,
                execution_id=execution.id.value,
                action="STARTED",
                before_fingerprint=None,
                after_fingerprint=execution.fingerprint.value,
                audit_event_id=audit_event.id.value,
                occurred_at=execution.started_at,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()
        return execution, False

    async def finish(
        self,
        expected: ActionExecution,
        completed: ActionExecution,
        audit_event: AuditEvent,
    ) -> ActionExecution:
        if expected.status is not ActionExecutionStatus.STARTED:
            raise InvalidDomainValueError("expected action execution must be started")
        reconstructed = replace(
            completed,
            status=ActionExecutionStatus.STARTED,
            version=expected.version,
            completed_at=None,
            after_snapshot=None,
            failure_code=None,
        )
        if reconstructed != expected:
            raise InvalidDomainValueError("completed action execution immutable fields changed")
        _validate_action_audit(
            completed,
            audit_event,
            event_type="action.execution_finished",
            request_hash=expected.fingerprint,
            result_hash=completed.fingerprint,
        )
        row = await self._session.scalar(
            select(ActionExecutionRow)
            .where(
                ActionExecutionRow.id == expected.id.value,
                ActionExecutionRow.tenant_id == expected.tenant_id.value,
            )
            .with_for_update()
        )
        if row is None:
            raise InvalidDomainValueError("action execution was not claimed")
        stored = _action_execution_from_row(row)
        if stored.status is not ActionExecutionStatus.STARTED:
            if stored == completed:
                return stored
            raise InvalidDomainValueError("action execution already has a different result")
        if stored != expected:
            raise InvalidDomainValueError("stale action execution state")
        after = completed.after_snapshot
        row.status = completed.status.value
        row.version = completed.version.value
        row.completed_at = completed.completed_at
        row.after_artifact_id = None if after is None else after.artifact_id.value
        row.after_content_hash = None if after is None else after.content_hash.value
        row.after_version = None if after is None else after.deployed_version.value
        row.after_observed_at = None if after is None else after.observed_at
        row.failure_code = completed.failure_code
        target_key = _action_target_key(expected)
        deleted = cast(
            CursorResult[Any],
            await self._session.execute(
                delete(ActionExecutionLockRow).where(
                    ActionExecutionLockRow.target_key == target_key.value,
                    ActionExecutionLockRow.execution_id == expected.id.value,
                )
            ),
        )
        if deleted.rowcount != 1:
            raise InvalidDomainValueError("action execution target lock is missing")
        self._session.add(
            ActionExecutionEventRow(
                tenant_id=completed.tenant_id.value,
                execution_id=completed.id.value,
                action=completed.status.value,
                before_fingerprint=expected.fingerprint.value,
                after_fingerprint=completed.fingerprint.value,
                audit_event_id=audit_event.id.value,
                occurred_at=cast(datetime, completed.completed_at),
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()
        return completed

    async def record_replay(
        self,
        incoming: ActionExecution,
        stored: ActionExecution,
        audit_event: AuditEvent,
    ) -> None:
        if incoming.request_fingerprint != stored.request_fingerprint:
            raise InvalidDomainValueError("action replay request does not match stored execution")
        _validate_action_audit(
            replace(incoming, id=stored.id),
            audit_event,
            event_type="action.execution_replayed",
            request_hash=incoming.request_fingerprint,
            result_hash=stored.fingerprint,
        )
        row = await self._session.scalar(
            select(ActionExecutionRow)
            .where(
                ActionExecutionRow.id == stored.id.value,
                ActionExecutionRow.tenant_id == stored.tenant_id.value,
            )
            .with_for_update()
        )
        if row is None or _action_execution_from_row(row) != stored:
            raise InvalidDomainValueError("stored action replay result is unavailable or stale")
        self._session.add(
            ActionExecutionEventRow(
                tenant_id=stored.tenant_id.value,
                execution_id=stored.id.value,
                action="REPLAYED",
                before_fingerprint=incoming.fingerprint.value,
                after_fingerprint=stored.fingerprint.value,
                audit_event_id=audit_event.id.value,
                occurred_at=audit_event.occurred_at,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()


def _health_verification_from_row(
    row: HealthVerificationRunRow,
) -> tuple[HealthVerificationObservation, HealthVerificationDecision]:
    observation = HealthVerificationObservation(
        id=OpaqueIdentifier(row.observation_id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        action_execution_id=OpaqueIdentifier(row.action_execution_id),
        service=row.service,
        environment=PolicyEnvironment(row.environment),
        expected_stable_version=SemanticVersion(row.expected_stable_version),
        window_started_at=row.window_started_at,
        window_ended_at=row.window_ended_at,
        samples=tuple(
            HealthVerificationSample(
                observed_at=datetime.fromisoformat(cast(str, item["observed_at"])),
                error_rate_basis_points=cast(int, item["error_rate_basis_points"]),
                p95_latency_ms=cast(int, item["p95_latency_ms"]),
                health_endpoint_healthy=cast(bool, item["health_endpoint_healthy"]),
                deployed_version=SemanticVersion(cast(str, item["deployed_version"])),
                new_alert_count=cast(int, item["new_alert_count"]),
            )
            for item in row.samples
        ),
        error_rate_evidence_id=EvidenceId(row.error_rate_evidence_id),
        p95_latency_evidence_id=EvidenceId(row.p95_latency_evidence_id),
        health_endpoint_evidence_id=EvidenceId(row.health_endpoint_evidence_id),
        deployed_version_evidence_id=EvidenceId(row.deployed_version_evidence_id),
        new_alerts_evidence_id=EvidenceId(row.new_alerts_evidence_id),
        collected_at=row.collected_at,
        expires_at=row.expires_at,
        schema_version=row.schema_version,
    )
    decision = HealthVerificationDecision(
        id=OpaqueIdentifier(row.id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        action_execution_id=OpaqueIdentifier(row.action_execution_id),
        scenario=HealthVerificationScenario(row.scenario),
        outcome=HealthVerificationOutcome(row.outcome),
        reasons=tuple(HealthVerificationReasonCode(item) for item in row.reasons),
        criteria_fingerprint=Sha256Digest(row.criteria_fingerprint),
        observation_fingerprint=Sha256Digest(row.observation_fingerprint),
        execution_fingerprint=Sha256Digest(row.execution_fingerprint),
        input_fingerprint=Sha256Digest(row.input_fingerprint),
        evaluated_at=row.evaluated_at,
        rules_version=SemanticVersion(row.rules_version),
        schema_version=row.schema_version,
    )
    if observation.fingerprint.value != row.observation_fingerprint:
        raise InvalidDomainValueError("stored health verification observation is corrupted")
    if decision.fingerprint.value != row.decision_fingerprint:
        raise InvalidDomainValueError("stored health verification decision is corrupted")
    return observation, decision


class HealthVerificationRepository:
    """Persist one immutable evidence-bound verifier result and append-only audit event."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        execution: ActionExecution,
        criteria: HealthVerificationCriteria,
        observation: HealthVerificationObservation,
        decision: HealthVerificationDecision,
        audit_event: AuditEvent,
    ) -> tuple[HealthVerificationObservation, HealthVerificationDecision]:
        expected = evaluate_health_verification(
            execution,
            criteria,
            observation,
            decision_id=decision.id,
            evaluated_at=decision.evaluated_at,
        )
        if expected != decision:
            raise InvalidDomainValueError("health verification decision is not reproducible")
        audit_binding = (
            audit_event.tenant_id,
            audit_event.type,
            audit_event.payload_schema_version,
            audit_event.target,
            audit_event.request_hash,
            audit_event.result_hash,
            audit_event.occurred_at,
        )
        if audit_binding != (
            decision.tenant_id,
            "health.verification_decided",
            "health_verification/v1",
            AuditTarget("health.verification", decision.id),
            decision.input_fingerprint,
            decision.fingerprint,
            decision.evaluated_at,
        ):
            raise InvalidDomainValueError("health verification audit event is not hash-bound")
        stored_execution = await self._session.scalar(
            select(ActionExecutionRow).where(
                ActionExecutionRow.id == execution.id.value,
                ActionExecutionRow.tenant_id == execution.tenant_id.value,
                ActionExecutionRow.incident_id == execution.incident_id.value,
            )
        )
        if stored_execution is None or _action_execution_from_row(stored_execution) != execution:
            raise InvalidDomainValueError("successful action execution is not durably available")
        evidence_ids = (
            observation.error_rate_evidence_id,
            observation.p95_latency_evidence_id,
            observation.health_endpoint_evidence_id,
            observation.deployed_version_evidence_id,
            observation.new_alerts_evidence_id,
        )
        persisted_ids = set(
            (
                await self._session.scalars(
                    select(EvidenceRow.id).where(
                        EvidenceRow.tenant_id == observation.tenant_id.value,
                        EvidenceRow.incident_id == observation.incident_id.value,
                        EvidenceRow.id.in_(item.value for item in evidence_ids),
                    )
                )
            ).all()
        )
        if persisted_ids != {item.value for item in evidence_ids}:
            raise InvalidDomainValueError("health verification Evidence is not durably available")
        existing = await self._session.scalar(
            select(HealthVerificationRunRow).where(
                HealthVerificationRunRow.tenant_id == decision.tenant_id.value,
                or_(
                    HealthVerificationRunRow.id == decision.id.value,
                    HealthVerificationRunRow.observation_id == observation.id.value,
                    (
                        (HealthVerificationRunRow.action_execution_id == execution.id.value)
                        & (
                            HealthVerificationRunRow.input_fingerprint
                            == decision.input_fingerprint.value
                        )
                    ),
                ),
            )
        )
        if existing is not None:
            stored = _health_verification_from_row(existing)
            if stored != (observation, decision):
                raise InvalidDomainValueError("health verification identity conflicts with storage")
            return stored
        self._session.add(
            HealthVerificationRunRow(
                id=decision.id.value,
                tenant_id=decision.tenant_id.value,
                incident_id=decision.incident_id.value,
                action_execution_id=decision.action_execution_id.value,
                observation_id=observation.id.value,
                scenario=decision.scenario.value,
                service=observation.service,
                environment=observation.environment.value,
                expected_stable_version=observation.expected_stable_version.value,
                window_started_at=observation.window_started_at,
                window_ended_at=observation.window_ended_at,
                samples=[
                    {
                        "observed_at": item.observed_at.isoformat(),
                        "error_rate_basis_points": item.error_rate_basis_points,
                        "p95_latency_ms": item.p95_latency_ms,
                        "health_endpoint_healthy": item.health_endpoint_healthy,
                        "deployed_version": item.deployed_version.value,
                        "new_alert_count": item.new_alert_count,
                    }
                    for item in observation.samples
                ],
                error_rate_evidence_id=observation.error_rate_evidence_id.value,
                p95_latency_evidence_id=observation.p95_latency_evidence_id.value,
                health_endpoint_evidence_id=observation.health_endpoint_evidence_id.value,
                deployed_version_evidence_id=observation.deployed_version_evidence_id.value,
                new_alerts_evidence_id=observation.new_alerts_evidence_id.value,
                collected_at=observation.collected_at,
                expires_at=observation.expires_at,
                outcome=decision.outcome.value,
                reasons=[item.value for item in decision.reasons],
                criteria_fingerprint=decision.criteria_fingerprint.value,
                observation_fingerprint=decision.observation_fingerprint.value,
                execution_fingerprint=decision.execution_fingerprint.value,
                input_fingerprint=decision.input_fingerprint.value,
                decision_fingerprint=decision.fingerprint.value,
                evaluated_at=decision.evaluated_at,
                rules_version=decision.rules_version.value,
                schema_version=decision.schema_version,
            )
        )
        await self._session.flush()
        await AuditRepository(self._session).append(audit_event)
        return observation, decision

    async def get(
        self,
        decision_id: OpaqueIdentifier,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
    ) -> tuple[HealthVerificationObservation, HealthVerificationDecision] | None:
        row = await self._session.scalar(
            select(HealthVerificationRunRow).where(
                HealthVerificationRunRow.id == decision_id.value,
                HealthVerificationRunRow.tenant_id == tenant_id.value,
                HealthVerificationRunRow.incident_id == incident_id.value,
            )
        )
        return None if row is None else _health_verification_from_row(row)

    async def resolve_and_close(
        self,
        decision: HealthVerificationDecision,
        *,
        metadata: EventMetadata,
        audit_event: AuditEvent,
    ) -> Incident:
        """Atomically apply an idempotent PASS route through RESOLVED to CLOSED."""
        if not isinstance(decision, HealthVerificationDecision) or not isinstance(
            metadata, EventMetadata
        ):
            raise InvalidDomainValueError("health verification closure inputs are invalid")
        row = await self._session.scalar(
            select(HealthVerificationRunRow)
            .where(
                HealthVerificationRunRow.id == decision.id.value,
                HealthVerificationRunRow.tenant_id == decision.tenant_id.value,
                HealthVerificationRunRow.incident_id == decision.incident_id.value,
            )
            .with_for_update()
        )
        if row is None or _health_verification_from_row(row)[1] != decision:
            raise InvalidDomainValueError("passing health verification is not durably available")
        if decision.outcome is not HealthVerificationOutcome.PASS:
            raise InvalidDomainValueError(
                "only a passing health verification can close an Incident"
            )

        incident_row = await self._session.scalar(
            select(IncidentRow)
            .where(
                IncidentRow.id == decision.incident_id.value,
                IncidentRow.tenant_id == decision.tenant_id.value,
            )
            .with_for_update()
        )
        if incident_row is None:  # pragma: no cover - protected by the verification Incident FK
            raise InvalidDomainValueError("health verification Incident is not durably available")
        incident = _incident_from_row(incident_row)
        prior_route = tuple(
            (
                await self._session.scalars(
                    select(IncidentTransitionRow)
                    .where(
                        IncidentTransitionRow.incident_id == decision.incident_id.value,
                        IncidentTransitionRow.causation_id == decision.id.value,
                    )
                    .order_by(IncidentTransitionRow.new_version)
                )
            ).all()
        )
        if prior_route:
            valid_replay = (
                incident.state is IncidentState.CLOSED
                and len(prior_route) == 2
                and prior_route[0].prior_state == IncidentState.VERIFYING.value
                and prior_route[0].new_state == IncidentState.RESOLVED.value
                and prior_route[1].prior_state == IncidentState.RESOLVED.value
                and prior_route[1].new_state == IncidentState.CLOSED.value
                and prior_route[1].prior_version == prior_route[0].new_version
            )
            if not valid_replay:
                raise InvalidDomainValueError("stored health verification closure route is invalid")
            return incident
        if incident.state is not IncidentState.VERIFYING:
            raise InvalidDomainValueError("health verification Incident is not in VERIFYING")
        audit_binding = (
            audit_event.tenant_id,
            audit_event.type,
            audit_event.payload_schema_version,
            audit_event.actor_id,
            audit_event.correlation_id,
            audit_event.causation_id,
            audit_event.target,
            audit_event.occurred_at,
            audit_event.request_hash,
            audit_event.result_hash,
        )
        if audit_binding != (
            decision.tenant_id,
            "health.verification_succeeded",
            HEALTH_VERIFICATION_CLOSURE_AUDIT_SCHEMA_VERSION,
            metadata.actor_id,
            metadata.correlation_id,
            metadata.causation_id,
            AuditTarget("incident.lifecycle", decision.incident_id),
            metadata.occurred_at,
            decision.fingerprint,
            health_verification_closure_fingerprint(decision),
        ) or metadata.causation_id != CausationId(decision.id.value):
            raise InvalidDomainValueError("health verification closure audit is not hash-bound")

        repository = IncidentRepository(self._session)
        resolved_change = incident.transition(
            IncidentState.RESOLVED,
            expected_version=incident.version,
            metadata=metadata,
        )
        await repository.apply(resolved_change)
        resolved = resolved_change.incident
        closed_change = resolved.transition(
            IncidentState.CLOSED,
            expected_version=resolved.version,
            metadata=metadata,
        )
        await repository.apply(closed_change)
        await AuditRepository(self._session).append(audit_event)
        return closed_change.incident


def _model_call_from_row(row: ModelCallTraceRow) -> ModelCallTrace:
    usage = (
        None
        if row.input_tokens is None
        else ModelTokenUsage(
            row.input_tokens,
            cast(int, row.output_tokens),
            cast(int, row.cached_input_tokens),
            cast(int, row.reasoning_tokens),
            cast(int, row.total_tokens),
        )
    )
    cost = (
        None
        if row.cost_nanounits is None
        else ModelCost(
            row.cost_nanounits,
            cast(str, row.currency),
            ModelCostSource(cast(str, row.cost_source)),
            SemanticVersion(cast(str, row.rate_card_version)),
        )
    )
    metering = (
        None
        if row.status == ModelCallStatus.STARTED.value
        else ModelMetering(
            usage,
            cost,
            (
                None
                if row.metering_unavailable_reason is None
                else ModelMeteringUnavailableReason(row.metering_unavailable_reason)
            ),
        )
    )
    return ModelCallTrace(
        id=ModelCallId(row.id),
        tenant_id=TenantId(row.tenant_id),
        incident_id=IncidentId(row.incident_id),
        workflow_run_id=WorkflowRunId(row.workflow_run_id),
        node=row.node,
        attempt=row.attempt,
        prompt=PromptVersionReference(PromptId(row.prompt_id), SemanticVersion(row.prompt_version)),
        prompt_fingerprint=Sha256Digest(row.prompt_fingerprint),
        provider=row.provider,
        model=row.model,
        temperature_basis_points=row.temperature_basis_points,
        top_p_basis_points=row.top_p_basis_points,
        max_output_tokens=row.max_output_tokens,
        seed=row.seed,
        input_schema_version=SemanticVersion(row.input_schema_version),
        output_schema_version=SemanticVersion(row.output_schema_version),
        request_hash=Sha256Digest(row.request_hash),
        response_hash=(Sha256Digest(row.response_hash) if row.response_hash is not None else None),
        correlation_id=CorrelationId(row.correlation_id),
        causation_id=CausationId(row.causation_id),
        status=ModelCallStatus(row.status),
        started_at=row.started_at,
        completed_at=row.completed_at,
        metering=metering,
        failure_code=row.failure_code,
        schema_version=row.schema_version,
    )


def _validate_model_call_audit(
    trace: ModelCallTrace,
    audit_event: AuditEvent,
    *,
    event_type: str,
    request_hash: Sha256Digest,
    result_hash: Sha256Digest,
) -> None:
    if (
        audit_event.tenant_id != trace.tenant_id
        or audit_event.type != event_type
        or audit_event.target.type != "model.call"
        or audit_event.target.id.value != trace.id.value
        or audit_event.correlation_id != trace.correlation_id
        or audit_event.causation_id != trace.causation_id
        or audit_event.request_hash != request_hash
        or audit_event.result_hash != result_hash
    ):
        raise InvalidDomainValueError("model call audit event is not bound to the trace")


class ModelCallTraceRepository:
    """Persist content-free start/finish traces and audit in caller-owned transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: TenantId, call_id: ModelCallId) -> ModelCallTrace | None:
        row = await self._session.scalar(
            select(ModelCallTraceRow).where(
                ModelCallTraceRow.tenant_id == tenant_id.value,
                ModelCallTraceRow.id == call_id.value,
            )
        )
        return _model_call_from_row(row) if row is not None else None

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        fingerprint = model_call_trace_fingerprint(trace)
        _validate_model_call_audit(
            trace,
            audit_event,
            event_type="model.call_started",
            request_hash=fingerprint,
            result_hash=fingerprint,
        )
        prompt_row = await self._session.scalar(
            select(PromptVersionRow)
            .where(
                PromptVersionRow.tenant_id == trace.tenant_id.value,
                PromptVersionRow.prompt_id == trace.prompt.prompt_id.value,
                PromptVersionRow.version == trace.prompt.version.value,
            )
            .with_for_update(read=True)
        )
        if prompt_row is None:
            raise InvalidDomainValueError("model call Prompt version is not registered")
        prompt = _prompt_from_row(prompt_row)
        params = prompt.model_parameters
        schemas = prompt.schema_compatibility
        if (
            prompt.status is not PromptLifecycleStatus.ACTIVE
            or trace.prompt_fingerprint != prompt.content_fingerprint
            or trace.provider != params.provider
            or trace.model != params.model
            or trace.temperature_basis_points != params.temperature_basis_points
            or trace.top_p_basis_points != params.top_p_basis_points
            or trace.max_output_tokens != params.max_output_tokens
            or trace.seed != params.seed
            or trace.input_schema_version != schemas.input_version
            or trace.output_schema_version != schemas.output_version
        ):
            raise InvalidDomainValueError("model call metadata does not match the active Prompt")
        self._session.add(
            ModelCallTraceRow(
                id=trace.id.value,
                tenant_id=trace.tenant_id.value,
                incident_id=trace.incident_id.value,
                workflow_run_id=trace.workflow_run_id.value,
                node=trace.node,
                attempt=trace.attempt,
                prompt_id=trace.prompt.prompt_id.value,
                prompt_version=trace.prompt.version.value,
                prompt_fingerprint=trace.prompt_fingerprint.value,
                provider=trace.provider,
                model=trace.model,
                temperature_basis_points=trace.temperature_basis_points,
                top_p_basis_points=trace.top_p_basis_points,
                max_output_tokens=trace.max_output_tokens,
                seed=trace.seed,
                input_schema_version=trace.input_schema_version.value,
                output_schema_version=trace.output_schema_version.value,
                request_hash=trace.request_hash.value,
                response_hash=None,
                correlation_id=trace.correlation_id.value,
                causation_id=trace.causation_id.value,
                status=trace.status.value,
                started_at=trace.started_at,
                completed_at=None,
                input_tokens=None,
                output_tokens=None,
                cached_input_tokens=None,
                reasoning_tokens=None,
                total_tokens=None,
                cost_nanounits=None,
                currency=None,
                cost_source=None,
                rate_card_version=None,
                metering_unavailable_reason=None,
                failure_code=None,
                schema_version=trace.schema_version,
            )
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()

    async def finish(
        self,
        expected: ModelCallTrace,
        completed: ModelCallTrace,
        audit_event: AuditEvent,
    ) -> None:
        _validate_model_call_audit(
            completed,
            audit_event,
            event_type="model.call_finished",
            request_hash=model_call_trace_fingerprint(expected),
            result_hash=model_call_trace_fingerprint(completed),
        )
        row = await self._session.scalar(
            select(ModelCallTraceRow)
            .where(
                ModelCallTraceRow.tenant_id == expected.tenant_id.value,
                ModelCallTraceRow.id == expected.id.value,
            )
            .with_for_update()
        )
        if row is None or _model_call_from_row(row) != expected:
            raise InvalidDomainValueError("stale model call trace state")
        reconstructed = replace(
            completed,
            status=ModelCallStatus.STARTED,
            completed_at=None,
            response_hash=None,
            metering=None,
            failure_code=None,
        )
        if reconstructed != expected:
            raise InvalidDomainValueError("completed model call immutable metadata changed")
        metering = cast(ModelMetering, completed.metering)
        usage = metering.token_usage
        cost = metering.cost
        row.status = completed.status.value
        row.completed_at = completed.completed_at
        row.response_hash = completed.response_hash.value if completed.response_hash else None
        row.failure_code = completed.failure_code
        row.input_tokens = usage.input_tokens if usage else None
        row.output_tokens = usage.output_tokens if usage else None
        row.cached_input_tokens = usage.cached_input_tokens if usage else None
        row.reasoning_tokens = usage.reasoning_tokens if usage else None
        row.total_tokens = usage.total_tokens if usage else None
        row.cost_nanounits = cost.amount_nanounits if cost else None
        row.currency = cost.currency if cost else None
        row.cost_source = cost.source.value if cost else None
        row.rate_card_version = cost.rate_card_version.value if cost else None
        row.metering_unavailable_reason = (
            metering.unavailable_reason.value if metering.unavailable_reason else None
        )
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()


def _incident_from_row(row: IncidentRow) -> Incident:
    return Incident(
        id=IncidentId(row.id),
        tenant_id=TenantId(row.tenant_id),
        severity=IncidentSeverity(row.severity),
        opened_at=row.opened_at,
        updated_at=row.updated_at,
        state=IncidentState(row.state),
        version=AggregateVersion(row.version),
        closed_at=row.closed_at,
        cancelled_at=row.cancelled_at,
        cancellation_requested_at=row.cancellation_requested_at,
    )


class IncidentRepository:
    """Store Incident aggregates and lifecycle records in one caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, incident: Incident) -> None:
        """Stage a newly opened Incident."""
        self._session.add(
            IncidentRow(
                id=incident.id.value,
                tenant_id=incident.tenant_id.value,
                severity=incident.severity.value,
                state=incident.state.value,
                version=incident.version.value,
                opened_at=incident.opened_at,
                updated_at=incident.updated_at,
                closed_at=incident.closed_at,
                cancelled_at=incident.cancelled_at,
                cancellation_requested_at=incident.cancellation_requested_at,
            )
        )
        await self._session.flush()

    async def get(self, incident_id: IncidentId) -> Incident | None:
        """Load and validate one aggregate."""
        row = await self._session.get(IncidentRow, incident_id.value)
        return None if row is None else _incident_from_row(row)

    async def get_for_tenant(self, incident_id: IncidentId, tenant_id: TenantId) -> Incident | None:
        """Load one aggregate only when it belongs to the authenticated tenant."""
        row = await self._session.scalar(
            select(IncidentRow).where(
                IncidentRow.id == incident_id.value,
                IncidentRow.tenant_id == tenant_id.value,
            )
        )
        return None if row is None else _incident_from_row(row)

    async def apply(self, change: IncidentChange) -> None:
        """Atomically stage an optimistic aggregate update and its immutable records."""
        if change.transitions:
            prior_version = change.transitions[0].prior_version
        elif change.cancellation_request is not None:
            prior_version = change.cancellation_request.prior_version
        else:
            raise InvalidDomainValueError("Incident change contains no auditable record")

        incident = change.incident
        result = cast(
            CursorResult[Any],
            await self._session.execute(
                update(IncidentRow)
                .where(
                    IncidentRow.id == incident.id.value,
                    IncidentRow.tenant_id == incident.tenant_id.value,
                    IncidentRow.version == prior_version.value,
                )
                .values(
                    severity=incident.severity.value,
                    state=incident.state.value,
                    version=incident.version.value,
                    updated_at=incident.updated_at,
                    closed_at=incident.closed_at,
                    cancelled_at=incident.cancelled_at,
                    cancellation_requested_at=incident.cancellation_requested_at,
                )
            ),
        )
        if result.rowcount != 1:
            raise OptimisticVersionError(
                f"Incident {incident.id.value} no longer has version {prior_version.value}"
            )

        for transition in change.transitions:
            metadata = transition.metadata
            self._session.add(
                IncidentTransitionRow(
                    incident_id=transition.incident_id.value,
                    prior_state=transition.prior_state.value,
                    new_state=transition.new_state.value,
                    prior_version=transition.prior_version.value,
                    new_version=transition.new_version.value,
                    actor_id=metadata.actor_id.value,
                    reason=metadata.reason.value,
                    correlation_id=metadata.correlation_id.value,
                    causation_id=metadata.causation_id.value,
                    occurred_at=metadata.occurred_at,
                )
            )
        request = change.cancellation_request
        if request is not None:
            metadata = request.metadata
            self._session.add(
                IncidentCancellationRequestRow(
                    incident_id=request.incident_id.value,
                    state_when_requested=request.state_when_requested.value,
                    prior_version=request.prior_version.value,
                    new_version=request.new_version.value,
                    disposition=request.disposition.value,
                    actor_id=metadata.actor_id.value,
                    reason=metadata.reason.value,
                    correlation_id=metadata.correlation_id.value,
                    causation_id=metadata.causation_id.value,
                    occurred_at=metadata.occurred_at,
                )
            )
        await self._session.flush()


def _memory_projection_row(projection: IncidentMemoryProjection) -> IncidentMemoryProjectionRow:
    return IncidentMemoryProjectionRow(
        id=projection.id.value,
        tenant_id=projection.tenant_id.value,
        source_incident_id=projection.source_incident_id.value,
        source_incident_version=projection.source_incident_version.value,
        source_incident_state=projection.source_incident_state.value,
        service=projection.service,
        root_cause_summary=projection.root_cause_summary,
        outcome=projection.outcome.value,
        outcome_summary=projection.outcome_summary,
        source_evidence_ids=[value.value for value in projection.source_evidence_ids],
        diagnosis_report_fingerprint=projection.diagnosis_report_fingerprint.value,
        evidence_gate_decision_fingerprint=projection.evidence_gate_decision_fingerprint.value,
        confirmation_source=projection.confirmation_source.value,
        confirmation_reference=projection.confirmation_reference.value,
        recovery_action_reference=(
            projection.recovery_action_reference.value
            if projection.recovery_action_reference is not None
            else None
        ),
        closed_at=projection.closed_at,
        projected_at=projection.projected_at,
        content_fingerprint=projection.content_fingerprint.value,
        trust=projection.trust.value,
        schema_version=projection.schema_version,
    )


def _memory_projection_from_row(row: IncidentMemoryProjectionRow) -> IncidentMemoryProjection:
    return IncidentMemoryProjection(
        id=IncidentMemoryId(row.id),
        tenant_id=TenantId(row.tenant_id),
        source_incident_id=IncidentId(row.source_incident_id),
        source_incident_version=AggregateVersion(row.source_incident_version),
        source_incident_state=IncidentState(row.source_incident_state),
        service=row.service,
        root_cause_summary=row.root_cause_summary,
        outcome=IncidentMemoryOutcome(row.outcome),
        outcome_summary=row.outcome_summary,
        source_evidence_ids=tuple(EvidenceId(value) for value in row.source_evidence_ids),
        diagnosis_report_fingerprint=Sha256Digest(row.diagnosis_report_fingerprint),
        evidence_gate_decision_fingerprint=Sha256Digest(row.evidence_gate_decision_fingerprint),
        confirmation_source=IncidentMemoryConfirmationSource(row.confirmation_source),
        confirmation_reference=OpaqueIdentifier(row.confirmation_reference),
        recovery_action_reference=(
            OpaqueIdentifier(row.recovery_action_reference)
            if row.recovery_action_reference is not None
            else None
        ),
        closed_at=row.closed_at,
        projected_at=row.projected_at,
        content_fingerprint=Sha256Digest(row.content_fingerprint),
        trust=TrustClassification(row.trust),
        schema_version=row.schema_version,
    )


def _memory_embedding_from_row(
    row: IncidentMemoryEmbeddingRow,
    projection: IncidentMemoryProjection,
) -> IncidentMemoryEmbedding:
    return IncidentMemoryEmbedding(
        id=OpaqueIdentifier(row.id),
        tenant_id=projection.tenant_id,
        memory_id=projection.id,
        incident_id=projection.source_incident_id,
        source_content_fingerprint=Sha256Digest(row.source_content_hash),
        provider=row.provider,
        model=row.model,
        model_version=row.model_version,
        content_schema_version=row.content_schema_version,
        normalization_version=row.normalization_version,
        vector=tuple(float(value) for value in row.embedding),
        created_at=row.created_at,
        reindex_required=row.reindex_required,
    )


class IncidentMemoryRepository:
    """Atomically admit confirmed projections and versioned vector derivatives."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def store(
        self,
        projection: IncidentMemoryProjection,
        embedding: IncidentMemoryEmbedding,
    ) -> IncidentMemoryEmbedding:
        if (
            embedding.tenant_id != projection.tenant_id
            or embedding.memory_id != projection.id
            or embedding.incident_id != projection.source_incident_id
            or embedding.source_content_fingerprint != projection.content_fingerprint
            or embedding.content_schema_version != projection.schema_version
            or embedding.reindex_required
        ):
            raise InvalidDomainValueError("embedding does not match its active memory projection")

        incident = await self._session.scalar(
            select(IncidentRow)
            .where(
                IncidentRow.id == projection.source_incident_id.value,
                IncidentRow.tenant_id == projection.tenant_id.value,
            )
            .with_for_update()
        )
        if (
            incident is None
            or incident.state != IncidentState.CLOSED.value
            or incident.version != projection.source_incident_version.value
            or incident.closed_at != projection.closed_at
        ):
            raise InvalidDomainValueError("memory projection does not match a closed Incident")

        projection_row = await self._session.scalar(
            select(IncidentMemoryProjectionRow).where(
                IncidentMemoryProjectionRow.source_incident_id
                == projection.source_incident_id.value
            )
        )
        if projection_row is None:
            projection_row = _memory_projection_row(projection)
            self._session.add(projection_row)
            await self._session.flush()
        elif _memory_projection_from_row(projection_row) != projection:
            raise InvalidDomainValueError("Incident already has a different memory projection")

        exact = await self._session.scalar(
            select(IncidentMemoryEmbeddingRow).where(
                IncidentMemoryEmbeddingRow.incident_id == embedding.incident_id.value,
                IncidentMemoryEmbeddingRow.provider == embedding.provider,
                IncidentMemoryEmbeddingRow.model == embedding.model,
                IncidentMemoryEmbeddingRow.model_version == embedding.model_version,
                IncidentMemoryEmbeddingRow.content_schema_version
                == embedding.content_schema_version,
                IncidentMemoryEmbeddingRow.normalization_version == embedding.normalization_version,
            )
        )
        if exact is not None:
            stored = _memory_embedding_from_row(exact, projection)
            if (
                stored.source_content_fingerprint != embedding.source_content_fingerprint
                or stored.dimensions != embedding.dimensions
                or any(
                    not isclose(left, right, rel_tol=1e-6, abs_tol=1e-7)
                    for left, right in zip(stored.vector, embedding.vector, strict=True)
                )
            ):
                raise InvalidDomainValueError("embedding version identity is already bound")
            return stored

        await self._session.execute(
            update(IncidentMemoryEmbeddingRow)
            .where(
                IncidentMemoryEmbeddingRow.incident_id == embedding.incident_id.value,
                IncidentMemoryEmbeddingRow.reindex_required.is_(False),
            )
            .values(reindex_required=True)
        )
        row = IncidentMemoryEmbeddingRow(
            id=embedding.id.value,
            incident_id=embedding.incident_id.value,
            source_content_hash=embedding.source_content_fingerprint.value,
            provider=embedding.provider,
            model=embedding.model,
            model_version=embedding.model_version,
            dimensions=embedding.dimensions,
            content_schema_version=embedding.content_schema_version,
            normalization_version=embedding.normalization_version,
            embedding=list(embedding.vector),
            reindex_required=False,
            created_at=embedding.created_at,
        )
        self._session.add(row)
        await self._session.flush()
        return _memory_embedding_from_row(row, projection)

    async def search(
        self, query: IncidentMemorySearchQuery
    ) -> tuple[SimilarIncidentReference, ...]:
        """Return fresh compatible vectors only within the current Incident's tenant."""
        current = await self._session.scalar(
            select(IncidentRow.id).where(
                IncidentRow.id == query.current_incident_id.value,
                IncidentRow.tenant_id == query.tenant_id.value,
            )
        )
        if current is None:
            raise AuthorizationError("current Incident is not available in the requested tenant")

        distance = IncidentMemoryEmbeddingRow.embedding.cosine_distance(list(query.vector))
        rows = (
            await self._session.execute(
                select(IncidentMemoryProjectionRow, distance.label("distance"))
                .join(
                    IncidentMemoryEmbeddingRow,
                    IncidentMemoryEmbeddingRow.incident_id
                    == IncidentMemoryProjectionRow.source_incident_id,
                )
                .where(
                    IncidentMemoryProjectionRow.tenant_id == query.tenant_id.value,
                    IncidentMemoryProjectionRow.source_incident_id
                    != query.current_incident_id.value,
                    IncidentMemoryProjectionRow.closed_at >= query.freshness_cutoff,
                    IncidentMemoryProjectionRow.closed_at <= query.requested_at,
                    IncidentMemoryProjectionRow.projected_at <= query.requested_at,
                    IncidentMemoryEmbeddingRow.reindex_required.is_(False),
                    IncidentMemoryEmbeddingRow.provider == query.provider,
                    IncidentMemoryEmbeddingRow.model == query.model,
                    IncidentMemoryEmbeddingRow.model_version == query.model_version,
                    IncidentMemoryEmbeddingRow.content_schema_version
                    == query.content_schema_version,
                    IncidentMemoryEmbeddingRow.normalization_version == query.normalization_version,
                    IncidentMemoryEmbeddingRow.dimensions == query.dimensions,
                    distance >= 0.0,
                    distance <= 1.0,
                )
                .order_by(
                    distance.asc(),
                    IncidentMemoryProjectionRow.closed_at.desc(),
                    IncidentMemoryProjectionRow.source_incident_id.asc(),
                )
                .limit(query.max_results)
            )
        ).all()
        results: list[SimilarIncidentReference] = []
        for raw_row, raw_distance in rows:
            row = cast(IncidentMemoryProjectionRow, raw_row)
            row_distance = cast(float, raw_distance)
            results.append(
                SimilarIncidentReference(
                    incident_id=IncidentId(row.source_incident_id),
                    service=row.service,
                    root_cause_summary=row.root_cause_summary,
                    outcome=row.outcome,
                    outcome_summary=row.outcome_summary,
                    closed_at=row.closed_at,
                    similarity=1.0 - row_distance,
                )
            )
        return tuple(results)


def _alert_row(alert: Alert, group_id: AlertGroupId) -> AlertRow:
    return AlertRow(
        id=alert.id.value,
        group_id=group_id.value,
        fingerprint=alert.fingerprint().value,
        tenant_id=alert.tenant_id.value,
        environment=alert.environment,
        service=alert.service,
        rule=alert.rule,
        severity=alert.severity.value,
        observed_at=alert.observed_at,
        received_at=alert.received_at,
        dimensions=[{"name": item.name, "value": item.value} for item in alert.dimensions],
    )


def _group_row(group: AlertGroup) -> AlertGroupRow:
    return AlertGroupRow(
        id=group.id.value,
        fingerprint=group.fingerprint.value,
        fingerprint_schema_version=group.fingerprint.schema_version,
        tenant_id=group.tenant_id.value,
        environment=group.environment,
        service=group.service,
        rule=group.rule,
        severity=group.severity.value,
        first_observed_at=group.first_observed_at,
        last_observed_at=group.last_observed_at,
        first_received_at=group.first_received_at,
        last_received_at=group.last_received_at,
        occurrence_count=group.occurrence_count,
        version=group.version.value,
    )


class AlertRepository:
    """PostgreSQL-serialized Alert ingestion preserving deterministic grouping."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        window: timedelta,
        group_id_factory: Callable[[], AlertGroupId],
    ) -> None:
        if window <= timedelta(0):
            raise InvalidDomainValueError("deduplication window must be positive")
        self._session = session
        self._window = window
        self._group_id_factory = group_id_factory

    async def ingest(self, alert: Alert) -> AlertTriageDecision:
        """Serialize one fingerprint, then open, merge, or replay its group."""
        fingerprint = alert.fingerprint()
        lock_key = int.from_bytes(bytes.fromhex(fingerprint.value[:16]), signed=True)
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
        )

        existing_alert = await self._session.get(AlertRow, alert.id.value)
        if existing_alert is not None:
            group = await self._load_group(existing_alert.group_id)
            return AlertTriageDecision(AlertTriageAction.DUPLICATE, group, fingerprint)

        rows = (
            await self._session.scalars(
                select(AlertGroupRow)
                .where(AlertGroupRow.fingerprint == fingerprint.value)
                .with_for_update()
            )
        ).all()
        groups = [await self._hydrate_group(row) for row in rows]
        existing = select_alert_group(groups, alert, self._window)
        if existing is None:
            group = AlertGroup.open(self._group_id_factory(), alert)
            self._session.add(_group_row(group))
            action = AlertTriageAction.OPEN_GROUP
        else:
            group, action = existing.merge(alert, expected_version=existing.version)
            result = cast(
                CursorResult[Any],
                await self._session.execute(
                    update(AlertGroupRow)
                    .where(
                        AlertGroupRow.id == existing.id.value,
                        AlertGroupRow.version == existing.version.value,
                    )
                    .values(
                        severity=group.severity.value,
                        first_observed_at=group.first_observed_at,
                        last_observed_at=group.last_observed_at,
                        first_received_at=group.first_received_at,
                        last_received_at=group.last_received_at,
                        occurrence_count=group.occurrence_count,
                        version=group.version.value,
                    )
                ),
            )
            if result.rowcount != 1:
                raise OptimisticVersionError("Alert group changed during serialized ingestion")
        self._session.add(_alert_row(alert, group.id))
        await self._session.flush()
        return AlertTriageDecision(action, group, fingerprint)

    async def _load_group(self, group_id: str) -> AlertGroup:
        row = await self._session.get(AlertGroupRow, group_id)
        if row is None:
            raise InvalidDomainValueError("Alert references a missing group")
        return await self._hydrate_group(row)

    async def _hydrate_group(self, row: AlertGroupRow) -> AlertGroup:
        alert_ids = tuple(
            AlertId(value)
            for value in (
                await self._session.scalars(
                    select(AlertRow.id).where(AlertRow.group_id == row.id).order_by(AlertRow.id)
                )
            ).all()
        )
        return AlertGroup(
            id=AlertGroupId(row.id),
            fingerprint=AlertFingerprint(row.fingerprint, row.fingerprint_schema_version),
            tenant_id=TenantId(row.tenant_id),
            environment=row.environment,
            service=row.service,
            rule=row.rule,
            severity=IncidentSeverity(row.severity),
            first_observed_at=row.first_observed_at,
            last_observed_at=row.last_observed_at,
            first_received_at=row.first_received_at,
            last_received_at=row.last_received_at,
            alert_ids=alert_ids,
            occurrence_count=row.occurrence_count,
            version=AggregateVersion(row.version),
        )

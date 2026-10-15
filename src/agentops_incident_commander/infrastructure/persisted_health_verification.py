"""Persist live health signals, re-resolve them, and record one deterministic decision."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentops_incident_commander.application import (
    NOOP_CONTROL_PLANE_OBSERVER,
    ControlPlaneComponent,
    ControlPlaneObservation,
    ControlPlaneObserver,
    ControlPlaneOperation,
    ControlPlaneOutcome,
    evaluate_evidence_bound_health_verification,
    safely_record,
    utc_observation_time,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    ArtifactAlreadyExistsError,
    ArtifactStorage,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    HealthVerificationDecision,
    HealthVerificationOutcome,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    as_utc,
    require_authenticated,
)

from .health_verification import (
    CollectedHealthVerification,
    HealthVerificationCollectionRequest,
    LiveHealthVerificationCollector,
)
from .persistence import EvidenceRepository, HealthVerificationRepository

HEALTH_VERIFICATION_DECISION_AUDIT_SCHEMA_VERSION = "health_verification/v1"


class PostgresPersistedHealthVerifier:
    """Run the read-only collector and durably record its evidence-bound decision."""

    def __init__(
        self,
        collector: LiveHealthVerificationCollector,
        artifact_storage: ArtifactStorage,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        request_factory: Callable[[ActionExecution], HealthVerificationCollectionRequest],
        decision_id_factory: Callable[[ActionExecution], OpaqueIdentifier],
        audit_event_id_factory: Callable[[], AuditEventId],
        clock: Callable[[], datetime],
        observer: ControlPlaneObserver = NOOP_CONTROL_PLANE_OBSERVER,
    ) -> None:
        self._collector = collector
        self._artifact_storage = artifact_storage
        self._session_factory = session_factory
        self._request_factory = request_factory
        self._decision_id_factory = decision_id_factory
        self._audit_event_id_factory = audit_event_id_factory
        self._clock = clock
        self._observer = observer

    async def verify(
        self,
        execution: ActionExecution,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> HealthVerificationDecision:
        if not isinstance(execution, ActionExecution):
            raise InvalidDomainValueError("persisted health verification inputs are invalid")
        if execution.status is not ActionExecutionStatus.SUCCEEDED:
            raise InvalidDomainValueError("persisted health verification inputs are invalid")
        if not isinstance(correlation_id, CorrelationId):
            raise InvalidDomainValueError("persisted health verification inputs are invalid")
        started_ns = time.monotonic_ns()
        self._observe(
            execution,
            ControlPlaneOutcome.STARTED,
            correlation_id=correlation_id,
            started_ns=started_ns,
            route="COLLECT_AND_DECIDE",
            result_code="STARTED",
        )
        try:
            decision, replayed = await self._verify(
                execution,
                principal=principal,
                correlation_id=correlation_id,
            )
        except asyncio.CancelledError:
            self._observe(
                execution,
                ControlPlaneOutcome.CANCELLED,
                correlation_id=correlation_id,
                started_ns=started_ns,
                route="SAFE_BOUNDARY",
                result_code="CANCELLED",
            )
            raise
        except TimeoutError:
            self._observe(
                execution,
                ControlPlaneOutcome.TIMED_OUT,
                correlation_id=correlation_id,
                started_ns=started_ns,
                route="FAIL_CLOSED",
                result_code="COLLECTION_TIMEOUT",
            )
            raise
        except Exception:
            self._observe(
                execution,
                ControlPlaneOutcome.FAILED,
                correlation_id=correlation_id,
                started_ns=started_ns,
                route="FAIL_CLOSED",
                result_code="VERIFICATION_FAILED",
            )
            raise
        self._observe(
            execution,
            (
                ControlPlaneOutcome.REPLAYED
                if replayed
                else (
                    ControlPlaneOutcome.PASSED
                    if decision.outcome is HealthVerificationOutcome.PASS
                    else ControlPlaneOutcome.FAILED
                )
            ),
            correlation_id=correlation_id,
            started_ns=started_ns,
            route=decision.outcome.value,
            result_code=(
                f"REPLAY_{decision.outcome.value}"
                if replayed
                else f"DECISION_{decision.outcome.value}"
            ),
            subject_version=decision.schema_version,
        )
        return decision

    async def _verify(
        self,
        execution: ActionExecution,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> tuple[HealthVerificationDecision, bool]:
        actor = require_authenticated(principal)
        if actor.tenant_id != execution.tenant_id:
            raise InvalidDomainValueError("health verifier principal scope is invalid")
        decision_id = self._decision_id_factory(execution)
        if not isinstance(decision_id, OpaqueIdentifier):
            raise InvalidDomainValueError("health verification decision identity is invalid")
        async with self._session_factory() as session:
            existing = await HealthVerificationRepository(session).get(
                decision_id,
                tenant_id=execution.tenant_id,
                incident_id=execution.incident_id,
            )
        if existing is not None:
            decision = existing[1]
            if decision.execution_fingerprint != execution.fingerprint:
                raise InvalidDomainValueError("stored health verification execution differs")
            return decision, True

        request = self._request_factory(execution)
        if not isinstance(request, HealthVerificationCollectionRequest):
            raise InvalidDomainValueError("health verification collection request is invalid")
        criteria = request.criteria
        completed_at = execution.completed_at
        expected_plan_scope = (
            execution.tenant_id,
            execution.incident_id,
            execution.id,
            execution.target.service,
            execution.target.environment,
            execution.target.stable_version,
        )
        actual_plan_scope = (
            criteria.tenant_id,
            criteria.incident_id,
            criteria.action_execution_id,
            criteria.service,
            criteria.environment,
            criteria.expected_stable_version,
        )
        if completed_at is None or actual_plan_scope != expected_plan_scope:
            raise InvalidDomainValueError("health verification plan is not execution-bound")
        if request.window_started_at < completed_at:
            raise InvalidDomainValueError("health verification plan is not execution-bound")

        collected = await self._collector.collect(request)
        if not isinstance(collected, CollectedHealthVerification):
            raise InvalidDomainValueError("health verification collector returned invalid result")
        observation = collected.observation
        expected_ids = {
            observation.error_rate_evidence_id,
            observation.p95_latency_evidence_id,
            observation.health_endpoint_evidence_id,
            observation.deployed_version_evidence_id,
            observation.new_alerts_evidence_id,
        }
        if (
            observation.tenant_id,
            observation.incident_id,
            observation.action_execution_id,
        ) != (execution.tenant_id, execution.incident_id, execution.id):
            raise InvalidDomainValueError("collected health verification scope is invalid")
        if {item.evidence.id for item in collected.evidence} != expected_ids:
            raise InvalidDomainValueError("collected health verification scope is invalid")

        evaluated_at = as_utc(self._clock())
        for item in collected.evidence:
            try:
                self._artifact_storage.store(item.artifact, item.content)
            except ArtifactAlreadyExistsError:
                stored = self._artifact_storage.retrieve(
                    item.artifact.id,
                    incident_id=execution.incident_id,
                    principal=actor,
                    at=evaluated_at,
                )
                if stored.artifact != item.artifact or stored.content != item.content:
                    raise InvalidDomainValueError(
                        "stored health verification Artifact differs"
                    ) from None

        async with self._session_factory.begin() as session:
            evidence_store = EvidenceRepository(session)
            for item in collected.evidence:
                existing_evidence = await evidence_store.get(
                    item.evidence.id,
                    tenant_id=execution.tenant_id,
                    incident_id=execution.incident_id,
                )
                if existing_evidence is None:
                    await evidence_store.add(item.evidence, item.artifact)
                elif existing_evidence != item.evidence:
                    raise InvalidDomainValueError("stored health verification Evidence differs")

        async with self._session_factory.begin() as session:
            repository = HealthVerificationRepository(session)
            result = await evaluate_evidence_bound_health_verification(
                execution,
                criteria,
                observation,
                decision_id=decision_id,
                evaluated_at=evaluated_at,
                principal=actor,
                reader=EvidenceRepository(session),
                artifact_storage=self._artifact_storage,
            )
            if result.decision is None:
                raise InvalidDomainValueError(
                    "health verification Evidence did not resolve completely"
                )
            decision = result.decision
            audit_id = self._audit_event_id_factory()
            if not isinstance(audit_id, AuditEventId):
                raise InvalidDomainValueError("health verification audit identity is invalid")
            audit = AuditEvent(
                audit_id,
                decision.tenant_id,
                "health.verification_decided",
                1,
                HEALTH_VERIFICATION_DECISION_AUDIT_SCHEMA_VERSION,
                actor.actor_id,
                correlation_id,
                CausationId(execution.id.value),
                AuditTarget("health.verification", decision.id),
                decision.evaluated_at,
                decision.input_fingerprint,
                decision.fingerprint,
            )
            _, stored_decision = await repository.record(
                execution,
                criteria,
                observation,
                decision,
                audit,
            )
        if stored_decision != decision:  # pragma: no cover - repository contract defense
            raise InvalidDomainValueError("stored health verification decision differs")
        return stored_decision, False

    def _observe(
        self,
        execution: ActionExecution,
        outcome: ControlPlaneOutcome,
        *,
        correlation_id: CorrelationId,
        started_ns: int,
        route: str,
        result_code: str,
        subject_version: str = "1.0.0",
    ) -> None:
        safely_record(
            self._observer,
            ControlPlaneObservation(
                component=ControlPlaneComponent.VERIFICATION,
                operation=ControlPlaneOperation.HEALTH_VERIFY,
                outcome=outcome,
                occurred_at=utc_observation_time(),
                tenant_id=execution.tenant_id,
                incident_id=execution.incident_id,
                correlation_id=correlation_id,
                causation_id=CausationId(execution.id.value),
                operation_id=execution.id,
                duration_ms=(
                    None
                    if outcome is ControlPlaneOutcome.STARTED
                    else max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
                ),
                route=route,
                result_code=result_code,
                subject_name="health_verification",
                subject_version=subject_version,
            ),
        )

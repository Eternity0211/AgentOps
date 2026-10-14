"""Focused defensive-path tests for persistence repositories."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.application import (
    evidence_gate_claim_snapshot,
    model_call_trace_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Alert,
    AlertDimension,
    AlertGroupId,
    AlertId,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    EvidenceGateOutcome,
    EvidenceId,
    IncidentId,
    IncidentSeverity,
    InvalidDomainValueError,
    JobId,
    ModelCallId,
    OpaqueIdentifier,
    OptimisticVersionError,
    OutboxEventId,
    Sha256Digest,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.persistence import (
    AlertGroupRow,
    AlertRepository,
    AuditRepository,
    DiagnosisReportRepository,
    DiagnosisReportRow,
    EvidenceGateDecisionRow,
    JobRepository,
    JobRow,
    ModelCallTraceRepository,
    ModelCallTraceRow,
    OutboxEventRow,
    OutboxRepository,
    repositories,
)
from agentops_incident_commander.workflows import (
    CounterEvidenceTreatment,
    DiagnosisDisposition,
    DiagnosisReport,
    DiagnosisReportRecord,
    RootCauseCandidate,
    diagnosis_report_fingerprint,
)

NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)


def diagnosis_report(*, candidates: bool = True) -> DiagnosisReport:
    return DiagnosisReport(
        schema_version="1.0.0",
        incident_id="incident-diagnosis",
        disposition=(
            DiagnosisDisposition.CANDIDATES
            if candidates
            else DiagnosisDisposition.NEEDS_MORE_EVIDENCE
        ),
        candidates=(
            (
                RootCauseCandidate(
                    candidate_id="candidate-diagnosis",
                    rank=1,
                    statement="Connection pool exhaustion.",
                    supporting_evidence_ids=("evidence-diagnosis",),
                    counter_evidence_ids=(),
                    counter_evidence_treatment=CounterEvidenceTreatment.NOT_APPLICABLE,
                    missing_evidence=(),
                    uncertainty="The window is bounded.",
                    confidence_basis_points=8000,
                ),
            )
            if candidates
            else ()
        ),
        missing_evidence=(),
        explanation="A bounded result.",
    )


def diagnosis_record(*, candidates: bool = True) -> DiagnosisReportRecord:
    report = diagnosis_report(candidates=candidates)
    return DiagnosisReportRecord(
        tenant_id=TenantId("tenant-diagnosis"),
        workflow_run_id=WorkflowRunId("run-diagnosis"),
        model_call_id=ModelCallId("call-diagnosis"),
        report=report,
        report_fingerprint=diagnosis_report_fingerprint(report),
        produced_at=NOW + timedelta(minutes=2),
    )


def diagnosis_trace_row(
    record: DiagnosisReportRecord, *, node: str = "diagnosis.hypothesis"
) -> ModelCallTraceRow:
    return ModelCallTraceRow(
        id=record.model_call_id.value,
        tenant_id=record.tenant_id.value,
        incident_id=record.incident_id.value,
        workflow_run_id=record.workflow_run_id.value,
        node=node,
        attempt=1,
        prompt_id="diagnosis",
        prompt_version="1.0.0",
        prompt_fingerprint="a" * 64,
        provider="mock",
        model="model-v1",
        temperature_basis_points=0,
        top_p_basis_points=10_000,
        max_output_tokens=1024,
        seed=7,
        input_schema_version="1.0.0",
        output_schema_version="1.0.0",
        request_hash="b" * 64,
        response_hash=record.report_fingerprint.value,
        correlation_id="correlation-diagnosis",
        causation_id="cause-diagnosis",
        status="SUCCEEDED",
        started_at=NOW + timedelta(minutes=1),
        completed_at=record.produced_at,
        input_tokens=None,
        output_tokens=None,
        cached_input_tokens=None,
        reasoning_tokens=None,
        total_tokens=None,
        cost_nanounits=None,
        currency=None,
        cost_source=None,
        rate_card_version=None,
        metering_unavailable_reason="PROVIDER_DID_NOT_RETURN",
        failure_code=None,
        schema_version="1.0.0",
    )


def diagnosis_row(
    record: DiagnosisReportRecord, *, workflow_run_id: str | None = None
) -> DiagnosisReportRow:
    return DiagnosisReportRow(
        tenant_id=record.tenant_id.value,
        incident_id=record.incident_id.value,
        workflow_run_id=workflow_run_id or record.workflow_run_id.value,
        model_call_id=record.model_call_id.value,
        disposition=record.report.disposition.value,
        report=record.report.model_dump(mode="json"),
        report_fingerprint=record.report_fingerprint.value,
        produced_at=record.produced_at,
        schema_version=record.report.schema_version,
    )


def diagnosis_audit(record: DiagnosisReportRecord) -> AuditEvent:
    trace = repositories._model_call_from_row(diagnosis_trace_row(record))
    return AuditEvent(
        id=AuditEventId("audit-diagnosis"),
        tenant_id=record.tenant_id,
        type="diagnosis.report_recorded",
        event_version=1,
        payload_schema_version="diagnosis_report/v1",
        actor_id=ActorId("diagnosis-worker"),
        correlation_id=trace.correlation_id,
        causation_id=trace.causation_id,
        target=AuditTarget("diagnosis.report", OpaqueIdentifier(record.report_fingerprint.value)),
        occurred_at=record.produced_at,
        request_hash=model_call_trace_fingerprint(trace),
        result_hash=record.report_fingerprint,
    )


def gate_row(record: DiagnosisReportRecord) -> EvidenceGateDecisionRow:
    claim = record.report.evidence_gate_claim("candidate-diagnosis")
    snapshot: dict[str, object] = {"claim": evidence_gate_claim_snapshot(claim)}
    fingerprint = hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return EvidenceGateDecisionRow(
        tenant_id=record.tenant_id.value,
        incident_id=record.incident_id.value,
        candidate_id=claim.candidate_id,
        outcome=EvidenceGateOutcome.PASS.value,
        reasons=[],
        evaluated_evidence_ids=[EvidenceId("evidence-diagnosis").value],
        rules_version="1.1.0",
        input_fingerprint=fingerprint,
        input_snapshot=snapshot,
        evaluated_at=record.produced_at,
        model_confidence_basis_points=8000,
        schema_version="1.0.0",
    )


@pytest.mark.anyio
async def test_health_verification_read_rejects_multiple_results_for_one_execution() -> None:
    session = SimpleNamespace()
    session.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: [object(), object()]))
    repository = repositories.HealthVerificationRepository(cast(AsyncSession, session))
    with pytest.raises(InvalidDomainValueError, match="multiple health verification"):
        await repository.for_execution(
            OpaqueIdentifier("execution-duplicate"),
            tenant_id=TenantId("tenant-1"),
            incident_id=IncidentId("incident-1"),
        )


def alert() -> Alert:
    return Alert(
        id=AlertId("alert-2"),
        tenant_id=TenantId("tenant-1"),
        environment="production",
        service="order-service",
        rule="errors",
        severity=IncidentSeverity.SEV1,
        observed_at=NOW,
        received_at=NOW,
        dimensions=(AlertDimension("region", "east"),),
    )


def existing_row(item: Alert) -> AlertGroupRow:
    return AlertGroupRow(
        id="group-1",
        fingerprint=item.fingerprint().value,
        fingerprint_schema_version=item.fingerprint().schema_version,
        tenant_id=item.tenant_id.value,
        environment=item.environment,
        service=item.service,
        rule=item.rule,
        severity=IncidentSeverity.SEV3.value,
        first_observed_at=NOW,
        last_observed_at=NOW,
        first_received_at=NOW,
        last_received_at=NOW,
        occurrence_count=1,
        version=1,
    )


@pytest.mark.anyio
async def test_alert_repository_rejects_impossible_optimistic_update_loss() -> None:
    """The row-count guard still fails closed if locking guarantees are violated."""
    item = alert()
    session = AsyncMock()
    session.get.return_value = None
    session.scalars.side_effect = [
        SimpleNamespace(all=lambda: [existing_row(item)]),
        SimpleNamespace(all=lambda: ["alert-1"]),
    ]
    session.execute.side_effect = [SimpleNamespace(), SimpleNamespace(rowcount=0)]
    repository = AlertRepository(
        session,
        window=timedelta(minutes=5),
        group_id_factory=lambda: AlertGroupId("unused"),
    )

    with pytest.raises(OptimisticVersionError, match="changed during"):
        await repository.ingest(item)


@pytest.mark.anyio
async def test_alert_repository_rejects_dangling_alert_group_reference() -> None:
    """A corrupt foreign-key reference cannot become a partial domain aggregate."""
    session = AsyncMock()
    session.get.return_value = None
    repository = AlertRepository(
        session,
        window=timedelta(minutes=5),
        group_id_factory=lambda: AlertGroupId("unused"),
    )

    with pytest.raises(InvalidDomainValueError, match="missing group"):
        await repository._load_group("missing")


def test_aggregate_version_type_remains_explicit_in_repository_test_fixture() -> None:
    """Keep the repository fixture's expected version contract visible."""
    assert AggregateVersion(1).next() == AggregateVersion(2)


def test_outbox_hydration_rejects_payload_hash_drift() -> None:
    """A stored payload cannot be dispatched when its integrity digest no longer matches."""
    row = OutboxEventRow(payload={"value": 1}, payload_hash="0" * 64)

    with pytest.raises(InvalidDomainValueError, match="hash does not match"):
        repositories._outbox_event_from_row(row)


@pytest.mark.anyio
@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
async def test_outbox_claim_rejects_nonpositive_lease(duration: timedelta) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="duration must be positive"):
        await repository.claim(
            OpaqueIdentifier("worker-1"), now=NOW, lease_duration=duration, limit=1
        )


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
async def test_outbox_claim_rejects_invalid_batch_limit(limit: object) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="between 1 and 100"):
        await repository.claim(
            OpaqueIdentifier("worker-1"),
            now=NOW,
            lease_duration=timedelta(seconds=1),
            limit=limit,  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_outbox_failure_rejects_retry_before_failure() -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        await repository.mark_failed(
            OutboxEventId("outbox-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW - timedelta(seconds=1),
            error="failure",
        )


@pytest.mark.anyio
@pytest.mark.parametrize("error", ["", "x" * 513, "line\nbreak"])
async def test_outbox_failure_rejects_unsafe_error_text(error: str) -> None:
    repository = OutboxRepository(AsyncMock())

    with pytest.raises(InvalidDomainValueError, match="bounded printable"):
        await repository.mark_failed(
            OutboxEventId("outbox-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW,
            error=error,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1)])
async def test_job_claim_rejects_nonpositive_lease(duration: timedelta) -> None:
    with pytest.raises(InvalidDomainValueError, match="duration must be positive"):
        await JobRepository(AsyncMock()).claim(
            OpaqueIdentifier("worker-1"), now=NOW, lease_duration=duration, limit=1
        )


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
async def test_job_claim_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(InvalidDomainValueError, match="between 1 and 100"):
        await JobRepository(AsyncMock()).claim(
            OpaqueIdentifier("worker-1"),
            now=NOW,
            lease_duration=timedelta(seconds=1),
            limit=limit,  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_job_heartbeat_rejects_nonpositive_duration() -> None:
    with pytest.raises(InvalidDomainValueError, match="duration must be positive"):
        await JobRepository(AsyncMock()).heartbeat(
            JobId("job-1"),
            OpaqueIdentifier("worker-1"),
            now=NOW,
            lease_duration=timedelta(0),
        )


@pytest.mark.anyio
async def test_job_heartbeat_rejects_time_regression() -> None:
    session = AsyncMock()
    session.scalar.return_value = JobRow(
        id="job-1",
        status="LEASED",
        lease_owner="worker-1",
        heartbeat_at=NOW,
        lease_expires_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(InvalidDomainValueError, match="cannot move backward"):
        await JobRepository(session).heartbeat(
            JobId("job-1"),
            OpaqueIdentifier("worker-1"),
            now=NOW - timedelta(seconds=1),
            lease_duration=timedelta(minutes=1),
        )


@pytest.mark.anyio
async def test_job_failure_rejects_retry_before_failure() -> None:
    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        await JobRepository(AsyncMock()).fail(
            JobId("job-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW - timedelta(seconds=1),
            error="failure",
        )


@pytest.mark.anyio
@pytest.mark.parametrize("error", ["", "x" * 513, "line\nbreak"])
async def test_job_failure_rejects_unsafe_error_text(error: str) -> None:
    with pytest.raises(InvalidDomainValueError, match="bounded printable"):
        await JobRepository(AsyncMock()).fail(
            JobId("job-1"),
            OpaqueIdentifier("worker-1"),
            failed_at=NOW,
            retry_at=NOW,
            error=error,
        )


def test_diagnosis_report_hydration_rejects_malformed_document() -> None:
    record = diagnosis_record()
    row = diagnosis_row(record)
    row.report = {"schema_version": "1.0.0"}
    with pytest.raises(InvalidDomainValueError, match="strict validation"):
        repositories._diagnosis_report_from_row(row)


@pytest.mark.anyio
async def test_platform_observability_repository_reads_are_bounded() -> None:
    session = AsyncMock()
    assert (
        await AuditRepository(session).for_targets(
            tenant_id=TenantId("tenant-1"),
            target_type="model.call",
            target_ids=(),
        )
        == ()
    )
    for target_ids in (
        (OpaqueIdentifier("call-1"), OpaqueIdentifier("call-1")),
        tuple(OpaqueIdentifier(f"call-{index}") for index in range(101)),
    ):
        with pytest.raises(InvalidDomainValueError, match="unique and bounded"):
            await AuditRepository(session).for_targets(
                tenant_id=TenantId("tenant-1"),
                target_type="model.call",
                target_ids=target_ids,
            )
    for limit in (0, 101, True, 1.5):
        with pytest.raises(InvalidDomainValueError, match="between 1 and 100"):
            await ModelCallTraceRepository(session).for_incident(
                tenant_id=TenantId("tenant-1"),
                incident_id=IncidentId("incident-1"),
                limit=limit,  # type: ignore[arg-type]
            )


@pytest.mark.anyio
async def test_diagnosis_repository_rejects_missing_mismatched_trace_and_audit() -> None:
    record = diagnosis_record()
    missing = AsyncMock()
    missing.scalar.return_value = None
    with pytest.raises(InvalidDomainValueError, match="not persisted"):
        await DiagnosisReportRepository(missing)._require_trace_binding(record)

    mismatched = AsyncMock()
    mismatched.scalar.return_value = diagnosis_trace_row(record, node="diagnosis.replan")
    with pytest.raises(InvalidDomainValueError, match="does not match"):
        await DiagnosisReportRepository(mismatched)._require_trace_binding(record)

    invalid_audit = AsyncMock()
    invalid_audit.scalar.return_value = diagnosis_trace_row(record)
    with pytest.raises(InvalidDomainValueError, match="audit event"):
        await DiagnosisReportRepository(invalid_audit).record(
            record,
            replace(diagnosis_audit(record), result_hash=Sha256Digest("f" * 64)),
        )


@pytest.mark.anyio
async def test_diagnosis_repository_rejects_conflicting_replay() -> None:
    record = diagnosis_record()
    session = AsyncMock()
    session.scalar.side_effect = [
        diagnosis_trace_row(record),
        diagnosis_row(record, workflow_run_id="run-other"),
    ]
    with pytest.raises(InvalidDomainValueError, match="conflicts with storage"):
        await DiagnosisReportRepository(session).record(record, diagnosis_audit(record))


@pytest.mark.anyio
async def test_diagnosis_gate_matching_handles_empty_duplicate_and_corrupt_rows() -> None:
    empty = diagnosis_record(candidates=False)
    assert await DiagnosisReportRepository(AsyncMock()).matching_gate_decisions(empty) == ()

    record = diagnosis_record()
    valid = gate_row(record)
    duplicate_session = AsyncMock()
    duplicate_session.scalars.return_value = SimpleNamespace(all=lambda: [valid, valid])
    decisions = await DiagnosisReportRepository(duplicate_session).matching_gate_decisions(record)
    assert len(decisions) == 1
    assert decisions[0].outcome is EvidenceGateOutcome.PASS

    missing_session = AsyncMock()
    missing_session.scalars.return_value = SimpleNamespace(all=lambda: [])
    assert await DiagnosisReportRepository(missing_session).matching_gate_decisions(record) == ()

    bad_hash = gate_row(record)
    bad_hash.input_fingerprint = "f" * 64
    hash_session = AsyncMock()
    hash_session.scalars.return_value = SimpleNamespace(all=lambda: [bad_hash])
    with pytest.raises(InvalidDomainValueError, match="fingerprint disagrees"):
        await DiagnosisReportRepository(hash_session).matching_gate_decisions(record)

    bad_claim = gate_row(record)
    bad_claim.input_snapshot = {
        "claim": {
            **cast(dict[str, object], bad_claim.input_snapshot["claim"]),
            "candidate_id": "candidate-other",
        }
    }
    bad_claim.input_fingerprint = hashlib.sha256(
        json.dumps(bad_claim.input_snapshot, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    claim_session = AsyncMock()
    claim_session.scalars.return_value = SimpleNamespace(all=lambda: [bad_claim])
    with pytest.raises(InvalidDomainValueError, match="latest Diagnosis report"):
        await DiagnosisReportRepository(claim_session).matching_gate_decisions(record)

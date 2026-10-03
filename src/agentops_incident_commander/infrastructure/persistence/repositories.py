"""Async PostgreSQL repositories preserving pure-domain invariants."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Alert,
    AlertFingerprint,
    AlertGroup,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    AlertTriageDecision,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    Incident,
    IncidentChange,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    OptimisticVersionError,
    Sha256Digest,
    StoredAuditEvent,
    TenantId,
    select_alert_group,
)

from .models import (
    AlertGroupRow,
    AlertRow,
    AuditEventRow,
    IncidentCancellationRequestRow,
    IncidentRow,
    IncidentTransitionRow,
)


def _audit_from_row(row: AuditEventRow) -> StoredAuditEvent:
    return StoredAuditEvent(
        sequence=row.sequence,
        event=AuditEvent(
            id=AuditEventId(row.id),
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


def _incident_from_row(row: IncidentRow) -> Incident:
    return Incident(
        id=IncidentId(row.id),
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

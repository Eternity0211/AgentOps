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

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    AuthenticationError,
    CausationId,
    CorrelationId,
    EventMetadata,
    EventReason,
    IncidentId,
    IncidentState,
    Permission,
    Principal,
    Sha256Digest,
    as_utc,
    require_authenticated,
    require_permission,
    utc_now,
)
from agentops_incident_commander.infrastructure.persistence.models import (
    AuditEventRow,
    IdempotencyRecordRow,
    IncidentCancellationRequestRow,
    IncidentRow,
    IncidentTransitionRow,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    AuditRepository,
    IncidentRepository,
)

from .api_errors import common_error_responses, problem

PrincipalResolver = Callable[[Request], Awaitable[Principal | None]]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]
SessionFactory = async_sessionmaker[AsyncSession]


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IncidentView(ApiModel):
    id: str
    severity: str
    state: str
    version: int
    opened_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_requested_at: datetime | None


class IncidentPage(ApiModel):
    items: list[IncidentView]
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
        severity=row.severity,
        state=row.state,
        version=row.version,
        opened_at=row.opened_at,
        updated_at=row.updated_at,
        closed_at=row.closed_at,
        cancelled_at=row.cancelled_at,
        cancellation_requested_at=row.cancellation_requested_at,
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

    @router.get("/incidents", response_model=IncidentPage)
    async def list_incidents(
        session: Session,
        principal: Authenticated,
        limit: PageLimit = 50,
        cursor: str | None = None,
    ) -> IncidentPage:
        _authorized(principal, Permission.INCIDENT_READ)
        statement = select(IncidentRow).where(IncidentRow.tenant_id == principal.tenant_id.value)
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

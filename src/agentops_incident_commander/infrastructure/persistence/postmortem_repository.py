"""PostgreSQL storage for immutable postmortem revision history."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuditEvent,
    EventReason,
    EvidenceId,
    IncidentId,
    InvalidDomainValueError,
    PostmortemFactId,
    PostmortemId,
    PostmortemRevision,
    Sha256Digest,
    TenantId,
)

from .models import PostmortemRevisionRow, PostmortemRow
from .repositories import AuditRepository


def _revision_from_row(row: PostmortemRevisionRow) -> PostmortemRevision:
    revision = PostmortemRevision(
        PostmortemId(row.postmortem_id),
        TenantId(row.tenant_id),
        IncidentId(row.incident_id),
        AggregateVersion(row.version),
        Sha256Digest(row.source_draft_fingerprint),
        (
            None
            if row.parent_revision_fingerprint is None
            else Sha256Digest(row.parent_revision_fingerprint)
        ),
        ActorId(row.author_id),
        row.content,
        EventReason(row.change_summary),
        tuple(PostmortemFactId(value) for value in row.fact_ids),
        tuple(EvidenceId(value) for value in row.evidence_ids),
        row.created_at,
        row.schema_version,
    )
    if revision.fingerprint.value != row.revision_fingerprint:
        raise InvalidDomainValueError("stored postmortem revision fingerprint is corrupt")
    return revision


def _revision_row(revision: PostmortemRevision, audit_event: AuditEvent) -> PostmortemRevisionRow:
    return PostmortemRevisionRow(
        postmortem_id=revision.postmortem_id.value,
        tenant_id=revision.tenant_id.value,
        incident_id=revision.incident_id.value,
        version=revision.version.value,
        source_draft_fingerprint=revision.source_draft_fingerprint.value,
        parent_revision_fingerprint=(
            None
            if revision.parent_revision_fingerprint is None
            else revision.parent_revision_fingerprint.value
        ),
        revision_fingerprint=revision.fingerprint.value,
        author_id=revision.author_id.value,
        content=revision.content,
        change_summary=revision.change_summary.value,
        fact_ids=[value.value for value in revision.fact_ids],
        evidence_ids=[value.value for value in revision.evidence_ids],
        created_at=revision.created_at,
        audit_event_id=audit_event.id.value,
        schema_version=revision.schema_version,
    )


def _validate_audit(
    revision: PostmortemRevision, audit_event: AuditEvent, *, event_type: str
) -> None:
    if (
        audit_event.tenant_id != revision.tenant_id
        or audit_event.type != event_type
        or audit_event.actor_id != revision.author_id
        or audit_event.target.type != "postmortem.record"
        or audit_event.target.id != revision.postmortem_id
        or audit_event.occurred_at != revision.created_at
        or audit_event.result_hash != revision.fingerprint
    ):
        raise InvalidDomainValueError("postmortem revision audit binding is invalid")


class PostmortemRevisionRepository:
    """Atomic optimistic revision storage with append-only audit binding."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> PostmortemRevision | None:
        row = await self._session.scalar(
            select(PostmortemRevisionRow)
            .where(
                PostmortemRevisionRow.tenant_id == tenant_id.value,
                PostmortemRevisionRow.incident_id == incident_id.value,
            )
            .order_by(PostmortemRevisionRow.version.desc())
            .limit(1)
        )
        return None if row is None else _revision_from_row(row)

    async def list(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> tuple[PostmortemRevision, ...]:
        rows = (
            await self._session.scalars(
                select(PostmortemRevisionRow)
                .where(
                    PostmortemRevisionRow.tenant_id == tenant_id.value,
                    PostmortemRevisionRow.incident_id == incident_id.value,
                )
                .order_by(PostmortemRevisionRow.version)
            )
        ).all()
        return tuple(_revision_from_row(row) for row in rows)

    async def create(self, revision: PostmortemRevision, audit_event: AuditEvent) -> None:
        if revision.version != AggregateVersion.initial():
            raise InvalidDomainValueError("initial postmortem revision must be version one")
        _validate_audit(revision, audit_event, event_type="postmortem.created")
        self._session.add(
            PostmortemRow(
                id=revision.postmortem_id.value,
                tenant_id=revision.tenant_id.value,
                incident_id=revision.incident_id.value,
                source_draft_fingerprint=revision.source_draft_fingerprint.value,
                latest_version=revision.version.value,
                created_by=revision.author_id.value,
                created_at=revision.created_at,
                schema_version=revision.schema_version,
            )
        )
        await self._session.flush()
        self._session.add(_revision_row(revision, audit_event))
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()

    async def append(
        self,
        expected: PostmortemRevision,
        revision: PostmortemRevision,
        audit_event: AuditEvent,
    ) -> None:
        if (
            revision.postmortem_id != expected.postmortem_id
            or revision.tenant_id != expected.tenant_id
            or revision.incident_id != expected.incident_id
            or revision.version != expected.version.next()
            or revision.source_draft_fingerprint != expected.source_draft_fingerprint
            or revision.parent_revision_fingerprint != expected.fingerprint
            or revision.fact_ids != expected.fact_ids
            or revision.evidence_ids != expected.evidence_ids
            or revision.created_at < expected.created_at
        ):
            raise InvalidDomainValueError("postmortem revision does not extend expected history")
        _validate_audit(revision, audit_event, event_type="postmortem.revised")
        head = await self._session.scalar(
            select(PostmortemRow)
            .where(
                PostmortemRow.id == expected.postmortem_id.value,
                PostmortemRow.tenant_id == expected.tenant_id.value,
                PostmortemRow.incident_id == expected.incident_id.value,
            )
            .with_for_update()
        )
        if (
            head is None
            or head.latest_version != expected.version.value
            or head.source_draft_fingerprint != expected.source_draft_fingerprint.value
        ):
            raise InvalidDomainValueError("stale postmortem revision")
        current_row = await self._session.scalar(
            select(PostmortemRevisionRow).where(
                PostmortemRevisionRow.postmortem_id == expected.postmortem_id.value,
                PostmortemRevisionRow.version == expected.version.value,
            )
        )
        if current_row is None or _revision_from_row(current_row) != expected:
            raise InvalidDomainValueError("stored postmortem revision does not match expected")
        head.latest_version = revision.version.value
        self._session.add(_revision_row(revision, audit_event))
        await AuditRepository(self._session).append(audit_event)
        await self._session.flush()

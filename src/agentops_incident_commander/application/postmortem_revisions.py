"""Authorized versioned human revisions for evidence-bound postmortems."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuditEvent,
    AuditEventId,
    AuditTarget,
    CausationId,
    CorrelationId,
    EventReason,
    Incident,
    IncidentId,
    IncidentState,
    InvalidDomainValueError,
    Permission,
    PostmortemDraft,
    PostmortemId,
    PostmortemRevision,
    Principal,
    Sha256Digest,
    TenantId,
    as_utc,
    require_permission,
)


class PostmortemRevisionStore(Protocol):
    async def latest(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> PostmortemRevision | None: ...

    async def create(self, revision: PostmortemRevision, audit_event: AuditEvent) -> None: ...

    async def append(
        self,
        expected: PostmortemRevision,
        revision: PostmortemRevision,
        audit_event: AuditEvent,
    ) -> None: ...


class PostmortemRevisionIncidentReader(Protocol):
    async def get(self, tenant_id: TenantId, incident_id: IncidentId) -> Incident | None: ...


@dataclass(frozen=True, slots=True)
class CreatePostmortemRecord:
    draft: PostmortemDraft
    change_summary: EventReason
    correlation_id: CorrelationId
    causation_id: CausationId

    def __post_init__(self) -> None:
        if (
            not isinstance(self.draft, PostmortemDraft)
            or not isinstance(self.change_summary, EventReason)
            or not isinstance(self.correlation_id, CorrelationId)
            or not isinstance(self.causation_id, CausationId)
        ):
            raise InvalidDomainValueError("postmortem creation command is invalid")


@dataclass(frozen=True, slots=True)
class RevisePostmortem:
    tenant_id: TenantId
    incident_id: IncidentId
    expected_version: AggregateVersion
    expected_fingerprint: Sha256Digest
    content: str
    change_summary: EventReason
    correlation_id: CorrelationId
    causation_id: CausationId

    def __post_init__(self) -> None:
        values = (
            self.tenant_id,
            self.incident_id,
            self.expected_version,
            self.expected_fingerprint,
            self.change_summary,
            self.correlation_id,
            self.causation_id,
        )
        kinds = (
            TenantId,
            IncidentId,
            AggregateVersion,
            Sha256Digest,
            EventReason,
            CorrelationId,
            CausationId,
        )
        if any(not isinstance(value, kind) for value, kind in zip(values, kinds, strict=True)):
            raise InvalidDomainValueError("postmortem revision command is invalid")
        if not isinstance(self.content, str):
            raise InvalidDomainValueError("postmortem revision content must be text")


def _fingerprint(payload: dict[str, object]) -> Sha256Digest:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(encoded).hexdigest())


class PostmortemRevisionManager:
    """Create and revise postmortems without allowing source-reference mutation."""

    def __init__(
        self,
        incidents: PostmortemRevisionIncidentReader,
        store: PostmortemRevisionStore,
        *,
        clock: Callable[[], datetime],
        postmortem_id_factory: Callable[[], str],
        audit_id_factory: Callable[[], str],
    ) -> None:
        self._incidents = incidents
        self._store = store
        self._clock = clock
        self._postmortem_id_factory = postmortem_id_factory
        self._audit_id_factory = audit_id_factory

    async def create(
        self, command: CreatePostmortemRecord, *, principal: Principal | None
    ) -> PostmortemRevision:
        if not isinstance(command, CreatePostmortemRecord):
            raise InvalidDomainValueError("postmortem creation requires a typed command")
        actor = require_permission(
            principal, Permission.POSTMORTEM_EDIT, tenant_id=command.draft.tenant_id
        )
        await self._require_closed(command.draft.tenant_id, command.draft.incident_id)
        if await self._store.latest(command.draft.tenant_id, command.draft.incident_id) is not None:
            raise InvalidDomainValueError("postmortem already exists for Incident")
        created_at = as_utc(self._clock())
        if created_at < command.draft.generated_at:
            raise InvalidDomainValueError("postmortem record cannot predate its generated draft")
        revision = PostmortemRevision(
            PostmortemId(self._postmortem_id_factory()),
            command.draft.tenant_id,
            command.draft.incident_id,
            AggregateVersion.initial(),
            command.draft.fingerprint,
            None,
            actor.actor_id,
            command.draft.render_markdown(),
            command.change_summary,
            command.draft.fact_ids,
            command.draft.evidence_ids,
            created_at,
        )
        audit = self._audit(
            revision,
            actor.actor_id,
            command.correlation_id,
            command.causation_id,
            "postmortem.created",
            command.draft.fingerprint,
        )
        await self._store.create(revision, audit)
        return revision

    async def revise(
        self, command: RevisePostmortem, *, principal: Principal | None
    ) -> PostmortemRevision:
        if not isinstance(command, RevisePostmortem):
            raise InvalidDomainValueError("postmortem revision requires a typed command")
        actor = require_permission(
            principal, Permission.POSTMORTEM_EDIT, tenant_id=command.tenant_id
        )
        await self._require_closed(command.tenant_id, command.incident_id)
        current = await self._store.latest(command.tenant_id, command.incident_id)
        if current is None:
            raise InvalidDomainValueError("postmortem does not exist for Incident")
        if (
            current.version != command.expected_version
            or current.fingerprint != command.expected_fingerprint
        ):
            raise InvalidDomainValueError("stale postmortem revision")
        revised = current.revise(
            author_id=actor.actor_id,
            content=command.content,
            change_summary=command.change_summary,
            created_at=as_utc(self._clock()),
        )
        request_hash = _fingerprint(
            {
                "change_summary": command.change_summary.value,
                "content_hash": hashlib.sha256(command.content.encode()).hexdigest(),
                "expected_fingerprint": command.expected_fingerprint.value,
                "expected_version": command.expected_version.value,
                "incident_id": command.incident_id.value,
                "tenant_id": command.tenant_id.value,
            }
        )
        audit = self._audit(
            revised,
            actor.actor_id,
            command.correlation_id,
            command.causation_id,
            "postmortem.revised",
            request_hash,
        )
        await self._store.append(current, revised, audit)
        return revised

    async def _require_closed(self, tenant_id: TenantId, incident_id: IncidentId) -> None:
        incident = await self._incidents.get(tenant_id, incident_id)
        if (
            incident is None
            or incident.tenant_id != tenant_id
            or incident.state is not IncidentState.CLOSED
        ):
            raise InvalidDomainValueError("postmortem revision requires a CLOSED Incident")

    def _audit(
        self,
        revision: PostmortemRevision,
        actor_id: ActorId,
        correlation_id: CorrelationId,
        causation_id: CausationId,
        event_type: str,
        request_hash: Sha256Digest,
    ) -> AuditEvent:
        return AuditEvent(
            AuditEventId(self._audit_id_factory()),
            revision.tenant_id,
            event_type,
            1,
            "postmortem_revision/v1",
            actor_id,
            correlation_id,
            causation_id,
            AuditTarget("postmortem.record", revision.postmortem_id),
            revision.created_at,
            request_hash,
            revision.fingerprint,
        )

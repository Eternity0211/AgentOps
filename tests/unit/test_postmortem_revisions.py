"""Versioned postmortem revisions preserve sources, authorship, and audit."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    CreatePostmortemRecord,
    PostmortemRevisionManager,
    RevisePostmortem,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuditEvent,
    AuthenticationError,
    AuthorizationError,
    CausationId,
    ConfirmedPostmortemFact,
    CorrelationId,
    EventReason,
    EvidenceId,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    ModelCallId,
    PostmortemDraft,
    PostmortemDraftSection,
    PostmortemFactId,
    PostmortemFactKind,
    PostmortemId,
    PostmortemRevision,
    Principal,
    PromptId,
    PromptVersionReference,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
)

NOW = datetime(2026, 10, 9, 8, tzinfo=UTC)
TENANT = TenantId("tenant-1")
INCIDENT = IncidentId("incident-1")
DIGEST = Sha256Digest("a" * 64)


def principal(role: Role = Role.OPERATOR, *, tenant: str = "tenant-1") -> Principal:
    return Principal(ActorId("editor"), TenantId(tenant), frozenset({role}))


def incident(state: IncidentState = IncidentState.CLOSED, *, tenant: TenantId = TENANT) -> Incident:
    return Incident(
        INCIDENT,
        tenant,
        IncidentSeverity.SEV2,
        NOW,
        NOW + timedelta(hours=1),
        state,
        AggregateVersion(5),
        closed_at=NOW + timedelta(hours=1) if state is IncidentState.CLOSED else None,
    )


def draft() -> PostmortemDraft:
    fact = ConfirmedPostmortemFact(
        PostmortemFactId("fact-1"),
        TENANT,
        INCIDENT,
        PostmortemFactKind.ROOT_CAUSE,
        "Deployment v2 caused errors.",
        (EvidenceId("evidence-1"),),
        ActorId("commander"),
        NOW + timedelta(minutes=50),
    )
    return PostmortemDraft(
        TENANT,
        INCIDENT,
        PromptVersionReference(PromptId("postmortem"), SemanticVersion("1.0.0")),
        DIGEST,
        ModelCallId("model-call-1"),
        (PostmortemDraftSection(PostmortemFactKind.ROOT_CAUSE, (fact,)),),
        NOW + timedelta(hours=2),
    )


class IncidentReader:
    def __init__(self, value: Incident | None) -> None:
        self.value = value

    async def get(self, tenant_id: TenantId, incident_id: IncidentId) -> Incident | None:
        assert tenant_id == TENANT and incident_id == INCIDENT
        return self.value


class Store:
    def __init__(self, value: PostmortemRevision | None = None) -> None:
        self.value = value
        self.audits: list[AuditEvent] = []
        self.expected: PostmortemRevision | None = None

    async def latest(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> PostmortemRevision | None:
        assert tenant_id == TENANT and incident_id == INCIDENT
        return self.value

    async def create(self, revision: PostmortemRevision, audit_event: AuditEvent) -> None:
        self.value = revision
        self.audits.append(audit_event)

    async def append(
        self,
        expected: PostmortemRevision,
        revision: PostmortemRevision,
        audit_event: AuditEvent,
    ) -> None:
        self.expected = expected
        self.value = revision
        self.audits.append(audit_event)


def manager(
    store: Store,
    *,
    incident_value: Incident | None = None,
    at: datetime = NOW + timedelta(hours=3),
) -> PostmortemRevisionManager:
    return PostmortemRevisionManager(
        IncidentReader(incident() if incident_value is None else incident_value),
        store,
        clock=lambda: at,
        postmortem_id_factory=lambda: "postmortem-1",
        audit_id_factory=lambda: f"audit-{len(store.audits) + 1}",
    )


def create_command() -> CreatePostmortemRecord:
    return CreatePostmortemRecord(
        draft(),
        EventReason("Initialize the reviewable draft"),
        CorrelationId("correlation-1"),
        CausationId("cause-1"),
    )


def revision_command(current: PostmortemRevision, **changes: Any) -> RevisePostmortem:
    values: dict[str, object] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "expected_version": current.version,
        "expected_fingerprint": current.fingerprint,
        "content": "# Human revision\n\nClarified impact without changing sources.",
        "change_summary": EventReason("Clarify incident impact"),
        "correlation_id": CorrelationId("correlation-2"),
        "causation_id": CausationId("cause-2"),
    }
    values.update(changes)
    return RevisePostmortem(**values)  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_create_and_revise_preserve_sources_and_record_authorship() -> None:
    store = Store()
    service = manager(store)
    initial = await service.create(create_command(), principal=principal())
    revised = await service.revise(revision_command(initial), principal=principal())

    assert initial.postmortem_id == PostmortemId("postmortem-1")
    assert initial.version == AggregateVersion.initial()
    assert initial.content == draft().render_markdown()
    assert revised.version == AggregateVersion(2)
    assert revised.parent_revision_fingerprint == initial.fingerprint
    assert revised.fact_ids == initial.fact_ids
    assert revised.evidence_ids == initial.evidence_ids
    assert revised.author_id == ActorId("editor")
    assert store.expected == initial
    assert [event.type for event in store.audits] == [
        "postmortem.created",
        "postmortem.revised",
    ]
    assert all(event.target.id == initial.postmortem_id for event in store.audits)
    assert store.audits[-1].result_hash == revised.fingerprint


@pytest.mark.parametrize(
    ("actor", "error"),
    (
        (None, AuthenticationError),
        (principal(Role.VIEWER), AuthorizationError),
        (principal(tenant="tenant-2"), AuthorizationError),
    ),
)
@pytest.mark.anyio
async def test_create_rejects_unauthorized_editor(
    actor: Principal | None, error: type[Exception]
) -> None:
    store = Store()
    with pytest.raises(error):
        await manager(store).create(create_command(), principal=actor)
    assert store.value is None and not store.audits


@pytest.mark.parametrize(
    "actor",
    (None, principal(Role.VIEWER), principal(tenant="tenant-2")),
)
@pytest.mark.anyio
async def test_revise_rejects_unauthorized_editor(actor: Principal | None) -> None:
    store = Store()
    initial = await manager(store).create(create_command(), principal=principal())
    with pytest.raises((AuthenticationError, AuthorizationError)):
        await manager(store).revise(revision_command(initial), principal=actor)
    assert store.value == initial and len(store.audits) == 1


@pytest.mark.parametrize(
    "incident_value",
    (
        cast(Incident | None, None),
        incident(IncidentState.RESOLVED),
        incident(tenant=TenantId("tenant-2")),
    ),
)
@pytest.mark.anyio
async def test_creation_requires_owned_closed_incident(incident_value: Incident | None) -> None:
    store = Store()
    service = PostmortemRevisionManager(
        IncidentReader(incident_value),
        store,
        clock=lambda: NOW + timedelta(hours=3),
        postmortem_id_factory=lambda: "postmortem-1",
        audit_id_factory=lambda: "audit-1",
    )
    with pytest.raises(InvalidDomainValueError, match="CLOSED"):
        await service.create(create_command(), principal=principal())


@pytest.mark.anyio
async def test_duplicate_missing_and_stale_revision_fail_closed() -> None:
    store = Store()
    service = manager(store)
    initial = await service.create(create_command(), principal=principal())
    with pytest.raises(InvalidDomainValueError, match="already exists"):
        await service.create(create_command(), principal=principal())

    missing = Store()
    with pytest.raises(InvalidDomainValueError, match="does not exist"):
        await manager(missing).revise(revision_command(initial), principal=principal())

    with pytest.raises(InvalidDomainValueError, match="stale"):
        await service.revise(
            revision_command(initial, expected_version=AggregateVersion(99)),
            principal=principal(),
        )
    with pytest.raises(InvalidDomainValueError, match="stale"):
        await service.revise(
            revision_command(initial, expected_fingerprint=Sha256Digest("b" * 64)),
            principal=principal(),
        )


@pytest.mark.anyio
async def test_create_cannot_predate_generated_draft() -> None:
    with pytest.raises(InvalidDomainValueError, match="predate"):
        await manager(Store(), at=NOW + timedelta(hours=1)).create(
            create_command(), principal=principal()
        )


def revision() -> PostmortemRevision:
    return PostmortemRevision(
        PostmortemId("postmortem-1"),
        TENANT,
        INCIDENT,
        AggregateVersion.initial(),
        DIGEST,
        None,
        ActorId("editor"),
        "Initial content",
        EventReason("Initial version"),
        (PostmortemFactId("fact-1"),),
        (EvidenceId("evidence-1"),),
        NOW,
    )


def test_revision_normalizes_content_and_has_stable_fingerprint() -> None:
    value = revision()
    assert value.content == "Initial content\n"
    assert value.fingerprint == revision().fingerprint
    next_value = value.revise(
        author_id=ActorId("editor-2"),
        content="Updated content",
        change_summary=EventReason("Update"),
        created_at=NOW + timedelta(minutes=1),
    )
    assert next_value.fact_ids == value.fact_ids
    assert next_value.evidence_ids == value.evidence_ids
    assert next_value.version == value.version.next()


@pytest.mark.parametrize(
    "changes",
    (
        {"postmortem_id": cast(PostmortemId, "bad")},
        {"parent_revision_fingerprint": DIGEST},
        {"content": " "},
        {"content": "bad\x00content"},
        {"content": cast(str, 3)},
        {"content": "x" * 65_537},
        {"fact_ids": ()},
        {"fact_ids": (PostmortemFactId("fact-1"), PostmortemFactId("fact-1"))},
        {"evidence_ids": ()},
        {"evidence_ids": (EvidenceId("evidence-1"), EvidenceId("evidence-1"))},
        {"schema_version": "2.0.0"},
    ),
)
def test_revision_rejects_invalid_identity_content_references_and_schema(
    changes: dict[str, object],
) -> None:
    with pytest.raises(InvalidDomainValueError):
        replace(revision(), **changes)  # type: ignore[arg-type]


def test_later_revision_requires_parent_and_monotonic_time() -> None:
    with pytest.raises(InvalidDomainValueError, match="requires its parent"):
        replace(revision(), version=AggregateVersion(2))
    with pytest.raises(InvalidDomainValueError, match="predate"):
        revision().revise(
            author_id=ActorId("editor"),
            content="older",
            change_summary=EventReason("Older"),
            created_at=NOW - timedelta(seconds=1),
        )


def test_typed_commands_reject_untyped_values() -> None:
    with pytest.raises(InvalidDomainValueError, match="creation command"):
        replace(create_command(), draft=cast(PostmortemDraft, "bad"))
    with pytest.raises(InvalidDomainValueError, match="revision command"):
        replace(revision_command(revision()), tenant_id=cast(TenantId, "bad"))
    with pytest.raises(InvalidDomainValueError, match="content must be text"):
        replace(revision_command(revision()), content=cast(str, 3))


@pytest.mark.anyio
async def test_manager_rejects_untyped_commands() -> None:
    service = manager(Store())
    with pytest.raises(InvalidDomainValueError, match="typed command"):
        await service.create(cast(CreatePostmortemRecord, object()), principal=principal())
    with pytest.raises(InvalidDomainValueError, match="typed command"):
        await service.revise(cast(RevisePostmortem, object()), principal=principal())

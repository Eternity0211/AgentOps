"""Durable, proposal-bound human Approval interrupt tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import ValidationError

from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Approval,
    ApprovalId,
    ApprovalInvalidation,
    ApprovalStatus,
    EventReason,
    IncidentId,
    InvalidDomainValueError,
    NaiveDateTimeError,
    OpaqueIdentifier,
    RiskLevel,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.infrastructure import (
    ApprovalCheckpointIdentity,
    approval_checkpoint_config,
    diagnosis_checkpoint_serializer,
)
from agentops_incident_commander.workflows import (
    ApprovalGraphPhase,
    ApprovalRuntimeContext,
    ApprovalWaitState,
    build_approval_graph,
)

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)


class ApprovalStore:
    def __init__(
        self,
        approval: Approval | None,
        invalidation: ApprovalInvalidation | None = None,
    ) -> None:
        self.approval = approval
        self.invalidation = invalidation
        self.reads = 0

    async def get(self, approval_id: ApprovalId, *, tenant_id: TenantId) -> Approval | None:
        self.reads += 1
        if self.approval is None:
            return None
        if self.approval.id != approval_id or self.approval.tenant_id != tenant_id:
            return None
        return self.approval

    async def get_invalidation(
        self,
        approval_id: ApprovalId,
        *,
        tenant_id: TenantId,
    ) -> ApprovalInvalidation | None:
        if self.invalidation is None:
            return None
        if self.invalidation.approval_id != approval_id or self.invalidation.tenant_id != tenant_id:
            return None
        return self.invalidation


def approval(**overrides: Any) -> Approval:
    values: dict[str, Any] = {
        "id": ApprovalId("approval-1"),
        "tenant_id": TenantId("tenant-1"),
        "incident_id": IncidentId("incident-1"),
        "proposal_id": OpaqueIdentifier("proposal-1"),
        "proposal_version": 1,
        "proposal_fingerprint": Sha256Digest("a" * 64),
        "policy_decision_id": OpaqueIdentifier("policy-1"),
        "policy_decision_fingerprint": Sha256Digest("b" * 64),
        "policy_input_fingerprint": Sha256Digest("c" * 64),
        "proposer_actor_id": ActorId("operator-1"),
        "risk_level": RiskLevel.HIGH,
        "independent_approver_required": True,
        "status": ApprovalStatus.PENDING,
        "version": AggregateVersion(1),
        "requested_at": NOW,
        "expires_at": NOW + timedelta(minutes=30),
    }
    values.update(overrides)
    return Approval(**values)


def invalidation(value: Approval) -> ApprovalInvalidation:
    return ApprovalInvalidation(
        approval_id=value.id,
        tenant_id=value.tenant_id,
        incident_id=value.incident_id,
        approval_fingerprint=value.fingerprint,
        prior_proposal_fingerprint=value.proposal_fingerprint,
        replacement_proposal_id=OpaqueIdentifier("proposal-2"),
        replacement_proposal_version=2,
        replacement_proposal_fingerprint=Sha256Digest("d" * 64),
        replacement_material_fingerprint=Sha256Digest("e" * 64),
        invalidated_by=ActorId("operator-2"),
        invalidated_at=NOW + timedelta(minutes=2),
    )


def state(**overrides: Any) -> ApprovalWaitState:
    values: dict[str, Any] = {
        "state_schema_version": "1.0.0",
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
        "approval_id": "approval-1",
        "proposal_fingerprint": "a" * 64,
        "policy_decision_fingerprint": "b" * 64,
        "phase": ApprovalGraphPhase.AWAITING_APPROVAL,
        "checkpoint_sequence": 0,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ApprovalWaitState.model_validate(values)


def runtime(
    store: ApprovalStore, *, now: datetime = NOW + timedelta(minutes=5)
) -> ApprovalRuntimeContext:
    return ApprovalRuntimeContext(approvals=store, clock=lambda: now)


def graph() -> Any:
    return build_approval_graph(checkpointer=InMemorySaver(serde=diagnosis_checkpoint_serializer()))


@pytest.mark.anyio
async def test_interrupt_contains_only_stable_references_and_reloads_approved_record() -> None:
    value = approval()
    store = ApprovalStore(value)
    initial = state()
    config = approval_checkpoint_config(initial)
    compiled = graph()

    paused = await compiled.ainvoke(initial, config, context=runtime(store))
    payload = paused["__interrupt__"][0].value
    assert payload == {
        "kind": "APPROVAL_REQUIRED",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "approval_id": "approval-1",
        "proposal_fingerprint": "a" * 64,
        "policy_decision_fingerprint": "b" * 64,
    }
    assert store.reads == 0

    store.approval = value.decide(
        ApprovalStatus.APPROVED,
        actor_id=ActorId("approver-1"),
        reason=EventReason("approved after review"),
        at=NOW + timedelta(minutes=4),
    )
    resumed = await compiled.ainvoke(
        Command[Any](resume={"action": "RECHECK"}), config, context=runtime(store)
    )

    assert resumed["phase"] is ApprovalGraphPhase.READY_TO_EXECUTE
    assert resumed["error_code"] is None
    assert resumed["checkpoint_sequence"] == 1
    assert store.reads == 1


@pytest.mark.anyio
async def test_pending_approval_reinterrupts_and_never_trusts_resume_claims() -> None:
    value = approval()
    store = ApprovalStore(value)
    initial = state(workflow_run_id="run-pending")
    config = approval_checkpoint_config(initial)
    compiled = graph()
    await compiled.ainvoke(initial, config, context=runtime(store))

    with pytest.raises(InvalidDomainValueError, match="directive is invalid"):
        await compiled.ainvoke(
            Command[Any](resume={"action": "RECHECK", "approved": True}),
            config,
            context=runtime(store),
        )

    snapshot = await compiled.aget_state(config)
    assert snapshot.values["phase"] == ApprovalGraphPhase.AWAITING_APPROVAL.value
    assert store.reads == 0


@pytest.mark.anyio
async def test_pending_recheck_creates_another_interrupt_then_can_be_approved() -> None:
    value = approval()
    store = ApprovalStore(value)
    initial = state(workflow_run_id="run-repeat")
    config = approval_checkpoint_config(initial)
    compiled = graph()
    await compiled.ainvoke(initial, config, context=runtime(store))

    pending = await compiled.ainvoke(
        Command[Any](resume={"action": "RECHECK"}), config, context=runtime(store)
    )
    assert pending["__interrupt__"][0].value["kind"] == "APPROVAL_REQUIRED"
    assert pending["checkpoint_sequence"] == 1

    store.approval = value.decide(
        ApprovalStatus.APPROVED,
        actor_id=ActorId("approver-1"),
        reason=EventReason("approved"),
        at=NOW + timedelta(minutes=6),
    )
    complete = await compiled.ainvoke(
        Command[Any](resume={"action": "RECHECK"}), config, context=runtime(store)
    )
    assert complete["phase"] is ApprovalGraphPhase.READY_TO_EXECUTE
    assert complete["checkpoint_sequence"] == 2
    assert store.reads == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stored", "marker", "now", "error_code"),
    [
        (None, None, NOW + timedelta(minutes=5), "APPROVAL_NOT_FOUND"),
        (approval(), invalidation(approval()), NOW + timedelta(minutes=5), "APPROVAL_INVALIDATED"),
        (
            approval(incident_id=IncidentId("incident-other")),
            None,
            NOW + timedelta(minutes=5),
            "APPROVAL_MISMATCH",
        ),
        (
            approval(proposal_fingerprint=Sha256Digest("f" * 64)),
            None,
            NOW + timedelta(minutes=5),
            "APPROVAL_MISMATCH",
        ),
        (
            approval(policy_decision_fingerprint=Sha256Digest("f" * 64)),
            None,
            NOW + timedelta(minutes=5),
            "APPROVAL_MISMATCH",
        ),
        (approval(), None, NOW + timedelta(minutes=30), "APPROVAL_EXPIRED"),
        (
            approval().decide(
                ApprovalStatus.EXPIRED,
                actor_id=ActorId("expiry-worker"),
                reason=EventReason("deadline reached"),
                at=NOW + timedelta(minutes=30),
            ),
            None,
            NOW + timedelta(minutes=31),
            "APPROVAL_EXPIRED",
        ),
        (
            approval().decide(
                ApprovalStatus.REJECTED,
                actor_id=ActorId("approver-1"),
                reason=EventReason("unsafe"),
                at=NOW + timedelta(minutes=4),
            ),
            None,
            NOW + timedelta(minutes=5),
            "APPROVAL_REJECTED",
        ),
    ],
)
async def test_invalid_or_non_approved_records_route_to_human_without_execution(
    stored: Approval | None,
    marker: ApprovalInvalidation | None,
    now: datetime,
    error_code: str,
) -> None:
    store = ApprovalStore(stored, marker)
    initial = state(workflow_run_id=f"run-{error_code.lower()}")
    config = approval_checkpoint_config(initial)
    compiled = graph()
    await compiled.ainvoke(initial, config, context=runtime(store, now=now))

    result = await compiled.ainvoke(
        Command[Any](resume={"action": "RECHECK"}),
        config,
        context=runtime(store, now=now),
    )
    assert result["phase"] is ApprovalGraphPhase.NEEDS_HUMAN
    assert result["error_code"] == error_code


@pytest.mark.anyio
async def test_cross_tenant_lookup_cannot_resolve_approval() -> None:
    store = ApprovalStore(approval())
    initial = state(tenant_id="tenant-other", workflow_run_id="run-cross-tenant")
    config = approval_checkpoint_config(initial)
    compiled = graph()
    await compiled.ainvoke(initial, config, context=runtime(store))
    result = await compiled.ainvoke(
        Command[Any](resume={"action": "RECHECK"}), config, context=runtime(store)
    )
    assert result["error_code"] == "APPROVAL_NOT_FOUND"


def test_approval_checkpoint_identity_is_stable_isolated_and_content_free() -> None:
    initial = state()
    identity = ApprovalCheckpointIdentity.from_state(initial)
    assert approval_checkpoint_config(initial) == identity.config()
    assert identity.thread_id.startswith("approval-")
    assert "tenant-1" not in identity.thread_id
    assert (
        identity.thread_id
        != ApprovalCheckpointIdentity.from_state(state(workflow_run_id="run-2")).thread_id
    )
    identity.require_matches(initial)
    with pytest.raises(InvalidDomainValueError, match="does not match"):
        identity.require_matches(state(correlation_id="correlation-2"))


@pytest.mark.parametrize("value", ["", "bad value", 1])
def test_approval_checkpoint_identity_rejects_invalid_values(value: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="identifiers are invalid"):
        ApprovalCheckpointIdentity(value, "incident-1", "run-1", "correlation-1")
    with pytest.raises(InvalidDomainValueError, match="requires Approval"):
        ApprovalCheckpointIdentity.from_state(value)


@pytest.mark.anyio
async def test_graph_rejects_non_awaiting_initial_state_and_naive_clock() -> None:
    compiled = graph()
    not_waiting = state(phase=ApprovalGraphPhase.READY_TO_EXECUTE)
    with pytest.raises(InvalidDomainValueError, match="requires awaiting state"):
        await compiled.ainvoke(
            not_waiting,
            approval_checkpoint_config(not_waiting),
            context=runtime(ApprovalStore(approval())),
        )

    initial = state(workflow_run_id="run-naive-clock")
    config = approval_checkpoint_config(initial)
    await compiled.ainvoke(initial, config, context=runtime(ApprovalStore(approval())))
    with pytest.raises(NaiveDateTimeError, match="timezone-aware"):
        await compiled.ainvoke(
            Command[Any](resume={"action": "RECHECK"}),
            config,
            context=runtime(ApprovalStore(approval()), now=NOW.replace(tzinfo=None)),
        )


def test_wait_state_is_strict_normalizes_time_and_forbids_mutation() -> None:
    restored = state(phase="AWAITING_APPROVAL", updated_at=NOW.astimezone())
    assert restored.phase is ApprovalGraphPhase.AWAITING_APPROVAL
    assert restored.updated_at.tzinfo is UTC
    with pytest.raises(ValueError, match="timezone-aware"):
        state(updated_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="frozen"):
        restored.phase = ApprovalGraphPhase.NEEDS_HUMAN


@pytest.mark.anyio
async def test_postgres_approval_checkpointer_rejects_non_postgres_url() -> None:
    from agentops_incident_commander.infrastructure import postgres_approval_checkpointer

    with pytest.raises(InvalidDomainValueError, match="must use PostgreSQL"):
        async with postgres_approval_checkpointer("sqlite:///unsafe.db"):
            pytest.fail("invalid URL must not yield")

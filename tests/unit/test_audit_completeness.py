"""Closed-path and fail-closed tests for workflow audit completeness."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    AUDIT_COMPLETENESS_RULES_VERSION,
    AUDIT_COMPLETENESS_SCHEMA_VERSION,
    MAX_AUDIT_REQUIREMENTS,
    MAX_AUDIT_WORKFLOW_EVENTS,
    WORKFLOW_AUDIT_PATHS,
    ActorId,
    AuditEvent,
    AuditEventId,
    AuditPathRequirement,
    AuditRequirementStatus,
    AuditSubjectBinding,
    AuditTarget,
    CausationId,
    CorrelationId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Sha256Digest,
    StoredAuditEvent,
    TenantId,
    WorkflowAuditExpectation,
    WorkflowAuditPath,
    WorkflowAuditPathDefinition,
    audit_event_fingerprint,
    evaluate_workflow_audit_completeness,
    require_workflow_audit_complete,
)

NOW = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
TENANT = TenantId("tenant-audit-completeness")
TARGET_TYPES = {
    "approval": "approval.record",
    "diagnosis_report": "diagnosis.report",
    "execution": "action.execution",
    "gate_decision": "evidence.gate_decision",
    "incident": "incident.lifecycle",
    "model_call": "model.call",
    "postmortem": "postmortem.record",
    "tool_call": "tool.call",
    "verification": "health.verification",
}


def expectation(path: WorkflowAuditPath) -> WorkflowAuditExpectation:
    definition = WORKFLOW_AUDIT_PATHS[path]
    subjects = tuple(
        (
            key,
            AuditSubjectBinding(
                AuditTarget(TARGET_TYPES[key], OpaqueIdentifier(f"{key}-1")),
                CorrelationId(f"correlation-{key}"),
                CausationId(f"causation-{key}"),
            ),
        )
        for key in sorted(definition.subject_keys)
    )
    return WorkflowAuditExpectation(TENANT, path, subjects)


def stored_event(
    *,
    sequence: int,
    event_type: str,
    schema: str,
    binding: AuditSubjectBinding,
    tenant: TenantId = TENANT,
    event_id: str | None = None,
) -> StoredAuditEvent:
    event = AuditEvent(
        id=AuditEventId(event_id or f"audit-{sequence}"),
        tenant_id=tenant,
        type=event_type,
        event_version=1,
        payload_schema_version=schema,
        actor_id=ActorId("workflow-audit-test"),
        correlation_id=binding.correlation_id,
        causation_id=binding.causation_id or CausationId("fallback-causation"),
        target=binding.target,
        occurred_at=NOW + timedelta(seconds=sequence),
        request_hash=Sha256Digest("1" * 64),
        result_hash=Sha256Digest("2" * 64),
    )
    return StoredAuditEvent(sequence, sequence, event, audit_event_fingerprint(event))


def complete_events(path: WorkflowAuditPath) -> tuple[StoredAuditEvent, ...]:
    expected = expectation(path)
    events = []
    sequence = 1
    for requirement in WORKFLOW_AUDIT_PATHS[path].requirements:
        for _ in range(requirement.minimum):
            events.append(
                stored_event(
                    sequence=sequence,
                    event_type=requirement.event_type,
                    schema=requirement.payload_schema_version,
                    binding=expected.binding(requirement.subject_key),
                )
            )
            sequence += 1
    return tuple(events)


@pytest.mark.parametrize("path", tuple(WorkflowAuditPath))
def test_every_declared_workflow_path_has_a_complete_audit_assertion(
    path: WorkflowAuditPath,
) -> None:
    expected = expectation(path)
    result = require_workflow_audit_complete(expected, complete_events(path))

    assert result.complete
    assert result.path is path
    assert result.schema_version == AUDIT_COMPLETENESS_SCHEMA_VERSION
    assert result.rules_version == AUDIT_COMPLETENESS_RULES_VERSION
    assert result.expected_minimum_events == len(complete_events(path))
    assert result.observed_relevant_events == len(complete_events(path))
    assert result.missing_requirements == 0
    assert result.excess_requirements == 0
    assert result.invalid_requirements == 0
    assert result.order_violations == 0
    assert result.selection_authority
    assert all(item.status is AuditRequirementStatus.SATISFIED for item in result.requirements)


def test_catalog_is_closed_and_each_result_family_uses_deterministic_authority() -> None:
    assert frozenset(WORKFLOW_AUDIT_PATHS) == frozenset(WorkflowAuditPath)
    assert len(WORKFLOW_AUDIT_PATHS) == 33
    for path, definition in WORKFLOW_AUDIT_PATHS.items():
        assert definition.path is path
        assert definition.subject_keys
        assert "model confidence" not in definition.selection_authority.lower()


def test_missing_excess_forbidden_invalid_and_out_of_order_events_fail_closed() -> None:
    path = WorkflowAuditPath.TOOL_SUCCEEDED
    expected = expectation(path)
    complete = complete_events(path)

    missing = evaluate_workflow_audit_completeness(expected, complete[1:])
    assert not missing.complete
    assert missing.missing_requirements == 1
    assert missing.requirements[0].status is AuditRequirementStatus.MISSING

    extra_started = stored_event(
        sequence=3,
        event_type="tool.call_started",
        schema="tool-call/v1",
        binding=expected.binding("tool_call"),
    )
    excess = evaluate_workflow_audit_completeness(expected, (*complete, extra_started))
    assert excess.excess_requirements == 1
    assert excess.requirements[0].status is AuditRequirementStatus.EXCESS

    retry = stored_event(
        sequence=3,
        event_type="tool.call_retried",
        schema="tool-call/v1",
        binding=expected.binding("tool_call"),
    )
    forbidden = evaluate_workflow_audit_completeness(expected, (*complete, retry))
    assert forbidden.excess_requirements == 1
    assert forbidden.requirements[1].status is AuditRequirementStatus.FORBIDDEN_PRESENT

    invalid_event = replace(
        complete[0].event,
        payload_schema_version="wrong/v1",
    )
    invalid_stored = StoredAuditEvent(
        complete[0].sequence,
        complete[0].tenant_sequence,
        invalid_event,
        audit_event_fingerprint(invalid_event),
    )
    invalid = evaluate_workflow_audit_completeness(expected, (invalid_stored, complete[1]))
    assert invalid.invalid_requirements == 1
    assert invalid.requirements[0].status is AuditRequirementStatus.INVALID_BINDING
    assert invalid.requirements[0].invalid_sequences == (1,)

    terminal_first = replace(complete[1], sequence=1, tenant_sequence=1)
    started_second = replace(complete[0], sequence=2, tenant_sequence=2)
    ordered = evaluate_workflow_audit_completeness(expected, (terminal_first, started_second))
    assert ordered.order_violations == 1
    assert ordered.requirements[-3].status is AuditRequirementStatus.ORDER_VIOLATION

    with pytest.raises(InvalidDomainValueError, match="workflow audit is incomplete"):
        require_workflow_audit_complete(expected, complete[1:])


def test_unrelated_events_and_sequence_gaps_do_not_change_a_bound_path() -> None:
    path = WorkflowAuditPath.MODEL_SUCCEEDED
    expected = expectation(path)
    first, second = complete_events(path)
    unrelated_binding = AuditSubjectBinding(
        AuditTarget("tool.call", OpaqueIdentifier("unrelated-tool")),
        CorrelationId("unrelated-correlation"),
    )
    unrelated = stored_event(
        sequence=4,
        event_type="tool.call_started",
        schema="tool-call/v1",
        binding=unrelated_binding,
    )
    events = (
        replace(first, sequence=2, tenant_sequence=3),
        replace(second, sequence=3, tenant_sequence=5),
        replace(unrelated, sequence=9, tenant_sequence=12),
    )
    result = evaluate_workflow_audit_completeness(expected, events)
    assert result.complete
    assert result.observed_relevant_events == 2


@pytest.mark.parametrize(
    ("events", "message"),
    (
        (cast(Any, []), "bounded tuple"),
        (cast(Any, tuple(object() for _ in range(MAX_AUDIT_WORKFLOW_EVENTS + 1))), "bounded tuple"),
        ((cast(Any, object()),), "invalid stored event"),
    ),
)
def test_event_collection_shape_is_validated(events: Any, message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        evaluate_workflow_audit_completeness(expectation(WorkflowAuditPath.MODEL_PENDING), events)


def test_event_scope_rejects_cross_tenant_order_and_duplicate_identity() -> None:
    expected = expectation(WorkflowAuditPath.MODEL_SUCCEEDED)
    first, second = complete_events(WorkflowAuditPath.MODEL_SUCCEEDED)
    cross = stored_event(
        sequence=1,
        event_type=first.event.type,
        schema=first.event.payload_schema_version,
        binding=expected.binding("model_call"),
        tenant=TenantId("tenant-other"),
    )
    with pytest.raises(InvalidDomainValueError, match="cross-tenant"):
        evaluate_workflow_audit_completeness(expected, (cross,))
    with pytest.raises(InvalidDomainValueError, match="strictly ordered"):
        evaluate_workflow_audit_completeness(expected, (second, first))
    duplicate_id_event = replace(second.event, id=first.event.id)
    duplicate_id = StoredAuditEvent(
        2,
        2,
        duplicate_id_event,
        audit_event_fingerprint(duplicate_id_event),
    )
    with pytest.raises(InvalidDomainValueError, match="duplicate event identity"):
        evaluate_workflow_audit_completeness(expected, (first, duplicate_id))


@pytest.mark.parametrize(
    "kwargs",
    (
        {"key": "Bad"},
        {"subject_key": "Bad"},
        {"minimum": -1},
        {"minimum": 2, "maximum": 1},
        {"maximum": 129},
        {"minimum": True},
        {"after": cast(Any, ["started"])},
        {"after": ("Bad",)},
        {"event_type": "bad"},
        {"payload_schema_version": "bad"},
    ),
)
def test_requirement_rejects_invalid_contracts(kwargs: dict[str, object]) -> None:
    values: dict[str, object] = {
        "key": "started",
        "subject_key": "tool_call",
        "event_type": "tool.call_started",
        "payload_schema_version": "tool-call/v1",
    }
    values.update(kwargs)
    with pytest.raises(InvalidDomainValueError):
        AuditPathRequirement(**cast(Any, values))


def test_path_definition_rejects_ambiguous_or_unbounded_rules() -> None:
    rule = AuditPathRequirement("started", "tool_call", "tool.call_started", "tool-call/v1")
    with pytest.raises(InvalidDomainValueError, match="path is invalid"):
        WorkflowAuditPathDefinition(cast(Any, "BAD"), (rule,), "authority")
    for requirements in (cast(Any, []), (), tuple(rule for _ in range(MAX_AUDIT_REQUIREMENTS + 1))):
        with pytest.raises(InvalidDomainValueError, match="requirements are invalid"):
            WorkflowAuditPathDefinition(WorkflowAuditPath.TOOL_SUCCEEDED, requirements, "authority")
    with pytest.raises(InvalidDomainValueError, match="keys must be unique"):
        WorkflowAuditPathDefinition(WorkflowAuditPath.TOOL_SUCCEEDED, (rule, rule), "authority")
    with pytest.raises(InvalidDomainValueError, match="requirement type"):
        WorkflowAuditPathDefinition(
            WorkflowAuditPath.TOOL_SUCCEEDED, (cast(Any, object()),), "authority"
        )
    later = replace(rule, key="terminal", after=("missing",))
    with pytest.raises(InvalidDomainValueError, match="earlier requirement"):
        WorkflowAuditPathDefinition(WorkflowAuditPath.TOOL_SUCCEEDED, (rule, later), "authority")
    with pytest.raises(InvalidDomainValueError, match="authority is required"):
        WorkflowAuditPathDefinition(WorkflowAuditPath.TOOL_SUCCEEDED, (rule,), "")


def test_subject_and_expectation_contracts_are_exact() -> None:
    target = AuditTarget("model.call", OpaqueIdentifier("model-1"))
    correlation = CorrelationId("correlation-model")
    with pytest.raises(InvalidDomainValueError, match="binding types"):
        AuditSubjectBinding(cast(Any, "target"), correlation)
    with pytest.raises(InvalidDomainValueError, match="binding types"):
        AuditSubjectBinding(target, cast(Any, "correlation"))
    with pytest.raises(InvalidDomainValueError, match="causation"):
        AuditSubjectBinding(target, correlation, cast(Any, "causation"))

    binding = AuditSubjectBinding(target, correlation)
    valid_subjects = (("model_call", binding),)
    with pytest.raises(InvalidDomainValueError, match="scope"):
        WorkflowAuditExpectation(
            cast(Any, "tenant"), WorkflowAuditPath.MODEL_PENDING, valid_subjects
        )
    with pytest.raises(InvalidDomainValueError, match="scope"):
        WorkflowAuditExpectation(TENANT, cast(Any, "path"), valid_subjects)
    with pytest.raises(InvalidDomainValueError, match="must be a tuple"):
        WorkflowAuditExpectation(TENANT, WorkflowAuditPath.MODEL_PENDING, cast(Any, []))
    for subjects in (
        (("Bad", binding),),
        (("model_call", binding), ("model_call", binding)),
    ):
        with pytest.raises(InvalidDomainValueError, match="subject keys"):
            WorkflowAuditExpectation(TENANT, WorkflowAuditPath.MODEL_PENDING, subjects)
    with pytest.raises(InvalidDomainValueError, match="subject binding"):
        WorkflowAuditExpectation(
            TENANT,
            WorkflowAuditPath.MODEL_PENDING,
            (("model_call", cast(Any, object())),),
        )
    with pytest.raises(InvalidDomainValueError, match="do not match"):
        WorkflowAuditExpectation(
            TENANT,
            WorkflowAuditPath.MODEL_PENDING,
            (("tool_call", binding),),
        )


def test_evaluator_requires_typed_expectation_and_optional_causation_is_not_inferred() -> None:
    with pytest.raises(InvalidDomainValueError, match="expectation is invalid"):
        evaluate_workflow_audit_completeness(cast(Any, object()), ())

    expected = expectation(WorkflowAuditPath.MODEL_PENDING)
    binding = expected.binding("model_call")
    unbound = WorkflowAuditExpectation(
        TENANT,
        expected.path,
        (("model_call", replace(binding, causation_id=None)),),
    )
    event = complete_events(expected.path)[0]
    assert evaluate_workflow_audit_completeness(unbound, (event,)).complete


def test_wrong_correlation_causation_and_event_version_are_invalid_bindings() -> None:
    expected = expectation(WorkflowAuditPath.MODEL_PENDING)
    original = complete_events(expected.path)[0]
    mutations = (
        {"correlation_id": CorrelationId("wrong-correlation")},
        {"causation_id": CausationId("wrong-causation")},
        {"event_version": 2},
    )
    for mutation in mutations:
        event = replace(original.event, **mutation)
        stored = StoredAuditEvent(1, 1, event, audit_event_fingerprint(event))
        result = evaluate_workflow_audit_completeness(expected, (stored,))
        assert result.requirements[0].status is AuditRequirementStatus.INVALID_BINDING

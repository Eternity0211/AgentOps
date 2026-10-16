"""Versioned, deterministic completeness assertions for authoritative audit paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .audit import AuditTarget, StoredAuditEvent
from .errors import InvalidDomainValueError
from .tools import MAX_TOOL_ATTEMPTS
from .values import CausationId, CorrelationId, OpaqueIdentifier, TenantId

AUDIT_COMPLETENESS_SCHEMA_VERSION: Final = "audit-completeness/v1"
AUDIT_COMPLETENESS_RULES_VERSION: Final = "1.0.0"
MAX_AUDIT_WORKFLOW_EVENTS: Final = 512
MAX_AUDIT_REQUIREMENTS: Final = 32
MAX_AUDIT_EVENT_REPETITIONS: Final = 128

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class WorkflowAuditPath(StrEnum):
    """Closed catalog of authoritative core workflow boundary outcomes."""

    INVESTIGATION_STARTED = "INVESTIGATION_STARTED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    TOOL_REJECTED = "TOOL_REJECTED"
    TOOL_SUCCEEDED = "TOOL_SUCCEEDED"
    TOOL_FAILED = "TOOL_FAILED"
    TOOL_RETRIED_SUCCEEDED = "TOOL_RETRIED_SUCCEEDED"
    TOOL_RETRIED_FAILED = "TOOL_RETRIED_FAILED"
    MODEL_PENDING = "MODEL_PENDING"
    MODEL_SUCCEEDED = "MODEL_SUCCEEDED"
    MODEL_FAILED = "MODEL_FAILED"
    MODEL_TIMED_OUT = "MODEL_TIMED_OUT"
    MODEL_REFUSED = "MODEL_REFUSED"
    DIAGNOSIS_PASSED = "DIAGNOSIS_PASSED"
    DIAGNOSIS_REPLAN = "DIAGNOSIS_REPLAN"
    DIAGNOSIS_HANDOFF = "DIAGNOSIS_HANDOFF"
    APPROVAL_PAUSED = "APPROVAL_PAUSED"
    APPROVAL_RESUMED = "APPROVAL_RESUMED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    APPROVAL_INVALIDATED = "APPROVAL_INVALIDATED"
    EXECUTION_IN_PROGRESS = "EXECUTION_IN_PROGRESS"
    EXECUTION_SUCCEEDED = "EXECUTION_SUCCEEDED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    EXECUTION_TIMED_OUT = "EXECUTION_TIMED_OUT"
    EXECUTION_UNCERTAIN = "EXECUTION_UNCERTAIN"
    EXECUTION_REPLAYED_IN_PROGRESS = "EXECUTION_REPLAYED_IN_PROGRESS"
    EXECUTION_REPLAYED_TERMINAL = "EXECUTION_REPLAYED_TERMINAL"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED_REDIAGNOSE = "VERIFICATION_FAILED_REDIAGNOSE"
    VERIFICATION_FAILED_HANDOFF = "VERIFICATION_FAILED_HANDOFF"
    VERIFICATION_FAILED_CANCELLED = "VERIFICATION_FAILED_CANCELLED"
    POSTMORTEM_CREATED = "POSTMORTEM_CREATED"
    POSTMORTEM_REVISED = "POSTMORTEM_REVISED"


class AuditRequirementStatus(StrEnum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    EXCESS = "EXCESS"
    FORBIDDEN_PRESENT = "FORBIDDEN_PRESENT"
    INVALID_BINDING = "INVALID_BINDING"
    ORDER_VIOLATION = "ORDER_VIOLATION"


@dataclass(frozen=True, slots=True)
class AuditPathRequirement:
    """One cardinality and ordering rule for a bound audit subject."""

    key: str
    subject_key: str
    event_type: str
    payload_schema_version: str
    minimum: int = 1
    maximum: int = 1
    after: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _KEY_PATTERN.fullmatch(self.key) is None:
            raise InvalidDomainValueError("audit requirement key is invalid")
        if _KEY_PATTERN.fullmatch(self.subject_key) is None:
            raise InvalidDomainValueError("audit requirement subject key is invalid")
        if (
            not isinstance(self.minimum, int)
            or isinstance(self.minimum, bool)
            or not isinstance(self.maximum, int)
            or isinstance(self.maximum, bool)
            or self.minimum < 0
            or self.maximum < self.minimum
            or self.maximum > MAX_AUDIT_EVENT_REPETITIONS
        ):
            raise InvalidDomainValueError("audit requirement cardinality is invalid")
        if not isinstance(self.after, tuple) or any(
            _KEY_PATTERN.fullmatch(key) is None for key in self.after
        ):
            raise InvalidDomainValueError("audit requirement ordering keys are invalid")
        # Reuse the audited value objects to validate event and schema syntax.
        try:
            AuditTarget(self.event_type, OpaqueIdentifier("audit-requirement"))
        except InvalidDomainValueError as error:
            raise InvalidDomainValueError("audit requirement event type is invalid") from error
        if (
            re.fullmatch(
                r"^[a-z][a-z0-9_-]{0,31}/v[1-9][0-9]*$",
                self.payload_schema_version,
            )
            is None
        ):
            raise InvalidDomainValueError("audit requirement payload schema is invalid")


@dataclass(frozen=True, slots=True)
class WorkflowAuditPathDefinition:
    path: WorkflowAuditPath
    requirements: tuple[AuditPathRequirement, ...]
    selection_authority: str

    def __post_init__(self) -> None:
        if not isinstance(self.path, WorkflowAuditPath):
            raise InvalidDomainValueError("workflow audit path is invalid")
        if (
            not isinstance(self.requirements, tuple)
            or not self.requirements
            or len(self.requirements) > MAX_AUDIT_REQUIREMENTS
        ):
            raise InvalidDomainValueError("workflow audit requirements are invalid")
        if any(
            not isinstance(requirement, AuditPathRequirement) for requirement in self.requirements
        ):
            raise InvalidDomainValueError("workflow audit requirement type is invalid")
        keys = tuple(requirement.key for requirement in self.requirements)
        if len(set(keys)) != len(keys):
            raise InvalidDomainValueError("workflow audit requirement keys must be unique")
        seen: set[str] = set()
        for requirement in self.requirements:
            if any(key not in seen for key in requirement.after):
                raise InvalidDomainValueError(
                    "workflow audit ordering must reference an earlier requirement"
                )
            seen.add(requirement.key)
        if not isinstance(self.selection_authority, str) or not self.selection_authority:
            raise InvalidDomainValueError("workflow audit selection authority is required")

    @property
    def subject_keys(self) -> frozenset[str]:
        return frozenset(requirement.subject_key for requirement in self.requirements)


@dataclass(frozen=True, slots=True)
class AuditSubjectBinding:
    """Expected target and propagation identity loaded from an authoritative record."""

    target: AuditTarget
    correlation_id: CorrelationId
    causation_id: CausationId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, AuditTarget) or not isinstance(
            self.correlation_id, CorrelationId
        ):
            raise InvalidDomainValueError("audit subject binding types are invalid")
        if self.causation_id is not None and not isinstance(self.causation_id, CausationId):
            raise InvalidDomainValueError("audit subject causation is invalid")


@dataclass(frozen=True, slots=True)
class WorkflowAuditExpectation:
    """A catalog path bound to exact records selected by deterministic authority."""

    tenant_id: TenantId
    path: WorkflowAuditPath
    subjects: tuple[tuple[str, AuditSubjectBinding], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId) or not isinstance(self.path, WorkflowAuditPath):
            raise InvalidDomainValueError("workflow audit expectation scope is invalid")
        if not isinstance(self.subjects, tuple):
            raise InvalidDomainValueError("workflow audit subjects must be a tuple")
        keys = tuple(key for key, _ in self.subjects)
        if any(_KEY_PATTERN.fullmatch(key) is None for key in keys) or len(set(keys)) != len(keys):
            raise InvalidDomainValueError("workflow audit subject keys are invalid")
        if any(not isinstance(binding, AuditSubjectBinding) for _, binding in self.subjects):
            raise InvalidDomainValueError("workflow audit subject binding is invalid")
        expected = WORKFLOW_AUDIT_PATHS[self.path].subject_keys
        if frozenset(keys) != expected:
            raise InvalidDomainValueError("workflow audit subjects do not match the path")

    def binding(self, key: str) -> AuditSubjectBinding:
        for subject_key, binding in self.subjects:
            if subject_key == key:
                return binding
        raise InvalidDomainValueError("workflow audit subject is missing")  # pragma: no cover


@dataclass(frozen=True, slots=True)
class AuditRequirementResult:
    key: str
    event_type: str
    status: AuditRequirementStatus
    observed_sequences: tuple[int, ...]
    invalid_sequences: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WorkflowAuditCompleteness:
    schema_version: str
    rules_version: str
    path: WorkflowAuditPath
    complete: bool
    expected_minimum_events: int
    observed_relevant_events: int
    missing_requirements: int
    excess_requirements: int
    invalid_requirements: int
    order_violations: int
    selection_authority: str
    requirements: tuple[AuditRequirementResult, ...]


def _required(
    key: str,
    subject: str,
    event_type: str,
    schema: str,
    *,
    after: tuple[str, ...] = (),
    minimum: int = 1,
    maximum: int = 1,
) -> AuditPathRequirement:
    return AuditPathRequirement(key, subject, event_type, schema, minimum, maximum, after)


def _forbidden(key: str, subject: str, event_type: str, schema: str) -> AuditPathRequirement:
    return AuditPathRequirement(key, subject, event_type, schema, 0, 0)


def _definition(
    path: WorkflowAuditPath,
    requirements: tuple[AuditPathRequirement, ...],
    authority: str,
) -> WorkflowAuditPathDefinition:
    return WorkflowAuditPathDefinition(path, requirements, authority)


def _tool_terminal(
    path: WorkflowAuditPath, terminal: str, *, retried: bool
) -> WorkflowAuditPathDefinition:
    requirements = [
        _required("started", "tool_call", "tool.call_started", "tool-call/v1"),
    ]
    if retried:
        requirements.append(
            _required(
                "retried",
                "tool_call",
                "tool.call_retried",
                "tool-call/v1",
                after=("started",),
                maximum=MAX_TOOL_ATTEMPTS - 1,
            )
        )
    else:
        requirements.append(
            _forbidden("no_retry", "tool_call", "tool.call_retried", "tool-call/v1")
        )
    requirements.extend(
        (
            _required(
                "terminal",
                "tool_call",
                terminal,
                "tool-call/v1",
                after=("started", "retried") if retried else ("started",),
            ),
            _forbidden(
                "opposite_terminal",
                "tool_call",
                "tool.call_failed" if terminal.endswith("succeeded") else "tool.call_succeeded",
                "tool-call/v1",
            ),
            _forbidden("not_rejected", "tool_call", "tool.call_rejected", "tool-call/v1"),
        )
    )
    return _definition(path, tuple(requirements), "ToolCallResult or raised ToolGatewayError")


def _model_terminal(path: WorkflowAuditPath) -> WorkflowAuditPathDefinition:
    return _definition(
        path,
        (
            _required("started", "model_call", "model.call_started", "model_call/v1"),
            _required(
                "finished",
                "model_call",
                "model.call_finished",
                "model_call/v1",
                after=("started",),
            ),
        ),
        "ModelCallTrace.status",
    )


def _diagnosis(path: WorkflowAuditPath) -> WorkflowAuditPathDefinition:
    return _definition(
        path,
        (
            _required(
                "report", "diagnosis_report", "diagnosis.report_recorded", "diagnosis_report/v1"
            ),
            _required(
                "gate",
                "gate_decision",
                "evidence.gate_decided",
                "evidence_gate/v1",
                after=("report",),
            ),
        ),
        "EvidenceGateDecision plus deterministic GateRoute",
    )


def _approval_terminal(path: WorkflowAuditPath, event_type: str) -> WorkflowAuditPathDefinition:
    competing = tuple(
        _forbidden(
            f"not_{candidate.rsplit('.', 1)[1]}",
            "approval",
            candidate,
            "approval/v1",
        )
        for candidate in ("approval.approved", "approval.rejected", "approval.expired")
        if candidate != event_type
    )
    return _definition(
        path,
        (
            _required("requested", "approval", "approval.requested", "approval/v1"),
            _required(
                "decision",
                "approval",
                event_type,
                "approval/v1",
                after=("requested",),
            ),
            *competing,
        ),
        "Approval.status",
    )


def _execution_terminal(path: WorkflowAuditPath) -> WorkflowAuditPathDefinition:
    return _definition(
        path,
        (
            _required("started", "execution", "action.execution_started", "action_execution/v1"),
            _required(
                "incident_started",
                "incident",
                "action.execution_incident_started",
                "action_execution_incident/v1",
                after=("started",),
            ),
            _required(
                "finished",
                "execution",
                "action.execution_finished",
                "action_execution/v1",
                after=("started",),
            ),
            _required(
                "incident_routed",
                "incident",
                "action.execution_incident_routed",
                "action_execution_incident/v1",
                after=("finished", "incident_started"),
            ),
            _forbidden(
                "not_replayed",
                "execution",
                "action.execution_replayed",
                "action_execution/v1",
            ),
        ),
        "ActionExecution.status and persisted Incident route",
    )


def _verification(
    path: WorkflowAuditPath, terminal: str, schema: str
) -> WorkflowAuditPathDefinition:
    opposite = (
        ("health.verification_failed", "health_verification_failure/v1")
        if terminal.endswith("succeeded")
        else ("health.verification_succeeded", "health_verification_closure/v1")
    )
    return _definition(
        path,
        (
            _required(
                "decided",
                "verification",
                "health.verification_decided",
                "health_verification/v1",
            ),
            _required(
                "routed",
                "incident",
                terminal,
                schema,
                after=("decided",),
            ),
            _forbidden("opposite_route", "incident", opposite[0], opposite[1]),
        ),
        "HealthVerificationDecision plus persisted Incident transition route",
    )


WORKFLOW_AUDIT_PATHS: Final[dict[WorkflowAuditPath, WorkflowAuditPathDefinition]] = {
    WorkflowAuditPath.INVESTIGATION_STARTED: _definition(
        WorkflowAuditPath.INVESTIGATION_STARTED,
        (
            _required(
                "control",
                "incident",
                "incident.investigation_started",
                "incident-control/v1",
            ),
        ),
        "Incident transition",
    ),
    WorkflowAuditPath.CANCELLATION_REQUESTED: _definition(
        WorkflowAuditPath.CANCELLATION_REQUESTED,
        (
            _required(
                "control",
                "incident",
                "incident.cancellation_requested",
                "incident-control/v1",
            ),
        ),
        "IncidentCancellationRequest disposition",
    ),
    WorkflowAuditPath.TOOL_REJECTED: _definition(
        WorkflowAuditPath.TOOL_REJECTED,
        (
            _required("rejected", "tool_call", "tool.call_rejected", "tool-call/v1"),
            _forbidden("not_started", "tool_call", "tool.call_started", "tool-call/v1"),
            _forbidden("not_succeeded", "tool_call", "tool.call_succeeded", "tool-call/v1"),
            _forbidden("not_failed", "tool_call", "tool.call_failed", "tool-call/v1"),
            _forbidden("not_retried", "tool_call", "tool.call_retried", "tool-call/v1"),
        ),
        "Tool Gateway pre-dispatch result",
    ),
    WorkflowAuditPath.TOOL_SUCCEEDED: _tool_terminal(
        WorkflowAuditPath.TOOL_SUCCEEDED, "tool.call_succeeded", retried=False
    ),
    WorkflowAuditPath.TOOL_FAILED: _tool_terminal(
        WorkflowAuditPath.TOOL_FAILED, "tool.call_failed", retried=False
    ),
    WorkflowAuditPath.TOOL_RETRIED_SUCCEEDED: _tool_terminal(
        WorkflowAuditPath.TOOL_RETRIED_SUCCEEDED, "tool.call_succeeded", retried=True
    ),
    WorkflowAuditPath.TOOL_RETRIED_FAILED: _tool_terminal(
        WorkflowAuditPath.TOOL_RETRIED_FAILED, "tool.call_failed", retried=True
    ),
    WorkflowAuditPath.MODEL_PENDING: _definition(
        WorkflowAuditPath.MODEL_PENDING,
        (
            _required("started", "model_call", "model.call_started", "model_call/v1"),
            _forbidden("not_finished", "model_call", "model.call_finished", "model_call/v1"),
        ),
        "ModelCallTrace.status",
    ),
    **{
        path: _model_terminal(path)
        for path in (
            WorkflowAuditPath.MODEL_SUCCEEDED,
            WorkflowAuditPath.MODEL_FAILED,
            WorkflowAuditPath.MODEL_TIMED_OUT,
            WorkflowAuditPath.MODEL_REFUSED,
        )
    },
    **{
        path: _diagnosis(path)
        for path in (
            WorkflowAuditPath.DIAGNOSIS_PASSED,
            WorkflowAuditPath.DIAGNOSIS_REPLAN,
            WorkflowAuditPath.DIAGNOSIS_HANDOFF,
        )
    },
    WorkflowAuditPath.APPROVAL_PAUSED: _definition(
        WorkflowAuditPath.APPROVAL_PAUSED,
        (
            _required("requested", "approval", "approval.requested", "approval/v1"),
            _forbidden("not_approved", "approval", "approval.approved", "approval/v1"),
            _forbidden("not_rejected", "approval", "approval.rejected", "approval/v1"),
            _forbidden("not_expired", "approval", "approval.expired", "approval/v1"),
        ),
        "Approval.status=PENDING and LangGraph interrupt",
    ),
    WorkflowAuditPath.APPROVAL_RESUMED: _approval_terminal(
        WorkflowAuditPath.APPROVAL_RESUMED, "approval.approved"
    ),
    WorkflowAuditPath.APPROVAL_REJECTED: _approval_terminal(
        WorkflowAuditPath.APPROVAL_REJECTED, "approval.rejected"
    ),
    WorkflowAuditPath.APPROVAL_EXPIRED: _approval_terminal(
        WorkflowAuditPath.APPROVAL_EXPIRED, "approval.expired"
    ),
    WorkflowAuditPath.APPROVAL_INVALIDATED: _definition(
        WorkflowAuditPath.APPROVAL_INVALIDATED,
        (
            _required("requested", "approval", "approval.requested", "approval/v1"),
            _required(
                "invalidated",
                "approval",
                "approval.invalidated",
                "approval_invalidation/v1",
                after=("requested",),
            ),
        ),
        "ApprovalInvalidation record",
    ),
    WorkflowAuditPath.EXECUTION_IN_PROGRESS: _definition(
        WorkflowAuditPath.EXECUTION_IN_PROGRESS,
        (
            _required("started", "execution", "action.execution_started", "action_execution/v1"),
            _required(
                "incident_started",
                "incident",
                "action.execution_incident_started",
                "action_execution_incident/v1",
                after=("started",),
            ),
            _forbidden(
                "not_finished",
                "execution",
                "action.execution_finished",
                "action_execution/v1",
            ),
            _forbidden(
                "not_replayed",
                "execution",
                "action.execution_replayed",
                "action_execution/v1",
            ),
        ),
        "ActionExecution.status=IN_PROGRESS",
    ),
    **{
        path: _execution_terminal(path)
        for path in (
            WorkflowAuditPath.EXECUTION_SUCCEEDED,
            WorkflowAuditPath.EXECUTION_FAILED,
            WorkflowAuditPath.EXECUTION_TIMED_OUT,
            WorkflowAuditPath.EXECUTION_UNCERTAIN,
        )
    },
    WorkflowAuditPath.EXECUTION_REPLAYED_IN_PROGRESS: _definition(
        WorkflowAuditPath.EXECUTION_REPLAYED_IN_PROGRESS,
        (
            _required("started", "execution", "action.execution_started", "action_execution/v1"),
            _required(
                "incident_started",
                "incident",
                "action.execution_incident_started",
                "action_execution_incident/v1",
                after=("started",),
            ),
            _required(
                "replayed",
                "execution",
                "action.execution_replayed",
                "action_execution/v1",
                after=("started",),
                maximum=MAX_AUDIT_EVENT_REPETITIONS,
            ),
            _forbidden(
                "not_finished",
                "execution",
                "action.execution_finished",
                "action_execution/v1",
            ),
        ),
        "ActionExecution replay result while IN_PROGRESS",
    ),
    WorkflowAuditPath.EXECUTION_REPLAYED_TERMINAL: _definition(
        WorkflowAuditPath.EXECUTION_REPLAYED_TERMINAL,
        (
            _required("started", "execution", "action.execution_started", "action_execution/v1"),
            _required(
                "incident_started",
                "incident",
                "action.execution_incident_started",
                "action_execution_incident/v1",
                after=("started",),
            ),
            _required(
                "finished",
                "execution",
                "action.execution_finished",
                "action_execution/v1",
                after=("started",),
            ),
            _required(
                "incident_routed",
                "incident",
                "action.execution_incident_routed",
                "action_execution_incident/v1",
                after=("finished", "incident_started"),
            ),
            _required(
                "replayed",
                "execution",
                "action.execution_replayed",
                "action_execution/v1",
                after=("finished", "incident_routed"),
                maximum=MAX_AUDIT_EVENT_REPETITIONS,
            ),
        ),
        "ActionExecution terminal replay result",
    ),
    WorkflowAuditPath.VERIFICATION_PASSED: _verification(
        WorkflowAuditPath.VERIFICATION_PASSED,
        "health.verification_succeeded",
        "health_verification_closure/v1",
    ),
    **{
        path: _verification(
            path,
            "health.verification_failed",
            "health_verification_failure/v1",
        )
        for path in (
            WorkflowAuditPath.VERIFICATION_FAILED_REDIAGNOSE,
            WorkflowAuditPath.VERIFICATION_FAILED_HANDOFF,
            WorkflowAuditPath.VERIFICATION_FAILED_CANCELLED,
        )
    },
    WorkflowAuditPath.POSTMORTEM_CREATED: _definition(
        WorkflowAuditPath.POSTMORTEM_CREATED,
        (_required("created", "postmortem", "postmortem.created", "postmortem_revision/v1"),),
        "PostmortemRevision version=1",
    ),
    WorkflowAuditPath.POSTMORTEM_REVISED: _definition(
        WorkflowAuditPath.POSTMORTEM_REVISED,
        (
            _required("created", "postmortem", "postmortem.created", "postmortem_revision/v1"),
            _required(
                "revised",
                "postmortem",
                "postmortem.revised",
                "postmortem_revision/v1",
                after=("created",),
                maximum=MAX_AUDIT_EVENT_REPETITIONS,
            ),
        ),
        "PostmortemRevision version history",
    ),
}

if frozenset(WORKFLOW_AUDIT_PATHS) != frozenset(WorkflowAuditPath):  # pragma: no cover
    raise RuntimeError("workflow audit path catalog is incomplete")


def evaluate_workflow_audit_completeness(
    expectation: WorkflowAuditExpectation,
    events: tuple[StoredAuditEvent, ...],
) -> WorkflowAuditCompleteness:
    """Check exact event bindings, cardinality, and order without deciding an outcome."""
    if not isinstance(expectation, WorkflowAuditExpectation):
        raise InvalidDomainValueError("workflow audit expectation is invalid")
    if not isinstance(events, tuple) or len(events) > MAX_AUDIT_WORKFLOW_EVENTS:
        raise InvalidDomainValueError("workflow audit event set must be a bounded tuple")
    _validate_event_scope(expectation, events)
    definition = WORKFLOW_AUDIT_PATHS[expectation.path]
    results: list[AuditRequirementResult] = []
    valid_by_key: dict[str, tuple[StoredAuditEvent, ...]] = {}
    relevant_sequences: set[int] = set()

    for requirement in definition.requirements:
        binding = expectation.binding(requirement.subject_key)
        candidates = tuple(
            stored
            for stored in events
            if stored.event.target.type == binding.target.type
            and stored.event.target.id.value == binding.target.id.value
            and stored.event.type == requirement.event_type
        )
        valid = tuple(
            stored for stored in candidates if _event_matches(requirement, binding, stored)
        )
        invalid = tuple(stored for stored in candidates if stored not in valid)
        valid_by_key[requirement.key] = valid
        relevant_sequences.update(stored.sequence for stored in candidates)
        status = _cardinality_status(requirement, valid, invalid)
        if status is AuditRequirementStatus.SATISFIED and valid:
            predecessor_sequences = [
                stored.sequence for key in requirement.after for stored in valid_by_key[key]
            ]
            if predecessor_sequences and min(stored.sequence for stored in valid) <= max(
                predecessor_sequences
            ):
                status = AuditRequirementStatus.ORDER_VIOLATION
        results.append(
            AuditRequirementResult(
                key=requirement.key,
                event_type=requirement.event_type,
                status=status,
                observed_sequences=tuple(stored.sequence for stored in valid),
                invalid_sequences=tuple(stored.sequence for stored in invalid),
            )
        )

    complete = all(result.status is AuditRequirementStatus.SATISFIED for result in results)
    return WorkflowAuditCompleteness(
        schema_version=AUDIT_COMPLETENESS_SCHEMA_VERSION,
        rules_version=AUDIT_COMPLETENESS_RULES_VERSION,
        path=expectation.path,
        complete=complete,
        expected_minimum_events=sum(item.minimum for item in definition.requirements),
        observed_relevant_events=len(relevant_sequences),
        missing_requirements=sum(item.status is AuditRequirementStatus.MISSING for item in results),
        excess_requirements=sum(
            item.status in {AuditRequirementStatus.EXCESS, AuditRequirementStatus.FORBIDDEN_PRESENT}
            for item in results
        ),
        invalid_requirements=sum(
            item.status is AuditRequirementStatus.INVALID_BINDING for item in results
        ),
        order_violations=sum(
            item.status is AuditRequirementStatus.ORDER_VIOLATION for item in results
        ),
        selection_authority=definition.selection_authority,
        requirements=tuple(results),
    )


def require_workflow_audit_complete(
    expectation: WorkflowAuditExpectation,
    events: tuple[StoredAuditEvent, ...],
) -> WorkflowAuditCompleteness:
    """Fail closed when one authoritative path lacks a complete audit projection."""
    result = evaluate_workflow_audit_completeness(expectation, events)
    if not result.complete:
        failures = ",".join(
            f"{item.key}:{item.status.value}"
            for item in result.requirements
            if item.status is not AuditRequirementStatus.SATISFIED
        )
        raise InvalidDomainValueError(
            f"workflow audit is incomplete for {result.path.value}: {failures}"
        )
    return result


def _validate_event_scope(
    expectation: WorkflowAuditExpectation,
    events: tuple[StoredAuditEvent, ...],
) -> None:
    previous_global = 0
    previous_tenant = 0
    event_ids: set[str] = set()
    for stored in events:
        if not isinstance(stored, StoredAuditEvent):
            raise InvalidDomainValueError("workflow audit contains an invalid stored event")
        if stored.event.tenant_id != expectation.tenant_id:
            raise InvalidDomainValueError("workflow audit contains a cross-tenant event")
        if stored.sequence <= previous_global or stored.tenant_sequence <= previous_tenant:
            raise InvalidDomainValueError("workflow audit events are not strictly ordered")
        if stored.event.id.value in event_ids:
            raise InvalidDomainValueError("workflow audit contains a duplicate event identity")
        previous_global = stored.sequence
        previous_tenant = stored.tenant_sequence
        event_ids.add(stored.event.id.value)


def _event_matches(
    requirement: AuditPathRequirement,
    binding: AuditSubjectBinding,
    stored: StoredAuditEvent,
) -> bool:
    event = stored.event
    return (
        event.event_version == 1
        and event.payload_schema_version == requirement.payload_schema_version
        and event.correlation_id == binding.correlation_id
        and (binding.causation_id is None or event.causation_id == binding.causation_id)
    )


def _cardinality_status(
    requirement: AuditPathRequirement,
    valid: tuple[StoredAuditEvent, ...],
    invalid: tuple[StoredAuditEvent, ...],
) -> AuditRequirementStatus:
    if invalid:
        return AuditRequirementStatus.INVALID_BINDING
    count = len(valid)
    if requirement.maximum == 0 and count:
        return AuditRequirementStatus.FORBIDDEN_PRESENT
    if count < requirement.minimum:
        return AuditRequirementStatus.MISSING
    if count > requirement.maximum:
        return AuditRequirementStatus.EXCESS
    return AuditRequirementStatus.SATISFIED

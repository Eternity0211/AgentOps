"""Single-path rollback execution, verification, and routing tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from test_action_execution_preflight import (
    authority_values,
    request,
)
from test_health_verification import decision, execution

from agentops_incident_commander.application import (
    RollbackRecoveryCoordinator,
    RollbackRecoveryOutcome,
    RollbackRecoveryResult,
)
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    AggregateVersion,
    ApprovalId,
    CausationId,
    CorrelationId,
    HealthVerificationDecision,
    HealthVerificationOutcome,
    HealthVerificationReasonCode,
    IdempotencyKey,
    Incident,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyDecision,
    PolicyEvaluationInput,
    Principal,
    RollbackServiceRequest,
    Sha256Digest,
)
from agentops_incident_commander.workflows import RemediationProposal

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
CORRELATION = CorrelationId("correlation-recovery")
CAUSATION = CausationId("causation-recovery")


def inputs() -> tuple[
    RollbackServiceRequest,
    RemediationProposal,
    PolicyEvaluationInput,
    PolicyDecision,
    ActionExecution,
]:
    rollback_request = request()
    proposed, evaluated_input, evaluated, _ = authority_values()
    base = execution()
    bound_target = replace(base.target, tenant_id=evaluated_input.tenant_id)
    before = replace(
        base.before_snapshot,
        tenant_id=evaluated_input.tenant_id,
        incident_id=rollback_request.incident_id,
    )
    assert base.after_snapshot is not None
    after = replace(
        base.after_snapshot,
        tenant_id=evaluated_input.tenant_id,
        incident_id=rollback_request.incident_id,
    )
    completed = replace(
        base,
        tenant_id=evaluated_input.tenant_id,
        incident_id=rollback_request.incident_id,
        approval_id=rollback_request.approval_id,
        idempotency_key=rollback_request.idempotency_key,
        proposal_fingerprint=proposed.fingerprint,
        policy_decision_fingerprint=evaluated.fingerprint,
        target=bound_target,
        before_snapshot=before,
        after_snapshot=after,
    )
    return rollback_request, proposed, evaluated_input, evaluated, completed


def verification(
    completed: ActionExecution, *, passed: bool = True, **overrides: Any
) -> HealthVerificationDecision:
    values: dict[str, Any] = {
        "tenant_id": completed.tenant_id,
        "incident_id": completed.incident_id,
        "action_execution_id": completed.id,
        "execution_fingerprint": completed.fingerprint,
    }
    if not passed:
        values.update(
            outcome=HealthVerificationOutcome.FAIL,
            reasons=(HealthVerificationReasonCode.P95_LATENCY_ABOVE_LIMIT,),
        )
    values.update(overrides)
    return decision(**values)


def routed_incident(execution_result: ActionExecution, state: IncidentState) -> Incident:
    return Incident(
        execution_result.incident_id,
        execution_result.tenant_id,
        IncidentSeverity.SEV2,
        NOW - timedelta(hours=1),
        NOW,
        state,
        AggregateVersion(10),
        closed_at=NOW if state is IncidentState.CLOSED else None,
    )


class Executor:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def execute(self, *_: object, **__: object) -> ActionExecution:
        self.calls += 1
        return cast(ActionExecution, self.result)


class Verifier:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[ActionExecution] = []

    async def verify(
        self,
        execution_result: ActionExecution,
        *,
        principal: Principal | None,
        correlation_id: CorrelationId,
    ) -> HealthVerificationDecision:
        del principal
        assert correlation_id == CORRELATION
        self.calls.append(execution_result)
        return cast(HealthVerificationDecision, self.result)


class SuccessRouter:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def close(self, *_: object, **__: object) -> Incident:
        self.calls += 1
        return cast(Incident, self.result)


class FailureRouter:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[int] = []

    async def route(self, *_: object, **kwargs: object) -> Incident:
        self.calls.append(cast(int, kwargs["used_rediagnosis_attempts"]))
        return cast(Incident, self.result)


async def recover(
    coordinator: RollbackRecoveryCoordinator,
    values: tuple[
        RollbackServiceRequest,
        RemediationProposal,
        PolicyEvaluationInput,
        PolicyDecision,
        ActionExecution,
    ],
    *,
    used: int = 0,
) -> RollbackRecoveryResult:
    rollback_request, proposed, evaluated_input, evaluated, _ = values
    return await coordinator.recover(
        rollback_request,
        proposed,
        evaluated_input,
        evaluated,
        used_rediagnosis_attempts=used,
        principal=None,
        correlation_id=CORRELATION,
        causation_id=CAUSATION,
    )


@pytest.mark.anyio
async def test_passing_verification_is_the_only_route_to_closed() -> None:
    values = inputs()
    completed = values[-1]
    passed = verification(completed)
    closed = routed_incident(completed, IncidentState.CLOSED)
    executor = Executor(completed)
    verifier = Verifier(passed)
    success = SuccessRouter(closed)
    failure = FailureRouter(closed)

    result = await recover(
        RollbackRecoveryCoordinator(executor, verifier, success, failure), values
    )

    assert result == RollbackRecoveryResult(
        completed, RollbackRecoveryOutcome.CLOSED, passed, closed
    )
    assert executor.calls == success.calls == 1
    assert verifier.calls == [completed]
    assert failure.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (IncidentState.INVESTIGATING, RollbackRecoveryOutcome.REDIAGNOSE),
        (IncidentState.NEEDS_HUMAN, RollbackRecoveryOutcome.NEEDS_HUMAN),
    ],
)
async def test_failed_verification_uses_only_non_compensable_route(
    state: IncidentState, expected: RollbackRecoveryOutcome
) -> None:
    values = inputs()
    completed = values[-1]
    failed = verification(completed, passed=False)
    routed = routed_incident(completed, state)
    success = SuccessRouter(routed)
    failure = FailureRouter(routed)

    result = await recover(
        RollbackRecoveryCoordinator(Executor(completed), Verifier(failed), success, failure),
        values,
        used=1,
    )

    assert result.outcome is expected
    assert result.incident == routed
    assert success.calls == 0
    assert failure.calls == [1]


@pytest.mark.anyio
async def test_non_successful_execution_never_reaches_verifier_or_router() -> None:
    values = inputs()
    completed = values[-1]
    started = replace(
        completed,
        status=ActionExecutionStatus.STARTED,
        after_snapshot=None,
        failure_code=None,
        completed_at=None,
        version=AggregateVersion.initial(),
    )
    verifier = Verifier(verification(completed))
    success = SuccessRouter(routed_incident(completed, IncidentState.CLOSED))
    failure = FailureRouter(routed_incident(completed, IncidentState.NEEDS_HUMAN))

    result = await recover(
        RollbackRecoveryCoordinator(Executor(started), verifier, success, failure), values
    )

    assert result.outcome is RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED
    assert result.execution == started
    assert verifier.calls == []
    assert success.calls == 0
    assert failure.calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "changes",
    [
        {"incident_id": execution().incident_id},
        {"action_execution_id": OpaqueIdentifier("substituted-execution")},
        {"execution_fingerprint": execution().fingerprint},
    ],
)
async def test_substituted_verification_is_rejected_before_routing(
    changes: dict[str, object],
) -> None:
    values = inputs()
    completed = values[-1]
    forged = verification(completed, **cast(Any, changes))
    success = SuccessRouter(routed_incident(completed, IncidentState.CLOSED))
    failure = FailureRouter(routed_incident(completed, IncidentState.NEEDS_HUMAN))

    with pytest.raises(InvalidDomainValueError, match="does not bind"):
        await recover(
            RollbackRecoveryCoordinator(Executor(completed), Verifier(forged), success, failure),
            values,
        )
    assert success.calls == 0
    assert failure.calls == []


@pytest.mark.anyio
async def test_invalid_execution_scope_and_untyped_results_fail_closed() -> None:
    values = inputs()
    completed = values[-1]
    success = SuccessRouter(routed_incident(completed, IncidentState.CLOSED))
    failure = FailureRouter(routed_incident(completed, IncidentState.NEEDS_HUMAN))
    with pytest.raises(InvalidDomainValueError, match="executor returned"):
        await recover(
            RollbackRecoveryCoordinator(Executor("bad"), Verifier("bad"), success, failure),
            values,
        )
    with pytest.raises(InvalidDomainValueError, match="authority scope"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed),
                Verifier(verification(completed)),
                success,
                failure,
            ),
            (
                replace(values[0], idempotency_key=IdempotencyKey("substituted-key")),
                values[1],
                values[2],
                values[3],
                completed,
            ),
        )


def test_recovery_result_invariants_reject_inconsistent_outcomes() -> None:
    values = inputs()
    completed = values[-1]
    passed = verification(completed)
    with pytest.raises(InvalidDomainValueError):
        RollbackRecoveryResult(completed, RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED)
    with pytest.raises(InvalidDomainValueError):
        RollbackRecoveryResult(
            completed,
            RollbackRecoveryOutcome.REDIAGNOSE,
            passed,
            routed_incident(completed, IncidentState.CLOSED),
        )


@pytest.mark.parametrize(
    ("execution_result", "outcome", "verification_result", "incident_result"),
    [
        ("bad", RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED, None, None),
        (inputs()[-1], "bad", None, None),
        (
            replace(
                inputs()[-1],
                status=ActionExecutionStatus.STARTED,
                after_snapshot=None,
                completed_at=None,
                version=AggregateVersion.initial(),
            ),
            RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED,
            verification(inputs()[-1]),
            None,
        ),
        (
            replace(
                inputs()[-1],
                status=ActionExecutionStatus.STARTED,
                after_snapshot=None,
                completed_at=None,
                version=AggregateVersion.initial(),
            ),
            RollbackRecoveryOutcome.EXECUTION_NOT_SUCCEEDED,
            None,
            routed_incident(inputs()[-1], IncidentState.NEEDS_HUMAN),
        ),
        (
            replace(
                inputs()[-1],
                status=ActionExecutionStatus.STARTED,
                after_snapshot=None,
                completed_at=None,
                version=AggregateVersion.initial(),
            ),
            RollbackRecoveryOutcome.CLOSED,
            verification(inputs()[-1]),
            routed_incident(inputs()[-1], IncidentState.CLOSED),
        ),
        (inputs()[-1], RollbackRecoveryOutcome.CLOSED, None, None),
        (
            inputs()[-1],
            RollbackRecoveryOutcome.CLOSED,
            verification(inputs()[-1]),
            None,
        ),
    ],
)
def test_recovery_result_rejects_invalid_types_and_incomplete_states(
    execution_result: object,
    outcome: object,
    verification_result: HealthVerificationDecision | None,
    incident_result: Incident | None,
) -> None:
    with pytest.raises(InvalidDomainValueError):
        RollbackRecoveryResult(
            cast(ActionExecution, execution_result),
            cast(RollbackRecoveryOutcome, outcome),
            verification_result,
            incident_result,
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("request", "bad"),
        ("proposal", "bad"),
        ("policy_input", "bad"),
        ("policy_decision", "bad"),
        ("correlation_id", "bad"),
        ("causation_id", "bad"),
        ("used", "bad"),
        ("used", True),
        ("used", -1),
    ],
)
async def test_invalid_recovery_inputs_fail_before_execution(field: str, bad: object) -> None:
    values = inputs()
    completed = values[-1]
    executor = Executor(completed)
    arguments: dict[str, object] = {
        "request": values[0],
        "proposal": values[1],
        "policy_input": values[2],
        "policy_decision": values[3],
        "correlation_id": CORRELATION,
        "causation_id": CAUSATION,
        "used": 0,
    }
    arguments[field] = bad

    with pytest.raises(InvalidDomainValueError, match="inputs are invalid"):
        await RollbackRecoveryCoordinator(
            executor,
            Verifier(verification(completed)),
            SuccessRouter(routed_incident(completed, IncidentState.CLOSED)),
            FailureRouter(routed_incident(completed, IncidentState.NEEDS_HUMAN)),
        ).recover(
            cast(RollbackServiceRequest, arguments["request"]),
            cast(RemediationProposal, arguments["proposal"]),
            cast(PolicyEvaluationInput, arguments["policy_input"]),
            cast(PolicyDecision, arguments["policy_decision"]),
            used_rediagnosis_attempts=cast(int, arguments["used"]),
            principal=None,
            correlation_id=cast(CorrelationId, arguments["correlation_id"]),
            causation_id=cast(CausationId, arguments["causation_id"]),
        )
    assert executor.calls == 0


@pytest.mark.anyio
@pytest.mark.parametrize("position", range(10))
async def test_every_execution_authority_binding_is_enforced(position: int) -> None:
    values = inputs()
    rollback_request, proposed, evaluated_input, evaluated, completed = values
    digest = Sha256Digest("f" * 64)
    altered_request = rollback_request
    altered_proposal = proposed
    altered_input = evaluated_input
    altered_decision = evaluated
    altered_execution = completed
    if position == 0:
        altered_input = replace(evaluated_input, tenant_id=execution().tenant_id)
    elif position == 1:
        altered_request = replace(rollback_request, incident_id=execution().incident_id)
    elif position == 2:
        altered_request = replace(rollback_request, approval_id=ApprovalId("other-approval"))
    elif position == 3:
        altered_execution = replace(
            completed, idempotency_key=IdempotencyKey("other-idempotency-key")
        )
    elif position == 4:
        altered_proposal = proposed.model_copy(update={"incident_id": "other-incident"})
    elif position == 5:
        altered_input = replace(evaluated_input, incident_id=execution().incident_id)
    elif position == 6:
        altered_execution = replace(completed, proposal_fingerprint=digest)
    elif position == 7:
        altered_decision = replace(evaluated, input_fingerprint=digest)
    elif position == 8:
        altered_decision = replace(evaluated, proposal_fingerprint=digest)
    else:
        altered_execution = replace(completed, policy_decision_fingerprint=digest)

    with pytest.raises(InvalidDomainValueError, match="authority scope"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(altered_execution),
                Verifier(verification(completed)),
                SuccessRouter(routed_incident(completed, IncidentState.CLOSED)),
                FailureRouter(routed_incident(completed, IncidentState.NEEDS_HUMAN)),
            ),
            (
                altered_request,
                altered_proposal,
                altered_input,
                altered_decision,
                altered_execution,
            ),
        )


@pytest.mark.anyio
async def test_untyped_verification_and_router_results_fail_closed() -> None:
    values = inputs()
    completed = values[-1]
    closed = routed_incident(completed, IncidentState.CLOSED)
    with pytest.raises(InvalidDomainValueError, match="does not bind"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed), Verifier("bad"), SuccessRouter(closed), FailureRouter(closed)
            ),
            values,
        )
    with pytest.raises(InvalidDomainValueError, match="router returned invalid"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed),
                Verifier(verification(completed)),
                SuccessRouter("bad"),
                FailureRouter(closed),
            ),
            values,
        )
    with pytest.raises(InvalidDomainValueError, match="failure router returned invalid"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed),
                Verifier(verification(completed, passed=False)),
                SuccessRouter(closed),
                FailureRouter("bad"),
            ),
            values,
        )


@pytest.mark.anyio
async def test_router_cannot_change_scope_or_return_unsafe_failure_state() -> None:
    values = inputs()
    completed = values[-1]
    passed = verification(completed)
    closed = routed_incident(completed, IncidentState.CLOSED)
    substituted = replace(closed, id=execution().incident_id)
    with pytest.raises(InvalidDomainValueError, match="changed Incident scope"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed),
                Verifier(passed),
                SuccessRouter(substituted),
                FailureRouter(closed),
            ),
            values,
        )
    with pytest.raises(InvalidDomainValueError, match="unsafe Incident state"):
        await recover(
            RollbackRecoveryCoordinator(
                Executor(completed),
                Verifier(verification(completed, passed=False)),
                SuccessRouter(closed),
                FailureRouter(closed),
            ),
            values,
        )

"""Deterministic scenario-aware health-verification contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, cast

import pytest

from agentops_incident_commander.domain import (
    HEALTH_VERIFICATION_RULES_VERSION,
    HEALTH_VERIFICATION_SCHEMA_VERSION,
    MAX_HEALTH_VERIFICATION_SAMPLES,
    ActionExecution,
    ActionExecutionStatus,
    ActionSnapshot,
    ActorId,
    AggregateVersion,
    ApprovalId,
    ArtifactId,
    EvidenceId,
    HealthVerificationCriteria,
    HealthVerificationDecision,
    HealthVerificationObservation,
    HealthVerificationOutcome,
    HealthVerificationReasonCode,
    HealthVerificationSample,
    HealthVerificationScenario,
    IdempotencyKey,
    IncidentId,
    InvalidDomainValueError,
    OpaqueIdentifier,
    PolicyEnvironment,
    ResolvedRollbackTarget,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    evaluate_health_verification,
)

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=UTC)
TENANT = TenantId("tenant-verification")
INCIDENT = IncidentId("incident-verification")
EXECUTION_ID = OpaqueIdentifier("execution-verification")


def target() -> ResolvedRollbackTarget:
    return ResolvedRollbackTarget(
        tenant_id=TENANT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        expected_current_version=SemanticVersion("2.0.0"),
        stable_version=SemanticVersion("1.0.0"),
    )


def snapshot(*, after: bool) -> ActionSnapshot:
    return ActionSnapshot(
        artifact_id=ArtifactId("verification-after" if after else "verification-before"),
        tenant_id=TENANT,
        incident_id=INCIDENT,
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        deployed_version=SemanticVersion("1.0.0" if after else "2.0.0"),
        observed_at=NOW if after else NOW - timedelta(minutes=1),
        content_hash=Sha256Digest(("b" if after else "a") * 64),
    )


def execution(*, succeeded: bool = True) -> ActionExecution:
    started = ActionExecution(
        id=EXECUTION_ID,
        tenant_id=TENANT,
        incident_id=INCIDENT,
        approval_id=ApprovalId("approval-verification"),
        idempotency_key=IdempotencyKey("rollback-verification"),
        actor_id=ActorId("operator-verification"),
        proposal_fingerprint=Sha256Digest("c" * 64),
        policy_decision_fingerprint=Sha256Digest("d" * 64),
        target=target(),
        before_snapshot=snapshot(after=False),
        status=ActionExecutionStatus.STARTED,
        version=AggregateVersion.initial(),
        started_at=NOW - timedelta(seconds=30),
    )
    return started.succeed(after_snapshot=snapshot(after=True), at=NOW) if succeeded else started


def criteria(**overrides: Any) -> HealthVerificationCriteria:
    values: dict[str, Any] = {
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "action_execution_id": EXECUTION_ID,
        "scenario": HealthVerificationScenario.RELEASE_HTTP_500,
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "expected_stable_version": SemanticVersion("1.0.0"),
        "max_error_rate_basis_points": 100,
        "max_p95_latency_ms": 500,
        "maximum_new_alerts": 0,
        "stability_window_seconds": 60,
        "max_sample_gap_seconds": 30,
    }
    values.update(overrides)
    return HealthVerificationCriteria(**values)


def sample(offset: int, **overrides: Any) -> HealthVerificationSample:
    values: dict[str, Any] = {
        "observed_at": NOW + timedelta(seconds=offset),
        "error_rate_basis_points": 50,
        "p95_latency_ms": 400,
        "health_endpoint_healthy": True,
        "deployed_version": SemanticVersion("1.0.0"),
        "new_alert_count": 0,
    }
    values.update(overrides)
    return HealthVerificationSample(**values)


def observation(**overrides: Any) -> HealthVerificationObservation:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("observation-verification"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "action_execution_id": EXECUTION_ID,
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "expected_stable_version": SemanticVersion("1.0.0"),
        "window_started_at": NOW,
        "window_ended_at": NOW + timedelta(seconds=60),
        "samples": (sample(0), sample(30), sample(60)),
        "error_rate_evidence_id": EvidenceId("evidence-error-rate"),
        "p95_latency_evidence_id": EvidenceId("evidence-p95-latency"),
        "health_endpoint_evidence_id": EvidenceId("evidence-health-endpoint"),
        "deployed_version_evidence_id": EvidenceId("evidence-deployed-version"),
        "new_alerts_evidence_id": EvidenceId("evidence-new-alerts"),
        "collected_at": NOW + timedelta(seconds=61),
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return HealthVerificationObservation(**values)


def decision(**overrides: Any) -> HealthVerificationDecision:
    values: dict[str, Any] = {
        "id": OpaqueIdentifier("decision-verification"),
        "tenant_id": TENANT,
        "incident_id": INCIDENT,
        "action_execution_id": EXECUTION_ID,
        "scenario": HealthVerificationScenario.RELEASE_HTTP_500,
        "outcome": HealthVerificationOutcome.PASS,
        "reasons": (),
        "criteria_fingerprint": criteria().fingerprint,
        "observation_fingerprint": observation().fingerprint,
        "execution_fingerprint": execution().fingerprint,
        "input_fingerprint": Sha256Digest("e" * 64),
        "evaluated_at": NOW + timedelta(seconds=62),
    }
    values.update(overrides)
    return HealthVerificationDecision(**values)


def evaluate(
    *,
    action: ActionExecution | None = None,
    rules: HealthVerificationCriteria | None = None,
    observed: HealthVerificationObservation | None = None,
    evaluated_at: datetime = NOW + timedelta(seconds=62),
) -> HealthVerificationDecision:
    return evaluate_health_verification(
        execution() if action is None else action,
        criteria() if rules is None else rules,
        observation() if observed is None else observed,
        decision_id=OpaqueIdentifier("decision-verification"),
        evaluated_at=evaluated_at,
    )


def test_healthy_complete_window_passes_with_stable_versioned_fingerprints() -> None:
    result = evaluate()
    assert result.outcome is HealthVerificationOutcome.PASS
    assert result.reasons == ()
    assert result.rules_version == HEALTH_VERIFICATION_RULES_VERSION
    assert result.schema_version == HEALTH_VERIFICATION_SCHEMA_VERSION
    assert result.criteria_fingerprint == criteria().fingerprint
    assert result.observation_fingerprint == observation().fingerprint
    assert result.execution_fingerprint == execution().fingerprint
    assert result.input_fingerprint == evaluate().input_fingerprint
    assert result.fingerprint == evaluate().fingerprint
    assert replace(result, evaluated_at=result.evaluated_at + timedelta(seconds=1)).fingerprint != (
        result.fingerprint
    )
    assert replace(criteria(), max_p95_latency_ms=501).fingerprint != criteria().fingerprint
    assert replace(observation(), expires_at=NOW + timedelta(minutes=6)).fingerprint != (
        observation().fingerprint
    )


def test_all_failures_are_reported_once_in_fixed_order() -> None:
    flapping = (
        sample(0),
        sample(
            30,
            error_rate_basis_points=101,
            p95_latency_ms=501,
            health_endpoint_healthy=False,
            deployed_version=SemanticVersion("2.0.0"),
            new_alert_count=1,
        ),
        sample(60),
    )
    result = evaluate(
        rules=criteria(stability_window_seconds=120, max_sample_gap_seconds=10),
        observed=observation(samples=flapping),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    assert result.outcome is HealthVerificationOutcome.FAIL
    assert result.reasons == tuple(HealthVerificationReasonCode)


def test_intermediate_flapping_fails_even_when_window_endpoints_are_healthy() -> None:
    observed = observation(
        samples=(sample(0), sample(30, health_endpoint_healthy=False), sample(60))
    )
    result = evaluate(observed=observed)
    assert result.reasons == (HealthVerificationReasonCode.HEALTH_ENDPOINT_UNHEALTHY,)


def test_scenario_specific_minimum_stability_window_is_enforced() -> None:
    assert (
        criteria(
            scenario=HealthVerificationScenario.DEPLOYMENT_MEMORY_LEAK,
            stability_window_seconds=300,
        ).stability_window_seconds
        == 300
    )
    for scenario, seconds in (
        (HealthVerificationScenario.RELEASE_HTTP_500, 59),
        (HealthVerificationScenario.DEPLOYMENT_MEMORY_LEAK, 299),
    ):
        with pytest.raises(InvalidDomainValueError, match="stability window"):
            criteria(scenario=scenario, stability_window_seconds=seconds)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": "tenant"}, "types"),
        ({"service": "Orders"}, "service"),
        ({"max_error_rate_basis_points": True}, "error-rate"),
        ({"max_error_rate_basis_points": 10_001}, "error-rate"),
        ({"max_p95_latency_ms": 0}, "P95"),
        ({"maximum_new_alerts": 1}, "cannot permit"),
        ({"max_sample_gap_seconds": 0}, "sample gap"),
        ({"max_sample_gap_seconds": 61}, "cannot exceed"),
        ({"rules_version": SemanticVersion("2.0.0")}, "rules version"),
        ({"schema_version": "2.0.0"}, "criteria schema"),
    ],
)
def test_criteria_reject_invalid_or_unbounded_values(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        criteria(**overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"error_rate_basis_points": -1}, "error rate"),
        ({"p95_latency_ms": 300_001}, "P95"),
        ({"health_endpoint_healthy": 1}, "endpoint"),
        ({"deployed_version": "1.0.0"}, "version"),
        ({"new_alert_count": True}, "new-alert"),
    ],
)
def test_sample_rejects_invalid_values(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        sample(0, **overrides)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "observation"}, "types"),
        ({"service": "orders/unsafe"}, "service"),
        ({"window_ended_at": NOW}, "times"),
        ({"collected_at": NOW + timedelta(seconds=59)}, "times"),
        ({"expires_at": NOW + timedelta(seconds=61)}, "times"),
        ({"samples": [sample(0), sample(60)]}, "samples"),
        ({"samples": (sample(0),)}, "samples"),
        (
            {"samples": tuple(sample(0) for _ in range(MAX_HEALTH_VERIFICATION_SAMPLES + 1))},
            "samples",
        ),
        ({"samples": (sample(0), cast(HealthVerificationSample, "invalid"))}, "samples"),
        ({"samples": (sample(1), sample(60))}, "coverage"),
        ({"samples": (sample(0), sample(30), sample(30), sample(60))}, "coverage"),
        ({"p95_latency_evidence_id": EvidenceId("evidence-error-rate")}, "must be unique"),
        ({"schema_version": "2.0.0"}, "observation schema"),
    ],
)
def test_observation_rejects_invalid_scope_time_samples_or_evidence(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        observation(**overrides)


@pytest.mark.parametrize(
    "value",
    ["execution", "criteria", "observation", "decision_id"],
)
def test_evaluator_rejects_untyped_inputs(value: str) -> None:
    inputs: dict[str, Any] = {
        "execution": execution(),
        "criteria": criteria(),
        "observation": observation(),
        "decision_id": OpaqueIdentifier("decision"),
    }
    inputs[value] = "invalid"
    with pytest.raises(InvalidDomainValueError, match="inputs are invalid"):
        evaluate_health_verification(**inputs, evaluated_at=NOW + timedelta(seconds=62))


def test_evaluator_rejects_non_successful_or_substituted_action_scope() -> None:
    with pytest.raises(InvalidDomainValueError, match="successful action"):
        evaluate(action=execution(succeeded=False))
    for rules, observed in (
        (criteria(tenant_id=TenantId("tenant-other")), observation()),
        (criteria(), observation(incident_id=IncidentId("incident-other"))),
        (criteria(action_execution_id=OpaqueIdentifier("execution-other")), observation()),
        (criteria(service="payments"), observation()),
        (criteria(environment=PolicyEnvironment.STAGING), observation()),
        (criteria(expected_stable_version=SemanticVersion("0.9.0")), observation()),
    ):
        with pytest.raises(InvalidDomainValueError, match="scope does not match"):
            evaluate(rules=rules, observed=observed)


def test_evaluator_rejects_time_before_collection_and_normalizes_aware_time() -> None:
    with pytest.raises(InvalidDomainValueError, match="cannot predate"):
        evaluate(evaluated_at=NOW + timedelta(seconds=60))
    offset = timezone(timedelta(hours=8))
    result = evaluate(evaluated_at=(NOW + timedelta(seconds=62)).astimezone(offset))
    assert result.evaluated_at == NOW + timedelta(seconds=62)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": "decision"}, "types"),
        (
            {
                "outcome": HealthVerificationOutcome.FAIL,
                "reasons": (),
            },
            "reasons",
        ),
        (
            {
                "outcome": HealthVerificationOutcome.PASS,
                "reasons": (HealthVerificationReasonCode.OBSERVATION_STALE,),
            },
            "reasons",
        ),
        (
            {
                "outcome": HealthVerificationOutcome.FAIL,
                "reasons": (
                    HealthVerificationReasonCode.OBSERVATION_STALE,
                    HealthVerificationReasonCode.OBSERVATION_STALE,
                ),
            },
            "reasons",
        ),
        (
            {"rules_version": SemanticVersion("2.0.0")},
            "decision rules",
        ),
        ({"schema_version": "2.0.0"}, "decision schema"),
    ],
)
def test_decision_rejects_invalid_types_outcome_reasons_or_versions(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        decision(**overrides)

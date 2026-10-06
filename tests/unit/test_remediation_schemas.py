"""Remediation Agent outputs are typed, bounded, and non-authoritative."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agentops_incident_commander.workflows import (
    MAX_REDIAGNOSIS_ATTEMPTS,
    MAX_REMEDIATION_RISK_ASSUMPTIONS,
    MAX_STABILITY_WINDOW_SECONDS,
    MIN_STABILITY_WINDOW_SECONDS,
    REMEDIATION_PROPOSAL_SCHEMA_VERSION,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
)


def proposal(**overrides: Any) -> RemediationProposal:
    values: dict[str, object] = {
        "schema_version": REMEDIATION_PROPOSAL_SCHEMA_VERSION,
        "proposal_id": "remediation-1",
        "proposal_version": 1,
        "incident_id": "incident-1",
        "candidate_id": "candidate-deployment",
        "evidence_gate_input_fingerprint": "b" * 64,
        "evidence_gate_decision_fingerprint": "a" * 64,
        "action": RecoveryAction.ROLLBACK_SERVICE,
        "parameters": RollbackServiceParameters(
            service="orders",
            introducing_deployment_evidence_id="evidence-deployment",
        ),
        "prerequisites": RollbackPrerequisites(
            current_version_evidence_id="evidence-current-version"
        ),
        "verification_conditions": RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            stability_window_seconds=300,
        ),
        "failure_handling": RemediationFailureHandling(
            route=RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF,
            max_rediagnosis_attempts=2,
        ),
        "compensation_eligible": False,
        "risk_assumptions": (
            "The observed faulty deployment is the active version.",
            "A stable predecessor can be resolved by the server.",
        ),
    }
    values.update(overrides)
    return RemediationProposal.model_validate(values)


def test_remediation_proposal_is_versioned_frozen_hash_bound_and_content_safe() -> None:
    value = proposal()
    assert value.action is RecoveryAction.ROLLBACK_SERVICE
    assert not value.compensation_eligible
    assert value.failure_handling.redeploy_faulty_version is False
    assert value.prerequisites.require_human_approval
    assert value.verification_conditions.require_server_resolved_stable_version
    assert len(value.fingerprint.value) == 64
    assert not hasattr(value.parameters, "target_version")
    assert not hasattr(value, "approval_id")
    assert not hasattr(value, "idempotency_key")
    assert RemediationProposal.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError, match="frozen"):
        value.proposal_version = 2


def test_any_material_proposal_change_changes_the_canonical_fingerprint() -> None:
    original = proposal()
    changed_values = (
        proposal(proposal_version=2),
        proposal(
            parameters=RollbackServiceParameters(
                service="inventory",
                introducing_deployment_evidence_id="evidence-deployment",
            )
        ),
        proposal(
            verification_conditions=RollbackVerificationConditions(
                max_error_rate_basis_points=50,
                max_p95_latency_ms=500,
                stability_window_seconds=300,
            )
        ),
        proposal(risk_assumptions=("The active deployment introduced the failure.",)),
    )
    assert len({original.fingerprint, *(item.fingerprint for item in changed_values)}) == 5


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema_version": "2.0.0"}, "literal_error"),
        ({"proposal_version": True}, "valid integer"),
        ({"proposal_version": 0}, "greater than or equal"),
        ({"action": "shell"}, "literal_error"),
        ({"compensation_eligible": True}, "literal_error"),
        ({"risk_assumptions": []}, "tuple"),
        ({"risk_assumptions": ()}, "at least 1"),
        ({"risk_assumptions": ("unsafe\nassumption",)}, "single-line"),
        ({"risk_assumptions": ("duplicate", "duplicate")}, "must be unique"),
        (
            {
                "risk_assumptions": tuple(
                    f"risk-{index}" for index in range(MAX_REMEDIATION_RISK_ASSUMPTIONS + 1)
                )
            },
            "at most",
        ),
        ({"shell_command": "kubectl rollout undo"}, "Extra inputs"),
        ({"target_version": "release-stable"}, "Extra inputs"),
        ({"approval_id": "approval-forged"}, "Extra inputs"),
    ],
)
def test_proposal_rejects_wrong_versions_coercion_authority_and_unbounded_inputs(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        proposal(**overrides)


@pytest.mark.parametrize(
    "extra",
    (
        {"target_version": "v1"},
        {"command": "rollback orders"},
        {"url": "https://control.invalid"},
        {"path": "/deployments/orders"},
    ),
)
def test_rollback_parameters_reject_model_supplied_targets_and_execution_fields(
    extra: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        RollbackServiceParameters.model_validate(
            {
                "service": "orders",
                "introducing_deployment_evidence_id": "evidence-deployment",
                **extra,
            }
        )


def test_prerequisites_are_non_bypassable_and_evidence_references_are_distinct() -> None:
    for field in (
        "require_server_resolved_stable_predecessor",
        "require_policy_authorization",
        "require_human_approval",
        "require_execution_lock",
    ):
        with pytest.raises(ValidationError, match="literal_error"):
            RollbackPrerequisites.model_validate(
                {"current_version_evidence_id": "evidence-current", field: False}
            )
    with pytest.raises(ValidationError, match="must differ"):
        proposal(
            prerequisites=RollbackPrerequisites(current_version_evidence_id="evidence-deployment")
        )


def test_verification_conditions_are_complete_strict_and_bounded() -> None:
    lower = RollbackVerificationConditions(
        max_error_rate_basis_points=0,
        max_p95_latency_ms=1,
        stability_window_seconds=MIN_STABILITY_WINDOW_SECONDS,
    )
    upper = RollbackVerificationConditions(
        max_error_rate_basis_points=10_000,
        max_p95_latency_ms=300_000,
        stability_window_seconds=MAX_STABILITY_WINDOW_SECONDS,
    )
    assert lower.maximum_new_alerts == upper.maximum_new_alerts == 0
    for overrides in (
        {"max_error_rate_basis_points": -1},
        {"max_p95_latency_ms": 0},
        {"stability_window_seconds": MIN_STABILITY_WINDOW_SECONDS - 1},
        {"stability_window_seconds": MAX_STABILITY_WINDOW_SECONDS + 1},
        {"require_healthy_endpoint": False},
        {"require_server_resolved_stable_version": False},
        {"maximum_new_alerts": 1},
    ):
        with pytest.raises(ValidationError):
            RollbackVerificationConditions.model_validate(
                {
                    "max_error_rate_basis_points": 100,
                    "max_p95_latency_ms": 500,
                    "stability_window_seconds": 300,
                    **overrides,
                }
            )


def test_failure_route_requires_matching_bounded_rediagnosis_budget() -> None:
    assert (
        RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
        ).max_rediagnosis_attempts
        == 0
    )
    assert (
        RemediationFailureHandling(
            route=RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF,
            max_rediagnosis_attempts=MAX_REDIAGNOSIS_ATTEMPTS,
        ).max_rediagnosis_attempts
        == MAX_REDIAGNOSIS_ATTEMPTS
    )
    for route, attempts in (
        (RemediationFailureRoute.HUMAN_HANDOFF, 1),
        (RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF, 0),
    ):
        with pytest.raises(ValidationError, match="route must match"):
            RemediationFailureHandling(route=route, max_rediagnosis_attempts=attempts)
    with pytest.raises(ValidationError):
        RemediationFailureHandling(
            route=RemediationFailureRoute.BOUNDED_REDIAGNOSIS_THEN_HUMAN_HANDOFF,
            max_rediagnosis_attempts=MAX_REDIAGNOSIS_ATTEMPTS + 1,
        )

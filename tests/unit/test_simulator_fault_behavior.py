"""Tests for validated simulator-side fault activation."""

from __future__ import annotations

import pytest

from agentops_incident_commander.simulator.fault_behavior import FaultBehavior


def test_fault_behavior_is_absent_by_default() -> None:
    """A baseline service has no hidden fault behavior."""
    assert FaultBehavior.from_environment("order", {}) is None


def test_http_500_behavior_requires_order_and_safe_run_id() -> None:
    """The implemented scenario activates only on its allowlisted target."""
    behavior = FaultBehavior.from_environment(
        "order",
        {
            "SIMULATOR_FAULT_SCENARIO": "http-500",
            "SIMULATOR_FAULT_RUN_ID": "run-abcdef123456",
        },
    )

    assert behavior == FaultBehavior("http-500", "run-abcdef123456")
    assert behavior.forces_internal_error is True
    assert behavior.exhausts_database_pool is False


def test_database_pool_behavior_is_a_distinct_typed_effect() -> None:
    """Pool saturation cannot accidentally enable the deployment failure branch."""
    behavior = FaultBehavior.from_environment(
        "order",
        {
            "SIMULATOR_FAULT_SCENARIO": "db-pool-exhaustion",
            "SIMULATOR_FAULT_RUN_ID": "run-abcdef123456",
        },
    )

    assert behavior == FaultBehavior("db-pool-exhaustion", "run-abcdef123456")
    assert behavior.forces_internal_error is False
    assert behavior.exhausts_database_pool is True


@pytest.mark.parametrize(
    ("service", "environment", "message"),
    [
        ("order", {"SIMULATOR_FAULT_SCENARIO": "http-500"}, "configured together"),
        ("order", {"SIMULATOR_FAULT_RUN_ID": "run-abcdef123456"}, "configured together"),
        (
            "order",
            {"SIMULATOR_FAULT_SCENARIO": "http-500", "SIMULATOR_FAULT_RUN_ID": "BAD"},
            "invalid fault run ID",
        ),
        (
            "order",
            {
                "SIMULATOR_FAULT_SCENARIO": "unknown",
                "SIMULATOR_FAULT_RUN_ID": "run-abcdef123456",
            },
            "unsupported",
        ),
        (
            "payment",
            {
                "SIMULATOR_FAULT_SCENARIO": "http-500",
                "SIMULATOR_FAULT_RUN_ID": "run-abcdef123456",
            },
            "only target Order",
        ),
        (
            "inventory",
            {
                "SIMULATOR_FAULT_SCENARIO": "db-pool-exhaustion",
                "SIMULATOR_FAULT_RUN_ID": "run-abcdef123456",
            },
            "only target Order",
        ),
    ],
)
def test_fault_behavior_rejects_partial_or_misdirected_configuration(
    service: str,
    environment: dict[str, str],
    message: str,
) -> None:
    """Partial, injected, unknown, and wrong-service activation fails closed."""
    with pytest.raises(ValueError, match=message):
        FaultBehavior.from_environment(service, environment)  # type: ignore[arg-type]

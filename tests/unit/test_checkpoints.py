"""Strict checkpoint identity, correlation config, and serializer tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.infrastructure import (
    DIAGNOSIS_CHECKPOINT_NAMESPACE,
    DiagnosisCheckpointIdentity,
    diagnosis_checkpoint_config,
    diagnosis_checkpoint_serializer,
    postgres_diagnosis_checkpointer,
)
from agentops_incident_commander.workflows import (
    DiagnosisGraphState,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    GraphStateMigrationRegistry,
)


def state(**overrides: Any) -> DiagnosisGraphState:
    values: dict[str, object] = {
        "state_schema_version": "1.3.0",
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
        "causation_id": "cause-1",
        "phase": GraphPhase.PLANNING,
        "budgets": GraphBudgetState(
            max_steps=1,
            used_steps=0,
            max_replans=0,
            used_replans=0,
            max_tool_calls=1,
            used_tool_calls=0,
            max_model_calls=1,
            used_model_calls=0,
            max_tokens=10,
            used_tokens=0,
            max_cost_nanounits=10,
            used_cost_nanounits=0,
        ),
        "prompt": GraphPromptReference(
            prompt_id="diagnosis", version="1.0.0", content_fingerprint="a" * 64
        ),
        "checkpoint_sequence": 0,
        "updated_at": datetime(2026, 10, 5, tzinfo=UTC),
    }
    values.update(overrides)
    return DiagnosisGraphState.model_validate(values)


def test_checkpoint_config_is_stable_correlated_and_content_free() -> None:
    graph_state = state()
    identity = DiagnosisCheckpointIdentity.from_state(graph_state)
    config = diagnosis_checkpoint_config(graph_state)

    assert config["configurable"] == {
        "thread_id": identity.thread_id,
        "checkpoint_ns": DIAGNOSIS_CHECKPOINT_NAMESPACE,
    }
    assert config["metadata"] == {
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "run-1",
        "correlation_id": "correlation-1",
    }
    assert identity.thread_id == DiagnosisCheckpointIdentity.from_state(graph_state).thread_id
    assert "tenant-1" not in identity.thread_id
    identity.require_matches(graph_state)


def test_thread_identity_isolated_and_full_correlation_must_match() -> None:
    base = DiagnosisCheckpointIdentity.from_state(state())
    assert (
        base.thread_id
        != DiagnosisCheckpointIdentity.from_state(state(tenant_id="tenant-2")).thread_id
    )
    assert (
        base.thread_id
        != DiagnosisCheckpointIdentity.from_state(state(workflow_run_id="run-2")).thread_id
    )
    with pytest.raises(InvalidDomainValueError, match="does not match"):
        base.require_matches(state(correlation_id="correlation-2"))


@pytest.mark.parametrize("value", ["", "bad value", 1])
def test_checkpoint_identity_rejects_invalid_correlation_values(value: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="identifiers are invalid"):
        DiagnosisCheckpointIdentity(value, "incident-1", "run-1", "correlation-1")
    with pytest.raises(InvalidDomainValueError, match="requires Diagnosis"):
        DiagnosisCheckpointIdentity.from_state(value)


def test_strict_serializer_round_trips_only_typed_graph_state() -> None:
    serializer = diagnosis_checkpoint_serializer()
    encoded = serializer.dumps_typed(state().model_dump(mode="json"))
    decoded = serializer.loads_typed(encoded)
    assert isinstance(decoded, dict)
    assert GraphStateMigrationRegistry().load(decoded) == state()
    assert serializer.pickle_fallback is False


@pytest.mark.anyio
async def test_postgres_checkpointer_rejects_non_postgres_urls_before_connecting() -> None:
    with pytest.raises(InvalidDomainValueError, match="must use PostgreSQL"):
        async with postgres_diagnosis_checkpointer("sqlite:///unsafe.db"):
            pytest.fail("invalid URL must not yield")

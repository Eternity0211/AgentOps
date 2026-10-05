"""Strict versioned graph-state and checkpoint migration contracts."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from pydantic import ValidationError

from agentops_incident_commander.domain import InvalidDomainValueError
from agentops_incident_commander.workflows import (
    DIAGNOSIS_GRAPH_STATE_SCHEMA_VERSION,
    DiagnosisGraphState,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    GraphStateMigrationRegistry,
    canonical_graph_state_bytes,
)

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def budget(**overrides: Any) -> GraphBudgetState:
    values: dict[str, object] = {
        "max_steps": 8,
        "used_steps": 1,
        "max_replans": 2,
        "used_replans": 0,
        "max_tool_calls": 16,
        "used_tool_calls": 1,
        "max_model_calls": 4,
        "used_model_calls": 1,
        "max_tokens": 10_000,
        "used_tokens": 500,
        "max_cost_nanounits": 1_000_000,
        "used_cost_nanounits": 25_000,
    }
    values.update(overrides)
    return GraphBudgetState.model_validate(values)


def state_dict(**overrides: Any) -> dict[str, object]:
    values: dict[str, object] = {
        "state_schema_version": DIAGNOSIS_GRAPH_STATE_SCHEMA_VERSION,
        "graph_version": "1.0.0",
        "tenant_id": "tenant-1",
        "incident_id": "incident-1",
        "workflow_run_id": "workflow-1",
        "correlation_id": "correlation-1",
        "causation_id": "job-1",
        "phase": GraphPhase.INVESTIGATING,
        "budgets": budget().model_dump(mode="json"),
        "prompt": {
            "prompt_id": "diagnosis-root-cause",
            "version": "1.0.0",
            "content_fingerprint": "a" * 64,
        },
        "tool_call_ids": ("tool-1",),
        "tool_query_fingerprints": ("b" * 64,),
        "model_call_ids": ("model-1",),
        "evidence_ids": ("evidence-1",),
        "gate_decision_fingerprint": None,
        "error_code": None,
        "checkpoint_sequence": 2,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


def test_current_state_is_strict_frozen_and_canonical() -> None:
    state = DiagnosisGraphState.model_validate(state_dict())
    assert state.prompt == GraphPromptReference(
        prompt_id="diagnosis-root-cause",
        version="1.0.0",
        content_fingerprint="a" * 64,
    )
    encoded = canonical_graph_state_bytes(state)
    assert DiagnosisGraphState.model_validate_json(encoded) == state
    assert json.loads(encoded)["state_schema_version"] == "1.1.0"
    with pytest.raises(ValidationError, match="frozen"):
        state.phase = GraphPhase.COMPLETE


@pytest.mark.parametrize(
    "field",
    ["prompt_content", "raw_telemetry", "model_response", "artifact_content"],
)
def test_state_rejects_content_bearing_or_unknown_fields(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        DiagnosisGraphState.model_validate(state_dict(**{field: "seeded-secret"}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "bad tenant"),
        ("graph_version", "v1"),
        ("gate_decision_fingerprint", "not-a-hash"),
        ("updated_at", datetime(2026, 10, 5, 10, 0)),
        ("tool_call_ids", ("duplicate", "duplicate")),
        ("tool_query_fingerprints", ("b" * 64, "b" * 64)),
    ],
)
def test_state_rejects_invalid_identity_time_hash_and_duplicate_references(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        DiagnosisGraphState.model_validate(state_dict(**{field: value}))


@pytest.mark.parametrize(
    ("field", "used_field"),
    [
        ("max_steps", "used_steps"),
        ("max_replans", "used_replans"),
        ("max_tool_calls", "used_tool_calls"),
        ("max_model_calls", "used_model_calls"),
        ("max_tokens", "used_tokens"),
        ("max_cost_nanounits", "used_cost_nanounits"),
    ],
)
def test_budget_rejects_consumption_above_each_limit(field: str, used_field: str) -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        budget(**{field: 1, used_field: 2})


def test_registry_migrates_copy_sequentially_and_validates_final_state() -> None:
    current = DiagnosisGraphState.model_validate(state_dict())
    current_snapshot = json.loads(canonical_graph_state_bytes(current))
    legacy = {**current_snapshot, "state_schema_version": "0.9.0"}
    legacy["legacy_phase"] = legacy.pop("phase")
    legacy.pop("tool_query_fingerprints")
    original = copy.deepcopy(legacy)
    registry = GraphStateMigrationRegistry()

    def migrate(value: dict[str, Any]) -> dict[str, Any]:
        value["phase"] = value.pop("legacy_phase")
        value["state_schema_version"] = "1.0.0"
        return value

    registry.register("0.9.0", "1.0.0", migrate)
    loaded = registry.load(legacy)
    assert loaded.phase is GraphPhase.INVESTIGATING
    assert loaded.tool_query_fingerprints == ()
    assert legacy == original
    assert registry.load(current_snapshot) == current


def test_registry_rejects_unknown_future_missing_and_invalid_migrations() -> None:
    registry = GraphStateMigrationRegistry()
    with pytest.raises(InvalidDomainValueError, match="missing"):
        registry.load({})
    with pytest.raises(InvalidDomainValueError, match="future"):
        registry.load({"state_schema_version": "2.0.0"})
    with pytest.raises(InvalidDomainValueError, match="incomplete"):
        registry.load({"state_schema_version": "0.9.0"})
    with pytest.raises(InvalidDomainValueError, match="advance"):
        registry.register("1.0.0", "1.0.0", lambda value: value)
    registry.register("0.9.0", "1.0.0", lambda value: value)
    with pytest.raises(InvalidDomainValueError, match="already"):
        registry.register("0.9.0", "1.0.0", lambda value: value)
    with pytest.raises(InvalidDomainValueError, match="invalid target"):
        registry.load({"state_schema_version": "0.9.0"})


def test_builtin_query_history_migration_rejects_future_field_in_legacy_snapshot() -> None:
    legacy = state_dict(state_schema_version="1.0.0", tool_query_fingerprints=("b" * 64,))
    with pytest.raises(InvalidDomainValueError, match="future query-history"):
        GraphStateMigrationRegistry().load(legacy)


def test_registry_rejects_non_mapping_migration_result_and_excessive_chain() -> None:
    registry = GraphStateMigrationRegistry()

    def invalid_result(value: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], [])

    registry.register("0.9.0", "1.0.0", invalid_result)
    with pytest.raises(InvalidDomainValueError, match="invalid target"):
        registry.load({"state_schema_version": "0.9.0"})

    limited = GraphStateMigrationRegistry(current_version="0.0.33")

    def migration_to(target: str) -> Any:
        def migrate(value: dict[str, Any]) -> dict[str, Any]:
            return {**value, "state_schema_version": target}

        return migrate

    for patch in range(33):
        source = f"0.0.{patch}"
        target = f"0.0.{patch + 1}"
        limited.register(
            source,
            target,
            migration_to(target),
        )
    with pytest.raises(InvalidDomainValueError, match="limit"):
        limited.load({"state_schema_version": "0.0.0"})

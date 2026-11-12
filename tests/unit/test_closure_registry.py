from __future__ import annotations

import json
from pathlib import Path

import pytest
from evaluation.closure_registry import ClosureRegistry, WorkStatus, load_closure_registry
from pydantic import ValidationError

REGISTRY = Path("evaluation/closure/v1/registry.json")


def test_closure_registry_is_complete_strict_and_ordered() -> None:
    registry = load_closure_registry(REGISTRY)

    assert [item.work_id for item in registry.experiments] == [f"FC{i}" for i in range(14)]
    assert [item.status for item in registry.experiments[:2]] == [
        WorkStatus.COMPLETE,
        WorkStatus.COMPLETE,
    ]
    assert registry.experiments[2].status is WorkStatus.IN_PROGRESS
    assert len(registry.legacy_mappings) == 16
    assert {item.resolution for item in registry.legacy_mappings} >= {
        "EXISTING_EVIDENCE",
        "FC13",
    }


def test_external_blocks_and_sample_size_decisions_are_explicit() -> None:
    registry = load_closure_registry(REGISTRY)
    blocked = [
        item
        for item in registry.experiments
        if item.status is WorkStatus.BLOCKED_EXTERNAL_DATA
    ]

    assert {item.work_id for item in blocked} == {"FC5", "FC6", "FC7", "FC8"}
    assert all(item.external_requirements for item in blocked)
    assert all(item.sample_size.method for item in registry.experiments)


def test_closure_registry_refuses_unknown_fields_and_forward_dependencies() -> None:
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    value["unknown"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ClosureRegistry.model_validate_json(json.dumps(value))

    value.pop("unknown")
    value["experiments"][1]["prerequisites"] = ["FC13"]
    with pytest.raises(ValidationError, match="prerequisites must reference earlier"):
        ClosureRegistry.model_validate_json(json.dumps(value))


def test_legacy_todo_has_no_unmapped_open_checkbox() -> None:
    todo = Path("TODO.md").read_text(encoding="utf-8")
    open_items = [line for line in todo.splitlines() if line.startswith("- [ ]")]
    registry = load_closure_registry(REGISTRY)
    expected = [
        item.work_id for item in registry.experiments if item.status is not WorkStatus.COMPLETE
    ]

    assert len(open_items) == len(expected)
    assert all(f"{work_id} " in line for work_id, line in zip(expected, open_items, strict=True))

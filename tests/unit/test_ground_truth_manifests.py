"""Contract tests for evaluation-only scenario Ground Truth manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
MANIFEST_ROOT = ROOT / "evaluation" / "ground_truth" / "v1"
SCENARIOS = {
    "http-500": ("order", True),
    "db-pool-exhaustion": ("order", False),
    "redis-timeout": ("inventory", False),
    "downstream-latency": ("payment", False),
    "memory-leak": ("order", True),
    "bad-configuration": ("payment", False),
}
REQUIRED = {
    "schema_version",
    "dataset_version",
    "scenario_id",
    "target_service",
    "cause",
    "symptoms",
    "key_evidence",
    "deployment_change",
    "automation_eligible",
    "eligibility_prerequisites",
    "expected_safe_outcome",
    "handoff_reason_code",
    "recovery_action",
    "verification",
    "evaluator_cleanup",
    "future_tool_requirement",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def keys_recursively(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in keys_recursively(child)}
    if isinstance(value, list):
        return {key for child in value for key in keys_recursively(child)}
    return set()


def test_schema_is_strict_versioned_and_covers_every_required_field() -> None:
    schema = load(MANIFEST_ROOT / "schema.json")
    assert schema["$schema"].endswith("2020-12/schema")
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == REQUIRED
    assert set(schema["properties"]) == REQUIRED
    assert schema["properties"]["scenario_id"]["enum"] == list(SCENARIOS)
    assert schema["properties"]["evaluator_cleanup"]["additionalProperties"] is False


def test_six_manifests_are_complete_unique_and_match_recovery_policy() -> None:
    paths = sorted(MANIFEST_ROOT.glob("*.json"))
    manifests = [load(path) for path in paths if path.name != "schema.json"]
    assert len(manifests) == 6
    assert {item["scenario_id"] for item in manifests} == set(SCENARIOS)
    for item in manifests:
        scenario = item["scenario_id"]
        target, eligible = SCENARIOS[scenario]
        assert set(item) == REQUIRED
        assert item["schema_version"] == "1.0"
        assert item["dataset_version"] == "phase1c-v1"
        assert item["target_service"] == target
        assert item["automation_eligible"] is eligible
        assert set(item["key_evidence"]) == {"metrics", "logs", "traces", "deployments"}
        assert item["symptoms"] and item["verification"]
        assert item["evaluator_cleanup"] == {
            "action": "fault_clean",
            "readiness_check": "simulator_status",
            "recovery_credit": False,
        }
        assert "command" not in keys_recursively(item)
        if eligible:
            assert item["deployment_change"] == {
                "introduced_version": "2.0.0",
                "stable_predecessor": "1.0.0",
            }
            assert item["recovery_action"] == "rollback_service"
            assert item["expected_safe_outcome"] == "approved_rollback_or_handoff"
            assert item["eligibility_prerequisites"]
        else:
            assert item["deployment_change"] is None
            assert item["recovery_action"] is None
            assert item["expected_safe_outcome"] == "human_handoff"
            assert item["handoff_reason_code"]
            assert item["future_tool_requirement"]

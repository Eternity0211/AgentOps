"""The development pair must bind code and inputs before any provider effect."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from evaluation.run_fallback_development_pair import BOUND_SOURCES, check_plan, run_pair

DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")
FROZEN_PLAN = Path("evaluation/final_diagnosis_optimization/v2/pair-plan.json")


def plan() -> dict[str, Any]:
    return {
        "schema_version": "diagnosis-fallback-development-pair/1.0.0",
        "implementation_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "profiles": {
            "baseline-1.11": "real-structured-evaluation/1.11.0",
            "candidate-1.12": "real-structured-evaluation/1.12.0",
        },
        "modes": ["controlled-graph"],
        "model_provider_call_ceiling": 6,
        "graph_model_call_ceiling": 4,
        "tool_call_ceiling": 12,
        "evidence_strategy": "gc-aware-causal-scope/1.0.0",
        "expected_cases": 27,
        "selective_reruns_allowed": False,
        "runtime_label_isolation": True,
        "dataset_index_sha256": hashlib.sha256((DATASET / "index.json").read_bytes()).hexdigest(),
        "source_hashes": {
            path: hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in BOUND_SOURCES
        },
    }


def test_development_plan_binds_exact_profiles_sources_and_budget() -> None:
    valid = plan()
    check_plan(valid, valid["implementation_commit"], DATASET)
    variants: tuple[tuple[str, Any], ...] = (
        ("profiles", {"candidate-1.12": "real-structured-evaluation/1.12.0"}),
        ("model_provider_call_ceiling", 7),
        ("graph_model_call_ceiling", 5),
        ("tool_call_ceiling", 13),
        ("runtime_label_isolation", False),
        ("selective_reruns_allowed", True),
        ("dataset_index_sha256", "0" * 64),
        ("source_hashes", {}),
    )
    for field, value in variants:
        changed = valid | {field: value}
        with pytest.raises(ValueError):
            check_plan(changed, valid["implementation_commit"], DATASET)


def test_development_runner_fails_before_effect_on_source_drift(tmp_path: Path) -> None:
    frozen = plan()
    frozen["source_hashes"]["evaluation/structured_model.py"] = "0" * 64
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(frozen), encoding="utf-8")
    output = tmp_path / "outcomes"
    with pytest.raises(ValueError, match="source drift"):
        run_pair(DATASET, path, output, key="test-only")
    assert not output.exists()


def test_development_runner_requires_key_before_creating_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        run_pair(DATASET, tmp_path / "missing.json", tmp_path / "outcomes", key="")
    assert not (tmp_path / "outcomes").exists()


def test_frozen_development_protocol_preflights_without_label_values() -> None:
    frozen = json.loads(FROZEN_PLAN.read_text(encoding="utf-8"))
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    check_plan(frozen, head, DATASET)
    assert frozen["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert frozen["expected_outcomes"] == 54
    assert frozen["evaluator_labels"] == (
        "evaluation/evidence_strategy_development/v1/evaluator_only/labels.json"
    )
    assert (
        hashlib.sha256(Path(frozen["evaluator_labels"]).read_bytes()).hexdigest()
        == (frozen["evaluator_labels_sha256"])
    )
    assert "final-diagnosis-comparison" not in FROZEN_PLAN.read_text(encoding="utf-8")
    for path, digest in frozen["postrun_scorer_hashes"].items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest

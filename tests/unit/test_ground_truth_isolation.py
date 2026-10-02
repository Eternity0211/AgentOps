"""Isolation and fail-closed tests for evaluation-only Ground Truth."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]
CANARY_PATH = ROOT / "evaluation" / "ground_truth" / "canary" / "label.txt"
MANIFEST_ROOT = ROOT / "evaluation" / "ground_truth" / "v1"


def load_verifier() -> ModuleType:
    """Load the evaluator entry point without making evaluation a runtime package."""
    path = ROOT / "evaluation" / "verify_ground_truth.py"
    spec = importlib.util.spec_from_file_location("ground_truth_verifier", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluator_accepts_only_complete_isolated_inputs(tmp_path: Path) -> None:
    verifier = load_verifier()
    credential = tmp_path / "credential"
    credential.write_text("synthetic-evaluation-credential\n", encoding="utf-8")

    assert verifier.verify_inputs(MANIFEST_ROOT, CANARY_PATH, credential) == 6


@pytest.mark.parametrize("invalid_value", [b"", b"x" * 4097])
def test_evaluator_rejects_invalid_credential_size(tmp_path: Path, invalid_value: bytes) -> None:
    verifier = load_verifier()
    credential = tmp_path / "credential"
    credential.write_bytes(invalid_value)

    with pytest.raises(verifier.GroundTruthValidationError, match="evaluation input"):
        verifier.verify_inputs(MANIFEST_ROOT, CANARY_PATH, credential)


def test_evaluator_rejects_missing_canary_without_disclosing_values(tmp_path: Path) -> None:
    verifier = load_verifier()
    credential = tmp_path / "credential"
    credential.write_text("synthetic-evaluation-credential\n", encoding="utf-8")

    with pytest.raises(verifier.GroundTruthValidationError, match=r"label\.txt") as captured:
        verifier.verify_inputs(MANIFEST_ROOT, tmp_path / "label.txt", credential)
    assert "synthetic-evaluation-credential" not in str(captured.value)


def test_evaluator_rejects_malformed_or_incomplete_manifest_set(tmp_path: Path) -> None:
    verifier = load_verifier()
    credential = tmp_path / "credential"
    credential.write_text("synthetic-evaluation-credential\n", encoding="utf-8")
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"additionalProperties": False}), encoding="utf-8")
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    with pytest.raises(verifier.GroundTruthValidationError, match="invalid evaluation JSON"):
        verifier.verify_inputs(tmp_path, CANARY_PATH, credential)

    (tmp_path / "broken.json").write_text(json.dumps({"scenario_id": "http-500"}), encoding="utf-8")
    with pytest.raises(verifier.GroundTruthValidationError, match="scenario set"):
        verifier.verify_inputs(tmp_path, CANARY_PATH, credential)


def test_evaluation_compose_has_a_single_closed_network_service() -> None:
    compose = (ROOT / "compose.evaluation.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile.evaluator").read_text(encoding="utf-8")

    assert compose.count("  ground-truth-evaluator:\n") == 1
    assert "profiles: [evaluation]" in compose
    assert "internal: true" in compose
    assert "networks: [ground-truth]" in compose
    assert "ground_truth_access" in compose
    assert compose.count("read_only: true") == 3
    assert "ports:" not in compose
    assert "cap_drop: [ALL]" in compose
    assert "COPY evaluation/verify_ground_truth.py" in dockerfile
    assert "COPY src" not in dockerfile


def test_runtime_and_model_capable_paths_cannot_contain_ground_truth_canary() -> None:
    canary = CANARY_PATH.read_text(encoding="utf-8").strip()
    canary_hash = hashlib.sha256(canary.encode()).hexdigest()
    runtime_paths = [
        ROOT / "compose.yaml",
        ROOT / "Dockerfile.simulator",
        *(ROOT / "src").rglob("*"),
        *(ROOT / "config").rglob("*"),
    ]

    for path in runtime_paths:
        if not path.is_file():
            continue
        content = path.read_bytes()
        assert canary.encode() not in content, path
        assert canary_hash.encode() not in content, path

    runtime_compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "GROUND_TRUTH_ACCESS_FILE" not in runtime_compose
    assert "/evaluation/ground-truth" not in runtime_compose
    assert "ground-truth" not in runtime_compose

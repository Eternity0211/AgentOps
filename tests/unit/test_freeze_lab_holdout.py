from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from evaluation.freeze_lab_holdout import PLAN, SOURCE, freeze_lab_holdout
from evaluation.observation_snapshot import load_snapshot


def test_freeze_lab_holdout_is_complete_separate_and_reproducible(tmp_path: Path) -> None:
    first_dataset = tmp_path / "first" / "dataset"
    first_evaluator = tmp_path / "first" / "evaluator"
    second_dataset = tmp_path / "second" / "dataset"
    second_evaluator = tmp_path / "second" / "evaluator"

    freeze_lab_holdout(PLAN, first_dataset, first_evaluator)
    freeze_lab_holdout(PLAN, second_dataset, second_evaluator)

    first_index = json.loads((first_dataset / "index.json").read_text(encoding="utf-8"))
    labels = json.loads((first_evaluator / "labels.json").read_text(encoding="utf-8"))
    assert len(first_index) == len(labels) == 160
    assert Counter(label["stratum"] for label in labels) == Counter(
        {
            "http-500": 20,
            "db-pool-exhaustion": 20,
            "redis-timeout": 20,
            "downstream-latency": 20,
            "memory-leak": 20,
            "bad-configuration": 20,
            "normal": 10,
            "insufficient-evidence": 10,
            "counter-evidence": 10,
            "prompt-injection": 10,
        }
    )
    assert {row["instance_id"] for row in first_index} == {label["instance_id"] for label in labels}
    assert {path.name for path in first_dataset.iterdir()} == {
        ".gitattributes",
        "index.json",
        "inputs",
    }
    assert not any("label" in path.name for path in first_dataset.rglob("*"))
    assert (first_dataset / "index.json").read_bytes() == (
        second_dataset / "index.json"
    ).read_bytes()
    for first in first_dataset.rglob("*.json"):
        relative = first.relative_to(first_dataset)
        assert first.read_bytes() == (second_dataset / relative).read_bytes()


def test_fault_variants_cover_declared_axes_without_runtime_labels(tmp_path: Path) -> None:
    dataset, evaluator = tmp_path / "dataset", tmp_path / "evaluator"
    freeze_lab_holdout(PLAN, dataset, evaluator)
    index = json.loads((dataset / "index.json").read_text(encoding="utf-8"))
    labels = json.loads((evaluator / "labels.json").read_text(encoding="utf-8"))
    by_id = {label["instance_id"]: label for label in labels}

    fault_labels = [label for label in labels if label["expected_root_cause"] is not None]
    assert {label["dependency_scope"] for label in fault_labels} == {"direct", "cross-service"}
    assert {label["deployment_timing"] for label in fault_labels} == {
        "recent-correlated",
        "old-uncorrelated",
        "no-change",
    }
    assert {label["signal_strength"] for label in fault_labels} == {
        "bounded-low",
        "bounded-medium",
        "bounded-high",
    }
    for row in index:
        snapshot = load_snapshot(
            dataset / "inputs" / f"{row['instance_id']}.json",
            expected_hash=row["input_hash"],
        )
        encoded = json.dumps(snapshot, sort_keys=True)
        label = by_id[row["instance_id"]]
        assert label["origin"] == SOURCE
        assert "expected_root_cause" not in encoded
        assert "expected_safe_control" not in encoded
        assert row["instance_id"] not in encoded.replace(row["instance_id"], "", 1)


def test_freeze_refuses_existing_or_nested_outputs(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="new separate"):
        freeze_lab_holdout(PLAN, existing, tmp_path / "evaluator")
    with pytest.raises(ValueError, match="new separate"):
        freeze_lab_holdout(PLAN, tmp_path / "dataset", tmp_path / "dataset" / "labels")


def test_published_lab_holdout_is_hash_bound_and_does_not_reuse_prior_inputs() -> None:
    dataset = Path("evaluation/datasets/lab-holdout-v1")
    evaluator = Path("evaluation/lab_holdout/v1/evaluator_only")
    manifest = json.loads((evaluator / "freeze-manifest.json").read_text(encoding="utf-8"))
    index = json.loads((dataset / "index.json").read_text(encoding="utf-8"))
    labels = json.loads((evaluator / "labels.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "lab-holdout-freeze/1.0.0"
    assert manifest["case_count"] == len(index) == len(labels) == 160
    assert manifest["plan_sha256"] == hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert (
        manifest["generator_sha256"]
        == hashlib.sha256(Path("evaluation/freeze_lab_holdout.py").read_bytes()).hexdigest()
    )
    for relative, expected_hash in manifest["files"].items():
        prefix, child = relative.split("/", 1)
        root = dataset if prefix == "dataset" else evaluator
        assert hashlib.sha256((root / child).read_bytes()).hexdigest() == expected_hash

    current_ids = {row["instance_id"] for row in index}
    current_hashes = {row["input_hash"] for row in index}
    prior_ids: set[str] = set()
    prior_hashes: set[str] = set()
    for prior_index in Path("evaluation/datasets").glob("*/index.json"):
        if prior_index.parent == dataset:
            continue
        rows = json.loads(prior_index.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                if isinstance(row.get("instance_id"), str):
                    prior_ids.add(row["instance_id"])
                if isinstance(row.get("input_hash"), str):
                    prior_hashes.add(row["input_hash"])
    assert current_ids.isdisjoint(prior_ids)
    assert current_hashes.isdisjoint(prior_hashes)

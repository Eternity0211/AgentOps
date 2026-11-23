from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluation.freeze_lab_holdout_v2 import PLAN, freeze_lab_holdout
from evaluation.observation_snapshot import load_snapshot


def test_confirmation_cohort_reproducible_disjoint_and_label_isolated(tmp_path: Path) -> None:
    first_data, first_labels = tmp_path / "first/data", tmp_path / "first/labels"
    second_data, second_labels = tmp_path / "second/data", tmp_path / "second/labels"
    freeze_lab_holdout(PLAN, first_data, first_labels)
    freeze_lab_holdout(PLAN, second_data, second_labels)

    first_index = json.loads((first_data / "index.json").read_text(encoding="utf-8"))
    second_index = json.loads((second_data / "index.json").read_text(encoding="utf-8"))
    labels = json.loads((first_labels / "labels.json").read_text(encoding="utf-8"))
    assert first_index == second_index
    assert len(first_index) == len(labels) == 160
    assert Counter(row["stratum"] for row in labels) == {
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
    assert {row["instance_id"] for row in first_index} == {
        row["instance_id"] for row in labels
    }
    assert not any("label" in path.name for path in first_data.rglob("*"))
    for row in first_index:
        snapshot = load_snapshot(
            first_data / "inputs" / f"{row['instance_id']}.json",
            expected_hash=row["input_hash"],
        )
        assert "expected_root_cause" not in json.dumps(snapshot)
        assert "expected_safe_control" not in json.dumps(snapshot)
    for path in first_data.rglob("*.json"):
        assert path.read_bytes() == (second_data / path.relative_to(first_data)).read_bytes()


def test_published_confirmation_cohort_has_frozen_bytes_and_no_reuse() -> None:
    dataset = Path("evaluation/datasets/lab-holdout-v2")
    evaluator = Path("evaluation/lab_holdout/v2/evaluator_only")
    manifest = json.loads((evaluator / "freeze-manifest.json").read_text(encoding="utf-8"))
    index = json.loads((dataset / "index.json").read_text(encoding="utf-8"))
    plan = json.loads(PLAN.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "lab-holdout-freeze/2.0.0"
    assert manifest["case_count"] == len(index) == 160
    assert manifest["plan_sha256"] == hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert manifest["generator_sha256"] == hashlib.sha256(
        Path("evaluation/freeze_lab_holdout_v2.py").read_bytes()
    ).hexdigest()
    for relative, expected in manifest["files"].items():
        prefix, child = relative.split("/", 1)
        root = dataset if prefix == "dataset" else evaluator
        assert hashlib.sha256((root / child).read_bytes()).hexdigest() == expected

    current_ids = {row["instance_id"] for row in index}
    current_hashes = {row["input_hash"] for row in index}
    for prior_path in map(Path, plan["disjoint_from_indexes"]):
        prior = json.loads(prior_path.read_text(encoding="utf-8"))
        assert current_ids.isdisjoint(row["instance_id"] for row in prior)
        assert current_hashes.isdisjoint(row["input_hash"] for row in prior)

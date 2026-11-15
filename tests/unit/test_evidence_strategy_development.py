from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.autonomous_diagnosis import (
    build_candidate_diagnosis_context,
    required_downstream_causal_scope,
)
from evaluation.freeze_evidence_strategy_development import GENERATOR, freeze
from evaluation.observation_snapshot import load_snapshot

PLAN = Path("evaluation/evidence_strategy_development/v1/plan.json")
DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")
EVALUATOR = Path("evaluation/evidence_strategy_development/v1/evaluator_only")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_development_freeze_is_label_isolated_disjoint_and_reproducible(tmp_path: Path) -> None:
    index = json.loads((DATASET / "index.json").read_text(encoding="utf-8"))
    labels = json.loads((EVALUATOR / "labels.json").read_text(encoding="utf-8"))
    manifest = json.loads((EVALUATOR / "freeze-manifest.json").read_text(encoding="utf-8"))
    assert len(index) == len(labels) == manifest["case_count"] == 27
    assert {row["instance_id"] for row in index} == {row["instance_id"] for row in labels}
    assert {row["stratum"] for row in labels} == {
        "http-500",
        "db-pool-exhaustion",
        "redis-timeout",
        "downstream-latency",
        "memory-leak",
        "bad-configuration",
        "normal",
        "insufficient-evidence",
        "counter-evidence",
    }
    prior_indexes = [
        Path("evaluation/datasets/real-v1/index.json"),
        Path("evaluation/datasets/real-v2/index.json"),
        Path("evaluation/datasets/lab-holdout-v1/index.json"),
    ]
    prior_rows = [
        row for path in prior_indexes for row in json.loads(path.read_text(encoding="utf-8"))
    ]
    assert {row["instance_id"] for row in index}.isdisjoint(
        row["instance_id"] for row in prior_rows
    )
    assert {row["input_hash"] for row in index}.isdisjoint(row["input_hash"] for row in prior_rows)
    for row in index:
        snapshot = load_snapshot(
            DATASET / "inputs" / f"{row['instance_id']}.json",
            expected_hash=row["input_hash"],
        )
        assert not ({"stratum", "label", "expected_root_cause"} & set(snapshot))
    assert manifest["generator_sha256"] == _hash(GENERATOR)

    regenerated_dataset = tmp_path / "dataset"
    regenerated_evaluator = tmp_path / "evaluator"
    freeze(PLAN, regenerated_dataset, regenerated_evaluator)
    assert (regenerated_dataset / "index.json").read_bytes() == (
        DATASET / "index.json"
    ).read_bytes()
    assert (regenerated_evaluator / "labels.json").read_bytes() == (
        EVALUATOR / "labels.json"
    ).read_bytes()


def test_development_cases_exercise_both_candidate_changes() -> None:
    labels = json.loads((EVALUATOR / "labels.json").read_text(encoding="utf-8"))
    by_stratum = {row["stratum"]: row["instance_id"] for row in labels}

    memory = json.loads(
        (DATASET / "inputs" / f"{by_stratum['memory-leak']}.json").read_text(encoding="utf-8")
    )
    memory_output = memory["reads"]["query_traces:order"]["output"]
    context = build_candidate_diagnosis_context(
        [{"id": "memory-trace", "source": "traces", "summary": memory_output["summary"]}], {}
    )
    assert context["memory_retention_by_service"][0]["classification"] == "SUSTAINED_RETENTION"

    configuration = json.loads(
        (DATASET / "inputs" / f"{by_stratum['bad-configuration']}.json").read_text(encoding="utf-8")
    )
    observations = [
        {
            "id": "topology",
            "source": "topology",
            "summary": configuration["reads"]["get_service_topology:gateway"]["output"]["summary"],
        },
        {
            "id": "trace",
            "source": "traces",
            "summary": configuration["reads"]["query_traces:gateway"]["output"]["summary"],
        },
    ]
    assert (
        required_downstream_causal_scope(
            observations,
            {("get_service_topology", "gateway"), ("query_traces", "gateway")},
        )
        == "inventory"
    )


def test_development_freeze_refuses_overwrite(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="new separate outputs"):
        freeze(PLAN, DATASET, tmp_path / "new-evaluator")

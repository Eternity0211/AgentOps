from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
from evaluation.run_transport_pair import FROZEN_V1_PROFILES, _check_plan, run_pair
from evaluation.structured_model import StructuredTransportProfile


def source_hashes() -> dict[str, str]:
    names = (
        "evaluation/run_transport_pair.py",
        "evaluation/structured_model.py",
    )
    return {name: hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in names}


def test_transport_pair_plan_binds_profiles_and_source_hashes(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "index.json").write_text("[]", encoding="utf-8")
    bank = tmp_path / "bank.json"
    bank.write_text("{}", encoding="utf-8")
    plan: dict[str, Any] = {
        "schema_version": "structured-transport-pair/1.0.0",
        "implementation_commit": "a" * 40,
        "dataset_index_sha256": hashlib.sha256(b"[]").hexdigest(),
        "simulated_history_bank_sha256": hashlib.sha256(b"{}").hexdigest(),
        "profiles": {name: profile.value for name, profile in FROZEN_V1_PROFILES},
        "source_hashes": source_hashes(),
    }
    with patch(
        "evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)
    ):
        _check_plan(plan, "b" * 40, dataset, bank)

    plan["profiles"]["candidate-1.5"] = "changed"
    with (
        patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)),
        pytest.raises(ValueError, match="profile binding mismatch"),
    ):
        _check_plan(plan, "b" * 40, dataset, bank)


def test_transport_pair_refuses_nonancestor_before_provider_work(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "index.json").write_text("[]", encoding="utf-8")
    bank = tmp_path / "bank.json"
    bank.write_text("{}", encoding="utf-8")
    plan: dict[str, Any] = {
        "schema_version": "structured-transport-pair/1.0.0",
        "implementation_commit": "a" * 40,
        "dataset_index_sha256": hashlib.sha256(b"[]").hexdigest(),
        "simulated_history_bank_sha256": hashlib.sha256(b"{}").hexdigest(),
        "profiles": {name: profile.value for name, profile in FROZEN_V1_PROFILES},
        "source_hashes": source_hashes(),
    }
    with (
        patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=1)),
        pytest.raises(ValueError, match="not an ancestor"),
    ):
        _check_plan(plan, "b" * 40, dataset, bank)


def test_profile_order_alternates_deterministically() -> None:
    forward = [name for name, _ in FROZEN_V1_PROFILES]
    reverse = [name for name, _ in reversed(FROZEN_V1_PROFILES)]

    assert forward == ["baseline-1.4", "candidate-1.5"]
    assert reverse == ["candidate-1.5", "baseline-1.4"]
    assert json.dumps(forward) != json.dumps(reverse)


def test_pair_runner_interleaves_profiles_without_loading_labels(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    (dataset / "inputs").mkdir(parents=True)
    (dataset / "index.json").write_text("[]", encoding="utf-8")
    bank = tmp_path / "bank.json"
    bank.write_text("{}", encoding="utf-8")
    plan: dict[str, Any] = {
        "schema_version": "structured-transport-pair/1.0.0",
        "implementation_commit": "a" * 40,
        "dataset_index_sha256": hashlib.sha256(b"[]").hexdigest(),
        "simulated_history_bank_sha256": hashlib.sha256(b"{}").hexdigest(),
        "profiles": {name: profile.value for name, profile in FROZEN_V1_PROFILES},
        "source_hashes": source_hashes(),
        "modes": ["single-agent", "controlled-graph", "controlled-graph-simulated-memory"],
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    calls: list[str] = []

    def record(*args: object, **kwargs: object) -> None:
        profile = kwargs["profile"]
        assert isinstance(profile, StructuredTransportProfile)
        calls.append(profile.name)

    with (
        patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)),
        patch(
            "evaluation.run_transport_pair.subprocess.check_output", return_value="b" * 40
        ),
        patch(
            "evaluation.run_transport_pair.preflight",
            return_value=({"instance_id": "instance-0000000000000001", "input_hash": "c" * 64},),
        ),
        patch(
            "evaluation.run_transport_pair.load_snapshot",
            return_value={"instance_id": "instance-0000000000000001"},
        ),
        patch("evaluation.run_transport_pair._history", return_value=None),
        patch("evaluation.run_transport_pair.run_snapshot", side_effect=record),
    ):
        run_pair(dataset, plan_path, tmp_path / "output", bank, key="test-only")

    assert calls == [
        "BASELINE_1_4",
        "CANDIDATE_1_5",
        "CANDIDATE_1_5",
        "BASELINE_1_4",
        "BASELINE_1_4",
        "CANDIDATE_1_5",
    ]


def test_committed_pair_plan_is_frozen_and_label_isolated() -> None:
    path = Path("evaluation/real_protocol/v4/structured-transport-pair.json")
    plan = json.loads(path.read_text(encoding="utf-8"))

    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        name: profile.value for name, profile in FROZEN_V1_PROFILES
    }
    assert plan["runtime_label_isolation"].startswith("The pair runner does not")
    assert "evaluator_labels" not in Path("evaluation/run_transport_pair.py").read_text(
        encoding="utf-8"
    )
    immutable_data = {
        plan["dataset"] + "/index.json": plan["dataset_index_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        plan["base_scoring_plan"]: plan["base_scoring_plan_sha256"],
        plan["simulated_history_bank"]: plan["simulated_history_bank_sha256"],
        plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
    }
    assert all(
        hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
        for name, digest in immutable_data.items()
    )
    assert all(
        hashlib.sha256(
            subprocess.check_output(
                [
                    "git",
                    "-c",
                    "safe.directory=D:/AgentOps",
                    "show",
                    f"{plan['implementation_commit']}:{name}",
                ]
            )
        ).hexdigest()
        == digest
        for name, digest in plan["source_hashes"].items()
    )


def test_candidate_1_6_pair_plan_is_frozen_before_calls() -> None:
    path = Path("evaluation/real_protocol/v5/structured-transport-pair.json")
    plan = json.loads(path.read_text(encoding="utf-8"))

    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "133e56e367288687e349482c6bac7ff080dc90f3"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        "baseline-1.5": StructuredTransportProfile.CANDIDATE_1_5.value,
        "candidate-1.6": StructuredTransportProfile.CANDIDATE_1_6.value,
    }
    bindings = {
        plan["dataset"] + "/index.json": plan["dataset_index_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        plan["base_scoring_plan"]: plan["base_scoring_plan_sha256"],
        plan["simulated_history_bank"]: plan["simulated_history_bank_sha256"],
        plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
        plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
            "orchestrator_source_sha256"
        ],
        **plan["source_hashes"],
    }
    assert all(
        hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
        for name, digest in bindings.items()
    )

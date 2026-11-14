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


def source_hashes(*, bind_workflow: bool = False) -> dict[str, str]:
    names = [
        "evaluation/run_transport_pair.py",
        "evaluation/structured_model.py",
    ]
    if bind_workflow:
        names.append("evaluation/autonomous_diagnosis.py")
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
    with patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)):
        _check_plan(plan, "b" * 40, dataset, bank)

    plan["source_hashes"] = source_hashes(bind_workflow=True)
    with patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)):
        _check_plan(plan, "b" * 40, dataset, bank)

    del plan["source_hashes"]["evaluation/structured_model.py"]
    with (
        patch("evaluation.run_transport_pair.subprocess.run", return_value=Mock(returncode=0)),
        pytest.raises(ValueError, match="source hash mismatch"),
    ):
        _check_plan(plan, "b" * 40, dataset, bank)

    plan["source_hashes"] = source_hashes()

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
        patch("evaluation.run_transport_pair.subprocess.check_output", return_value="b" * 40),
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
    assert plan["profiles"] == {name: profile.value for name, profile in FROZEN_V1_PROFILES}
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
    immutable_data = {
        plan["dataset"] + "/index.json": plan["dataset_index_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        plan["base_scoring_plan"]: plan["base_scoring_plan_sha256"],
        plan["simulated_history_bank"]: plan["simulated_history_bank_sha256"],
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
        for name, digest in {
            **plan["source_hashes"],
            plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
            plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
                "orchestrator_source_sha256"
            ],
        }.items()
    )


def test_candidate_1_7_pair_plan_is_frozen_before_calls() -> None:
    path = Path("evaluation/real_protocol/v6/structured-transport-pair.json")
    plan = json.loads(path.read_text(encoding="utf-8"))

    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "26dc67faf0876c7e7a031380f91d9219a177f93d"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        "baseline-1.6": StructuredTransportProfile.CANDIDATE_1_6.value,
        "candidate-1.7": StructuredTransportProfile.CANDIDATE_1_7.value,
    }
    assert plan["acceptance"]["candidate_failed_outcomes_after_successful_repair"] == 0
    immutable_data = {
        plan["dataset"] + "/index.json": plan["dataset_index_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        plan["base_scoring_plan"]: plan["base_scoring_plan_sha256"],
        plan["simulated_history_bank"]: plan["simulated_history_bank_sha256"],
    }
    assert all(
        hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
        for name, digest in immutable_data.items()
    )
    assert set(plan["source_hashes"]) == {
        "evaluation/run_transport_pair.py",
        "evaluation/structured_model.py",
        "evaluation/autonomous_diagnosis.py",
    }
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
        for name, digest in {
            **plan["source_hashes"],
            plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
            plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
                "orchestrator_source_sha256"
            ],
        }.items()
    )


def test_candidate_1_8_pair_plan_is_frozen_before_calls() -> None:
    plan = json.loads(
        Path("evaluation/real_protocol/v7/structured-transport-pair.json").read_text("utf-8")
    )
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "2e33680ec5470eb0e46adac913b2f6ab2fba4684"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        "baseline-1.7": StructuredTransportProfile.CANDIDATE_1_7.value,
        "candidate-1.8": StructuredTransportProfile.CANDIDATE_1_8.value,
    }
    assert plan["acceptance"]["native_followthrough_scorer"] is True
    bindings = {
        **plan["source_hashes"],
        plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
        plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
            "orchestrator_source_sha256"
        ],
        plan["paired_scorer"]["followthrough_auditor_source"]: plan["paired_scorer"][
            "followthrough_auditor_source_sha256"
        ],
    }
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
        for name, digest in bindings.items()
    )
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(ValueError, match="transport source hash mismatch"):
        _check_plan(
            plan,
            revision,
            Path(plan["dataset"]),
            Path(plan["simulated_history_bank"]),
        )


def test_candidate_1_9_pair_plan_is_frozen_before_calls() -> None:
    plan = json.loads(
        Path("evaluation/real_protocol/v8/structured-transport-pair.json").read_text("utf-8")
    )
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "5c0abcda5a5b9734907a1a344e90faae8c53eb09"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        "baseline-1.8": StructuredTransportProfile.CANDIDATE_1_8.value,
        "candidate-1.9": StructuredTransportProfile.CANDIDATE_1_9.value,
    }
    assert plan["acceptance"]["candidate_valid_outcomes"] == 81
    bindings = {
        **plan["source_hashes"],
        plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
        plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
            "orchestrator_source_sha256"
        ],
        plan["paired_scorer"]["followthrough_auditor_source"]: plan["paired_scorer"][
            "followthrough_auditor_source_sha256"
        ],
    }
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
        for name, digest in bindings.items()
    )
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(ValueError, match="transport source hash mismatch"):
        _check_plan(
            plan,
            revision,
            Path(plan["dataset"]),
            Path(plan["simulated_history_bank"]),
        )


def test_candidate_1_10_pair_plan_is_frozen_before_calls() -> None:
    plan = json.loads(
        Path("evaluation/real_protocol/v9/structured-transport-pair.json").read_text("utf-8")
    )
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "00688d73102b6c27a20a3ac82978c273ebab48f2"
    assert plan["expected_outcomes"] == 162
    assert plan["profiles"] == {
        "baseline-1.8": StructuredTransportProfile.CANDIDATE_1_8.value,
        "candidate-1.10": StructuredTransportProfile.CANDIDATE_1_10.value,
    }
    assert plan["acceptance"]["candidate_valid_outcomes"] == 81
    assert plan["acceptance"]["candidate_safe_controls"] == 27
    bindings = {
        **plan["source_hashes"],
        plan["paired_scorer"]["source"]: plan["paired_scorer"]["source_sha256"],
        plan["paired_scorer"]["orchestrator_source"]: plan["paired_scorer"][
            "orchestrator_source_sha256"
        ],
        plan["paired_scorer"]["followthrough_auditor_source"]: plan["paired_scorer"][
            "followthrough_auditor_source_sha256"
        ],
    }
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
        for name, digest in bindings.items()
    )
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    with pytest.raises(ValueError, match="transport source hash mismatch"):
        _check_plan(
            plan,
            revision,
            Path(plan["dataset"]),
            Path(plan["simulated_history_bank"]),
        )

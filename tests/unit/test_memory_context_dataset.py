from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.autonomous_diagnosis import build_candidate_diagnosis_context
from evaluation.memory_evidence import GcPhase, MemoryPattern, MemorySample, assess_memory_series
from evaluation.run_memory_context_pair import _windowed_observations

ROOT = Path("evaluation/memory_context/v1")
V2_PLAN = Path("evaluation/memory_context/v2/plan.json")
V3_ROOT = Path("evaluation/memory_context/v3")


def test_memory_context_inputs_are_opaque_and_labels_are_isolated() -> None:
    inputs = json.loads((ROOT / "inputs.json").read_text("utf-8"))
    labels = json.loads((ROOT / "evaluator_only/labels.json").read_text("utf-8"))
    cases = inputs["cases"]

    assert len(cases) == len({case["case_id"] for case in cases}) == 5
    assert set(labels["labels"]) == {case["case_id"] for case in cases}
    assert not any(label in json.dumps(cases) for label in labels["labels"].values())


def test_memory_context_labels_match_deterministic_contract() -> None:
    inputs = json.loads((ROOT / "inputs.json").read_text("utf-8"))
    labels = json.loads((ROOT / "evaluator_only/labels.json").read_text("utf-8"))["labels"]
    for case in inputs["cases"]:
        samples = tuple(
            MemorySample(
                row[0] * 1_000_000_000,
                row[1],
                row[2],
                row[3],
                inputs["retention_limit_bytes"],
                (f"evidence-{case['case_id']}-{index}",),
                row[4],
                None if row[5] is None else GcPhase(row[5]),
            )
            for index, row in enumerate(case["samples"])
        )
        expected = MemoryPattern(labels[case["case_id"]])
        assert assess_memory_series(samples).pattern is expected


def test_memory_context_plan_is_frozen_before_provider_calls() -> None:
    plan = json.loads((ROOT / "plan.json").read_text("utf-8"))
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "91d467d0ea530a6fc0b0ae2a1c16abc01d20fbf5"
    assert plan["expected_outcomes"] == 10
    bindings = {
        plan["inputs"]: plan["inputs_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        **plan["source_hashes"],
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


def test_memory_context_v2_plan_requires_full_paired_rerun() -> None:
    plan = json.loads(V2_PLAN.read_text("utf-8"))
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "886a37f106749c38874cafb631c1e889c29ba4fa"
    assert plan["expected_outcomes"] == 10
    assert plan["claim_profile"] == "v2"
    assert "Do not reuse or rescore any v1 provider output" in plan["rerun_policy"]
    bindings = {
        plan["inputs"]: plan["inputs_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        **plan["source_hashes"],
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


def test_expanded_memory_inputs_are_opaque_label_isolated_and_contract_aligned() -> None:
    inputs = json.loads((V3_ROOT / "inputs.json").read_text("utf-8"))
    labels = json.loads(
        (V3_ROOT / "evaluator_only/labels.json").read_text("utf-8")
    )["labels"]
    cases = inputs["cases"]
    assert len(cases) == len(labels) == 10
    assert set(labels) == {case["case_id"] for case in cases}
    assert not any(label in json.dumps(cases) for label in labels.values())
    classifications: dict[str, list[str]] = {}
    service_classifications: dict[str, list[str]] = {}
    for case in cases:
        observations, start, end = _windowed_observations(
            case, inputs["retention_limit_bytes"]
        )
        context = build_candidate_diagnosis_context(
            observations, {}, window_start=start, window_end=end
        )
        classifications[case["case_id"]] = [
            fact["classification"] for fact in context["memory_retention_by_service"]
        ]
        service_classifications[case["case_id"]] = [
            fact["classification"] for fact in context["alert_aligned_service_facts"]
        ]
    expected_positive = {
        case_id for case_id, label in labels.items() if label == "SUSTAINED_RETENTION"
    }
    actual_positive = {
        case_id
        for case_id, values in classifications.items()
        if "SUSTAINED_RETENTION" in values
    }
    assert actual_positive == expected_positive
    assert classifications["expanded-case-07"] == []
    assert service_classifications["expanded-case-08"] == ["CONTRADICTORY"]


def test_expanded_memory_plan_is_frozen_before_twenty_provider_outcomes() -> None:
    plan = json.loads((V3_ROOT / "plan.json").read_text("utf-8"))
    assert plan["status"] == "FROZEN_BEFORE_PROVIDER_CALLS"
    assert plan["implementation_commit"] == "275159581c4226ec519c515ae4373ff8cd05a984"
    assert plan["expected_outcomes"] == 20
    assert plan["claim_profile"] == "v2"
    assert "Do not reuse or rescore any v1 or v2 provider output" in plan["rerun_policy"]
    bindings = {
        plan["inputs"]: plan["inputs_sha256"],
        plan["evaluator_labels"]: plan["evaluator_labels_sha256"],
        **plan["source_hashes"],
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

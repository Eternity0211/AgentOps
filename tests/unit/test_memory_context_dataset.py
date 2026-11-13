from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from evaluation.memory_evidence import GcPhase, MemoryPattern, MemorySample, assess_memory_series

ROOT = Path("evaluation/memory_context/v1")
V2_PLAN = Path("evaluation/memory_context/v2/plan.json")


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

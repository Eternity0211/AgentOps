from __future__ import annotations

import json
from pathlib import Path

from evaluation.memory_evidence import GcPhase, MemoryPattern, MemorySample, assess_memory_series

ROOT = Path("evaluation/memory_context/v1")


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

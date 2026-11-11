from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path("evaluation/results/diagnosis-generalization/v1")


def test_published_generalization_score_matches_raw_outcomes() -> None:
    results = json.loads((ROOT / "run-002/results.json").read_text(encoding="utf-8"))
    score = json.loads((ROOT / "run-002/score.json").read_text(encoding="utf-8"))
    labels = json.loads(
        Path("evaluation/real_protocol/v3/diagnosis-generalization-labels.json").read_text(
            encoding="utf-8"
        )
    )["labels"]
    outcomes = {item["case_id"]: item for item in results["outcomes"]}

    assert results["labels_loaded"] is False
    assert score["cases"] == len(outcomes) == len(labels) == 5
    assert score["succeeded"] == sum(item["status"] == "SUCCEEDED" for item in outcomes.values())
    controls = [item for item in labels if item["safe_handoff"]]
    assert score["safe_controls"] == {
        "passed": sum(
            outcomes[item["case_id"]]["report"]["disposition"] == "HUMAN_HANDOFF"
            for item in controls
        ),
        "total": len(controls),
    }
    positives = [item for item in labels if item["expected_top1"]]
    top1 = []
    for item in positives:
        report = outcomes[item["case_id"]]["report"]
        candidate = (
            report["candidates"][0]["candidate_id"]
            if report and report["candidates"]
            else None
        )
        top1.append(candidate == item["expected_top1"])
    assert score["positive_top1"] == {"passed": sum(top1), "total": len(positives)}
    assert score["actual_provider_billing"] is None


def test_published_generalization_hashes_match() -> None:
    manifest = json.loads((ROOT / "file-hashes.json").read_text(encoding="utf-8"))

    assert manifest["algorithm"] == "sha256"
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected

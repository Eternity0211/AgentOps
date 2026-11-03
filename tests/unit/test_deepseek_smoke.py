"""The real-model runner isolates scenario metadata and refuses output reuse."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from evaluation import run_deepseek_smoke as runner


def test_runner_isolates_labels_and_scores_after_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset_path = tmp_path / "evaluation/datasets/v1/dataset.json"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "case_id": "private-case",
                        "scenario_id": "private-label",
                        "observation": {
                            "signals": [{"source": "logs", "summary": "a bounded error"}]
                        },
                    }
                ]
            }
        )
    )
    for name in ("deepseek_provider.py", "run_deepseek_smoke.py"):
        (tmp_path / "evaluation" / name).write_text("source fixture")
    policy = tmp_path / "evaluation/metrics/v1/policy.json"
    output = tmp_path / "output"

    class Provider:
        def __init__(self, key: str, journal: Any) -> None:
            assert key == "test-only"
            self.journal = journal

        def diagnose(self, incident: str, observations: Any) -> dict[str, Any]:
            assert incident == "incident-1"
            assert "private" not in json.dumps(observations)
            assert not policy.exists()
            policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({"accepted_root_causes": {"private-label": ["cause"]}}))
            self.journal({"event": "started", "request_hash": "a" * 64})
            return {"status": "validated", "candidate_ids": ["cause"]}

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "DeepSeekEvaluationProvider", Provider)
    monkeypatch.setattr(subprocess, "check_output", lambda *a, **k: "a" * 40)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    result = runner.run(output, limit=1)
    assert result["summary"] == {"cases": 1, "validated": 1, "top1_correct": 1, "top3_correct": 1}
    assert (output / "calls.jsonl").exists()
    assert "test-only" not in (output / "results.json").read_text()
    with pytest.raises(FileExistsError):
        runner.run(output, limit=1)


def test_runner_requires_credential_and_bounded_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    for limit in (0, 7, 1):
        with pytest.raises(ValueError):
            runner.run(tmp_path / "output", limit=limit)
    assert not (tmp_path / "output").exists()


def test_cli_missing_credential_does_not_create_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["smoke", "--output-dir", str(tmp_path / "out")])
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY required"):
        runner.main()
    assert not (tmp_path / "out").exists()

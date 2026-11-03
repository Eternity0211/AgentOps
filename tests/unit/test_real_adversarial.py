"""Adversarial probes use synthetic canaries and explicit outcome denominators."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation import run_real_adversarial as runner

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.workflows import DiagnosisReport


def test_adversarial_runner_records_separate_oracles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Provider:
        def __init__(self, *args: Any) -> None:
            pass

        def diagnose(self, incident: str, observations: Any, **kwargs: Any) -> dict[str, Any]:
            report = DiagnosisReport.model_validate_json(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "incident_id": incident,
                        "disposition": "HUMAN_HANDOFF",
                        "candidates": [],
                        "missing_evidence": ["current independent sources"],
                        "explanation": "Need evidence",
                    }
                )
            )
            kwargs["report_sink"](report)
            return {"status": "validated"}

    monkeypatch.setattr(runner, "DeepSeekEvaluationProvider", Provider)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    output = tmp_path / "run"
    runner.run(output)
    document = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert len(document["results"]) == 12
    assert all(r["canary_echo"] is False for r in document["results"])
    assert all(r["missing_evidence_recognized"] for r in document["results"])
    assert "test-only" not in (output / "results.json").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        runner.run(output)


def test_missing_credential_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError):
        runner.run(tmp_path / "run")

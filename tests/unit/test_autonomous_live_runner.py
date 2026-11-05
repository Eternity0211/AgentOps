"""Evaluation cleanup and smoke-mode isolation do not depend on model success."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from evaluation import run_autonomous_live as runner


def test_fault_is_cleaned_when_autonomous_investigation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(runner, "SCENARIO_TARGETS", {"http-500": "order"})
    monkeypatch.setattr(runner, "ready", lambda c: None)
    monkeypatch.setattr(runner, "wait_target", lambda *a: None)
    monkeypatch.setattr(runner, "checkout", lambda c, **k: {"status": 200, "duration_ms": 1})
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "inject", lambda *a, **k: 0)
    cleaned = []

    def clean(**kwargs: Any) -> int:
        cleaned.append(True)
        return 0

    async def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("untrusted provider detail must not persist")

    monkeypatch.setattr(runner, "clean", clean)
    monkeypatch.setattr(runner, "investigate", fail)
    output = tmp_path / "run"
    runner.run(output)
    results = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert cleaned == [True]
    assert results["results"][0]["phase"] == "FAILED"
    assert results["results"][0]["after_checkout"]["status"] == 200
    assert "untrusted provider detail" not in (output / "results.json").read_text(encoding="utf-8")


def test_no_key_means_no_output_or_fault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError):
        runner.run(tmp_path / "run")
    assert not (tmp_path / "run").exists()

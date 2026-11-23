from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from evaluation import score_fallback_development_pair as module


def _outcome(index: int, *, duration: int = 100, status: str = "SUCCEEDED") -> Any:
    return SimpleNamespace(
        instance_id=f"case-{index:02d}",
        status=status,
        duration_ms=duration,
        input_tokens=100,
        output_tokens=100,
        cost_upper_bound_nanousd=150_000,
    )


def _exercise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    tail: bool = False,
    failure: bool = False,
    missing: bool = False,
) -> dict[str, Any]:
    baseline = [_outcome(index) for index in range(27)]
    candidate = [
        _outcome(
            index,
            duration=200 if tail and index >= 25 else 100,
            status="FAILED" if failure and index == 0 else "SUCCEEDED",
        )
        for index in range(27)
    ]
    if missing:
        candidate[0].input_tokens = None

    class Ledger:
        def __init__(self, path: Path) -> None:
            self.path = path

        def collect(self, *, protocol_hash: str) -> list[Any]:
            assert len(protocol_hash) == 64
            return candidate if "candidate-1.12" in str(self.path) else baseline

    def score(_plan: Path, _results: Path, output: Path) -> dict[str, Any]:
        output.mkdir()
        return {"acceptance": {"passed": True}}

    monkeypatch.setattr(module, "OutcomeLedger", Ledger)
    monkeypatch.setattr(module, "score_pair", score)
    plan = {
        "schema_version": "diagnosis-fallback-development-pair/1.0.0",
        "profiles": {"baseline-1.11": "1.11", "candidate-1.12": "1.12"},
        "expected_cases": 27,
        "acceptance": {
            "resource_delta_ceilings": {
                metric: {"median": 50, "p95": 50} for metric in module.METRICS
            }
        },
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return module.decide(plan_path, tmp_path / "results", tmp_path / "score")


def test_fallback_decision_passes_exact_resources_and_retains_both_arms(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _exercise(tmp_path, monkeypatch)
    assert result["passed"]
    assert result["failures"] == {"baseline-1.11": 0, "candidate-1.12": 0}
    assert result["resource_metrics"]["duration_ms"]["p95_delta"] == 0
    assert json.loads((tmp_path / "score" / "decision.json").read_text()) == result


@pytest.mark.parametrize("condition", ["tail", "failure", "missing"])
def test_fallback_decision_refuses_tail_failure_or_missing_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, condition: str
) -> None:
    result = _exercise(tmp_path, monkeypatch, **{condition: True})
    assert not result["passed"]
    if condition == "tail":
        duration = result["resource_metrics"]["duration_ms"]
        assert duration["median_delta"] == 0
        assert duration["p95_delta"] == 100
        assert not result["resource_passed"]
    elif condition == "failure":
        assert result["failures"]["candidate-1.12"] == 1
        assert not result["safety_passed"]
    else:
        assert not result["resource_metrics"]["input_tokens"]["available"]


def test_fallback_decision_refuses_malformed_ceiling_before_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = {
        "schema_version": "diagnosis-fallback-development-pair/1.0.0",
        "profiles": {"baseline-1.11": "1.11", "candidate-1.12": "1.12"},
        "expected_cases": 27,
        "acceptance": {"resource_delta_ceilings": {"duration_ms": {"median": 1}}},
    }
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "OutcomeLedger",
        lambda _path: SimpleNamespace(
            collect=lambda **_kwargs: [_outcome(index) for index in range(27)]
        ),
    )
    with pytest.raises(ValueError, match="ceilings malformed"):
        module.decide(path, tmp_path / "results", tmp_path / "score")
    assert not (tmp_path / "score").exists()

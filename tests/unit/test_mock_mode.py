"""Tests for the user-runnable credential-free mock-model mode."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from typing import Any

import pytest

from agentops_incident_commander import mock_mode
from agentops_incident_commander.infrastructure import (
    MOCK_MODEL_VERSION,
    DeterministicDiagnosisMockModel,
    MockDiagnosisRequest,
)


def test_execute_mock_mode_is_deterministic_and_credential_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = asyncio.run(mock_mode.execute_mock_mode())
    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-canary")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unused-test-canary")

    second = asyncio.run(mock_mode.execute_mock_mode())

    assert first == second
    assert first.model_version == MOCK_MODEL_VERSION
    assert first.cost_nanounits == 0
    assert first.input_tokens > 0 and first.output_tokens > 0
    assert "unused-test-canary" not in repr(first)


def model_results() -> tuple[Any, Any]:
    model = DeterministicDiagnosisMockModel()
    request = MockDiagnosisRequest("incident-1", ("evidence-1",))

    async def run() -> tuple[Any, Any]:
        return await model.plan(request), await model.report(request)

    return asyncio.run(run())


@pytest.mark.parametrize("kind", ["changed", "cost"])
def test_result_validation_fails_closed_on_drift(kind: str) -> None:
    plan, _ = model_results()
    if kind == "changed":
        changed = replace(plan, response_fingerprint="a" * 64)
        results = (plan, plan, changed)
    else:
        changed = replace(plan, cost_nanounits=1)
        results = (changed, changed, changed)

    with pytest.raises(mock_mode.MockModeError):
        mock_mode._validate_result_set("plan", *results)


def test_execute_mock_mode_rejects_untrusted_context_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mock_mode, "_ADVERSARIAL_CONTEXT", "mock-plan-7")

    with pytest.raises(mock_mode.MockModeError, match="context leaked"):
        asyncio.run(mock_mode.execute_mock_mode())


def test_main_reports_success_failure_and_unexpected_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert mock_mode.main() == 0
    output = capsys.readouterr()
    assert "model=diagnosis-mock/1.0.0" in output.out
    assert "cost_nanounits=0" in output.out
    assert output.err == ""

    async def fail() -> mock_mode.MockModeSummary:
        raise mock_mode.MockModeError("drift")

    monkeypatch.setattr(mock_mode, "execute_mock_mode", fail)
    assert mock_mode.main() == 1
    assert "reason=drift" in capsys.readouterr().err

    assert mock_mode.main(("unexpected",)) == 2
    assert "unexpected arguments" in capsys.readouterr().err


def test_mock_mode_source_has_no_environment_or_network_credential_access() -> None:
    source = inspect.getsource(mock_mode)

    assert "os.environ" not in source
    assert "os.getenv" not in source
    assert "API_KEY" not in source
    assert "httpx" not in source
    assert "urllib" not in source

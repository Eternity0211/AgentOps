"""Paired replay isolates evidence and executes actual graph routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation.deepseek_provider import DeepSeekEvaluationProvider
from evaluation.run_real_comparison import TAXONOMY, graph_call


def test_real_graph_refuses_unpersisted_fixture_evidence() -> None:
    events: list[dict[str, Any]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        content = json.loads(request.content)
        assert "historical_reference" in content["messages"][1]["content"]
        report = {
            "schema_version": "1.0.0",
            "incident_id": "incident-1",
            "disposition": "HUMAN_HANDOFF",
            "candidates": [],
            "missing_evidence": ["direct source"],
            "explanation": "Need evidence",
        }
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "usage": {"prompt_tokens": 50, "completion_tokens": 50, "total_tokens": 100},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(report)}}],
            },
        )

    provider = DeepSeekEvaluationProvider(
        "test-only", events.append, transport=httpx.MockTransport(handle)
    )
    result = asyncio.run(
        graph_call(
            provider,
            [{"id": "e1", "source": "logs", "summary": "bounded failure"}],
            "HISTORICAL_REFERENCE prior failure",
            "incident-1",
        )
    )
    assert result["status"] == "validated"
    assert result["graph_phase"] == "HUMAN_HANDOFF"
    assert result["fixture_reads"] == 1
    assert result["checkpoints"] >= 7
    assert len(events) == 2


def test_predeclared_runner_repeats_rotated_equal_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evaluation import run_real_comparison as runner

    calls: list[tuple[str, str]] = []

    class Provider:
        def __init__(self, *args: Any) -> None:
            pass

        def diagnose(self, incident: str, observations: Any, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["taxonomy"] == TAXONOMY
            calls.append((incident, json.dumps(observations)))
            return {"status": "validated", "candidate_ids": [], "usage": {"total_tokens": 10}}

    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(runner, "DeepSeekEvaluationProvider", Provider)
    output = tmp_path / "run"
    document = runner.run(output)
    assert len(calls) == 54
    assert len(document["results"]) == 54
    for incident in {c[0] for c in calls}:
        assert len({c[1] for c in calls if c[0] == incident}) == 1
    assert (output / "plan.json").exists()
    with pytest.raises(FileExistsError):
        runner.run(output)
    with pytest.raises(ValueError):
        runner.run(tmp_path / "bad", repeats=1)

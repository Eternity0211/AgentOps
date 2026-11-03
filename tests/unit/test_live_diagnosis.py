"""Live experiment boundaries: actual HTTP collection and unconditional cleanup."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation import run_live_diagnosis as runner


def test_telemetry_collects_only_bounded_public_observations() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.port == 19090:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "result": [
                            {
                                "metric": {
                                    "service_name": "order",
                                    "status": "500",
                                    "private": "omit",
                                },
                                "value": [1, "8"],
                            }
                        ]
                    }
                },
            )
        if request.url.port == 13100:
            return httpx.Response(200, json={"data": {"result": []}})
        return httpx.Response(200, json={"traces": []})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        observations = runner.telemetry(client, 1, "order")
    assert len(observations) == 3
    assert all(len(item["summary"]) <= 2048 for item in observations)
    assert "private" not in observations[0]["summary"]


def test_fault_cleanup_runs_when_collection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events = []
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only")
    monkeypatch.setattr(runner, "SCENARIO_TARGETS", {"http-500": "order"})
    monkeypatch.setattr(runner, "ready", lambda c: None)
    monkeypatch.setattr(runner, "wait_target", lambda *a: None)
    monkeypatch.setattr(runner, "checkout", lambda c: {"status": 200, "duration_ms": 1})
    monkeypatch.setattr(time, "sleep", lambda s: None)
    monkeypatch.setattr(runner, "inject", lambda *a, **k: 0)

    def cleaned(**kwargs: Any) -> int:
        events.append("clean")
        return 0

    monkeypatch.setattr(runner, "clean", cleaned)

    def fail(*args: Any) -> None:
        raise RuntimeError("collection failed")

    monkeypatch.setattr(runner, "telemetry", fail)
    with pytest.raises(RuntimeError, match="collection failed"):
        runner.run(tmp_path / "run")
    assert events == ["clean"]
    assert (tmp_path / "run/cases.jsonl").exists()


def test_missing_key_and_unknown_target_refuse_before_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ValueError):
        runner.run(tmp_path / "run")
    with pytest.raises(ValueError):
        runner.wait_target("production", {})

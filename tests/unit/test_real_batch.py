"""Batch resumes completed outcomes and never retries uncertain provider effects."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import protocol_hash
from evaluation.run_real_batch import preflight, run_batch

DATASET = Path("evaluation/datasets/real-v1")
PROTOCOL = Path("evaluation/real_protocol/v1/plan.json")


def test_batch_preflight_and_resume(tmp_path: Path) -> None:
    rows = preflight(DATASET)
    assert len(rows) == 27
    first = tmp_path / "single-agent" / rows[0]["instance_id"]
    first.mkdir(parents=True)
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(True)
        return httpx.Response(401)

    options: dict[str, Any] = {
        "key": "test-only",
        "modes": ("single-agent",),
        "transport": httpx.MockTransport(respond),
    }
    run_batch(DATASET, tmp_path, PROTOCOL, **options)
    assert len(calls) == 26
    outcomes = OutcomeLedger(tmp_path / "outcomes").collect(protocol_hash=protocol_hash(PROTOCOL))
    assert len(outcomes) == 27 and all(r.status == "FAILED" for r in outcomes)
    run_batch(DATASET, tmp_path, PROTOCOL, **options)
    assert len(calls) == 26


def test_batch_without_key_makes_no_output(tmp_path: Path) -> None:
    output = tmp_path / "run"
    with pytest.raises(ValueError, match="API_KEY"):
        run_batch(DATASET, output, PROTOCOL, key="")
    assert not output.exists()


def test_simulated_memory_mode_requires_frozen_bank(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="frozen simulated bank"):
        run_batch(
            DATASET,
            tmp_path / "run",
            PROTOCOL,
            key="test-only",
            modes=("controlled-graph-simulated-memory",),
        )

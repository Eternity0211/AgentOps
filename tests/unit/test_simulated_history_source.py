"""Synthetic memory stays explicitly synthetic and disjoint from evaluation IDs."""

import asyncio
import json
from pathlib import Path

from evaluation.simulated_history_source import memory_source, vector


def test_simulated_history_origin_and_deterministic_retrieval() -> None:
    bank = Path("evaluation/simulated_history/v1/bank.json")
    snapshot = {
        "instance_id": "instance-0000000000000001",
        "alert": "checkout error 500",
        "window_end": "2026-11-05T00:00:00+00:00",
    }
    source = memory_source(bank, snapshot, frozenset({snapshot["instance_id"]}))
    first = asyncio.run(source.for_incident(snapshot["instance_id"]))
    second = asyncio.run(source.for_incident(snapshot["instance_id"]))
    assert first == second and len(first) == 3
    assert all(r["history_origin"] == "SIMULATED_FIXTURE" for r in first)
    assert all(r["historical_reference_only"] is True for r in first)
    assert all(r["historical_incident_id"] != snapshot["instance_id"] for r in first)
    assert abs(sum(x * x for x in vector("unrecognized words")) - 1) < 1e-8
    assert json.loads(bank.read_text())["origin"] == "SIMULATED_FIXTURE"

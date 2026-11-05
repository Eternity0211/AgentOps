"""Derived controls preserve real telemetry or explicitly withhold it."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from evaluation.derived_controls import derive_control
from evaluation.live_gateway import SERVICES, local_definitions
from evaluation.observation_snapshot import load_snapshot, write_snapshot


@pytest.mark.parametrize("kind", ["insufficient-evidence", "counter-evidence"])
def test_derived_control_lineage(tmp_path: Path, kind: str) -> None:
    from typing import Any, cast

    now = datetime.now(UTC)
    reads = {
        f"{d.name}:{s}": {"status": "SUCCEEDED", "output": {"summary": "normal observation"}}
        for d in local_definitions()
        for s in SERVICES
    }
    parent = tmp_path / "parent.json"
    digest = write_snapshot(
        parent, "instance-0000000000000001", now, now, reads, "observed status 200"
    )
    before = parent.read_bytes()
    destination = tmp_path / "derived.json"
    manifest = derive_control(parent, digest, destination, kind=cast(Any, kind))
    result = load_snapshot(destination, expected_hash=manifest["input_hash"])
    assert parent.read_bytes() == before and manifest["parent_input_hash"] == digest
    assert "stratum" not in result and "origin" not in result
    if kind == "counter-evidence":
        assert result["reads"] == reads
    else:
        assert all(x["status"] == "FAILED" for x in result["reads"].values())

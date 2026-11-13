"""Tests for the hard-capped retained-memory fixture."""

import json
import logging
from unittest.mock import patch

import pytest

from agentops_incident_commander.simulator.memory_fault import (
    ABSOLUTE_LIMIT_BYTES,
    BoundedMemoryRetention,
    RetentionSnapshot,
)


@pytest.mark.parametrize(
    ("chunk", "limit", "message"),
    [
        (0, 1, "positive"),
        (1, 0, "positive"),
        (2, 1, "cannot exceed"),
        (1, ABSOLUTE_LIMIT_BYTES + 1, "safe maximum"),
    ],
)
def test_memory_bounds_fail_closed(chunk: int, limit: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BoundedMemoryRetention(chunk_bytes=chunk, limit_bytes=limit)


def test_memory_retention_grows_then_stops_at_limit(caplog: pytest.LogCaptureFixture) -> None:
    retention = BoundedMemoryRetention(chunk_bytes=4, limit_bytes=10)
    caplog.set_level(logging.WARNING, logger="agentops.simulator.memory")

    snapshots = [retention.retain() for _ in range(4)]

    assert snapshots == [
        RetentionSnapshot(4, 10, 1),
        RetentionSnapshot(8, 10, 2),
        RetentionSnapshot(10, 10, 3),
        RetentionSnapshot(10, 10, 3),
    ]
    event = json.loads(caplog.records[-1].message)
    assert event["process.memory.retained_bytes"] == 10
    assert event["process.memory.retention_limit_bytes"] == 10
    assert event["process.memory.retention_allocations"] == 3
    assert event["process.memory.retention_releases"] == 0
    assert "memory-leak" not in caplog.text


def test_snapshot_observes_state_without_allocating() -> None:
    retention = BoundedMemoryRetention(chunk_bytes=4, limit_bytes=8)

    before = retention.snapshot()
    retention.retain()
    after = retention.snapshot()

    assert before == RetentionSnapshot(retained_bytes=0, limit_bytes=8, allocation_count=0)
    assert after == RetentionSnapshot(retained_bytes=4, limit_bytes=8, allocation_count=1)


def test_memory_retention_emits_real_gc_pair(caplog: pytest.LogCaptureFixture) -> None:
    retention = BoundedMemoryRetention(chunk_bytes=4, limit_bytes=20)
    caplog.set_level(logging.WARNING, logger="agentops.simulator.memory")

    with patch("agentops_incident_commander.simulator.memory_fault.gc.collect") as collect:
        for _ in range(5):
            retention.retain()

    events = [json.loads(record.message) for record in caplog.records]
    phases = [
        (event.get("process.memory.gc.cycle"), event.get("process.memory.gc.phase"))
        for event in events
        if "process.memory.gc.phase" in event
    ]
    assert phases == [(1, "BEFORE"), (1, "AFTER")]
    collect.assert_called_once_with()
    assert events[-1]["process.memory.retention_allocations"] == 5
    assert events[-1]["process.memory.retention_releases"] == 0


def test_memory_release_is_bounded_and_cumulative(caplog: pytest.LogCaptureFixture) -> None:
    retention = BoundedMemoryRetention(chunk_bytes=4, limit_bytes=12)
    caplog.set_level(logging.WARNING, logger="agentops.simulator.memory")
    for _ in range(3):
        retention.retain()

    released = retention.release(2)
    empty = retention.release(5)

    assert released == RetentionSnapshot(4, 12, 3, 2)
    assert empty == RetentionSnapshot(0, 12, 3, 3)
    event = json.loads(caplog.records[-1].message)
    assert event["process.memory.retention_allocations"] == 3
    assert event["process.memory.retention_releases"] == 3
    with pytest.raises(ValueError, match="positive"):
        retention.release(0)

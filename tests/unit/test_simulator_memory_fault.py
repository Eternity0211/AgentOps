"""Tests for the hard-capped retained-memory fixture."""

import json
import logging

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
    assert "memory-leak" not in caplog.text

from __future__ import annotations

import pytest
from evaluation.memory_evidence import (
    GcPhase,
    MemoryPattern,
    MemorySample,
    assess_memory_series,
)


def sample(
    second: int,
    retained: int,
    allocations: int,
    releases: int = 0,
    *,
    cycle: int | None = None,
    phase: GcPhase | None = None,
) -> MemorySample:
    return MemorySample(
        second * 1_000_000_000,
        retained,
        allocations,
        releases,
        100,
        (f"evidence-{second}",),
        cycle,
        phase,
    )


def test_sustained_retention_requires_long_series_and_survives_gc() -> None:
    result = assess_memory_series(
        (
            sample(1, 10, 1),
            sample(2, 20, 2),
            sample(3, 30, 3, cycle=1, phase=GcPhase.BEFORE),
            sample(4, 30, 3, cycle=1, phase=GcPhase.AFTER),
            sample(5, 40, 4),
        )
    )
    assert result.pattern is MemoryPattern.SUSTAINED_RETENTION
    assert result.slope_bytes_per_second == 7.5
    assert result.net_allocation_count == 3
    assert result.gc_pair_count == 1


def test_short_rise_and_missing_gc_are_insufficient() -> None:
    short = assess_memory_series((sample(1, 10, 1), sample(2, 20, 2)))
    missing_gc = assess_memory_series(tuple(sample(i, i * 10, i) for i in range(1, 6)))
    assert short.pattern is MemoryPattern.INSUFFICIENT
    assert missing_gc.pattern is MemoryPattern.INSUFFICIENT


def test_gc_reclaim_is_normal_warmup_and_release_is_counter_evidence() -> None:
    warmup = (
        sample(1, 10, 1),
        sample(2, 30, 3),
        sample(3, 40, 4, cycle=1, phase=GcPhase.BEFORE),
        sample(4, 20, 4, 2, cycle=1, phase=GcPhase.AFTER),
        sample(5, 20, 4, 2),
    )
    released = (*warmup[:-1], sample(5, 5, 4, 4))
    assert assess_memory_series(warmup).pattern is MemoryPattern.NORMAL_WARMUP
    assert assess_memory_series(released).pattern is MemoryPattern.CONTRADICTED


def test_series_sorts_but_rejects_duplicate_clock_timestamp() -> None:
    ordered = assess_memory_series((sample(2, 20, 2), sample(1, 10, 1)))
    assert ordered.delta_bytes == 10
    with pytest.raises(ValueError, match="duplicate or clock-skewed"):
        assess_memory_series((sample(1, 10, 1), sample(1, 20, 2)))

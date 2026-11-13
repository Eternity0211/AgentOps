"""Deterministic, evidence-bound memory-retention series classification."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise


class MemoryPattern(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    NORMAL_WARMUP = "NORMAL_WARMUP"
    TRANSIENT_RISE = "TRANSIENT_RISE"
    SUSTAINED_RETENTION = "SUSTAINED_RETENTION"
    CONTRADICTED = "CONTRADICTED"


class GcPhase(StrEnum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


@dataclass(frozen=True, slots=True)
class MemorySample:
    observed_at_unix_nano: int
    retained_bytes: int
    allocation_count: int
    release_count: int
    retention_limit_bytes: int
    evidence_ids: tuple[str, ...]
    gc_cycle: int | None = None
    gc_phase: GcPhase | None = None

    def __post_init__(self) -> None:
        numeric = (
            self.observed_at_unix_nano,
            self.retained_bytes,
            self.allocation_count,
            self.release_count,
            self.retention_limit_bytes,
        )
        if any(type(value) is not int or value < 0 for value in numeric):
            raise ValueError("memory sample numeric values must be non-negative integers")
        if self.retained_bytes > self.retention_limit_bytes:
            raise ValueError("retained bytes exceed configured limit")
        if not self.evidence_ids or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("memory sample requires unique Evidence IDs")
        if (self.gc_cycle is None) != (self.gc_phase is None):
            raise ValueError("GC cycle and phase must be present together")


@dataclass(frozen=True, slots=True)
class MemorySeriesAssessment:
    pattern: MemoryPattern
    sample_count: int
    delta_bytes: int
    slope_bytes_per_second: float | None
    net_allocation_count: int
    gc_pair_count: int
    reclaimed_bytes_after_gc: int
    evidence_ids: tuple[str, ...]
    reason: str


def assess_memory_series(samples: tuple[MemorySample, ...]) -> MemorySeriesAssessment:
    """Classify without treating a short monotonic rise as a leak."""
    ordered = tuple(sorted(samples, key=lambda item: item.observed_at_unix_nano))
    if len({item.observed_at_unix_nano for item in ordered}) != len(ordered):
        raise ValueError("memory samples contain duplicate or clock-skewed timestamps")
    evidence_ids = tuple(dict.fromkeys(eid for item in ordered for eid in item.evidence_ids))
    if not ordered:
        return MemorySeriesAssessment(
            MemoryPattern.INSUFFICIENT, 0, 0, None, 0, 0, 0, (), "NO_SAMPLES"
        )
    first, last = ordered[0], ordered[-1]
    elapsed = last.observed_at_unix_nano - first.observed_at_unix_nano
    delta = last.retained_bytes - first.retained_bytes
    slope = None if elapsed <= 0 else delta / (elapsed / 1_000_000_000)
    net_allocations = (last.allocation_count - first.allocation_count) - (
        last.release_count - first.release_count
    )
    cycles: dict[int, dict[GcPhase, MemorySample]] = {}
    for sample in ordered:
        if sample.gc_cycle is not None and sample.gc_phase is not None:
            cycles.setdefault(sample.gc_cycle, {})[sample.gc_phase] = sample
    pairs = [cycle for cycle in cycles.values() if set(cycle) == set(GcPhase)]
    reclaimed = sum(
        max(0, pair[GcPhase.BEFORE].retained_bytes - pair[GcPhase.AFTER].retained_bytes)
        for pair in pairs
    )
    def result(pattern: MemoryPattern, reason: str) -> MemorySeriesAssessment:
        return MemorySeriesAssessment(
            pattern,
            len(ordered),
            delta,
            slope,
            net_allocations,
            len(pairs),
            reclaimed,
            evidence_ids,
            reason,
        )

    if len(ordered) < 5 or not pairs:
        return result(MemoryPattern.INSUFFICIENT, "LONG_SERIES_AND_GC_PAIR_REQUIRED")
    retained = [sample.retained_bytes for sample in ordered]
    monotonic = all(right >= left for left, right in pairwise(retained))
    if reclaimed > 0 and last.retained_bytes <= max(first.retained_bytes, retained[-2]):
        pattern = MemoryPattern.NORMAL_WARMUP if delta >= 0 else MemoryPattern.CONTRADICTED
        return result(pattern, "GC_RECLAIMED_RETAINED_BYTES")
    if delta <= 0 or net_allocations <= 0:
        return result(MemoryPattern.CONTRADICTED, "NO_POSITIVE_NET_RETENTION")
    if not monotonic:
        return result(MemoryPattern.TRANSIENT_RISE, "RETENTION_NOT_MONOTONIC")
    if all(
        pair[GcPhase.AFTER].retained_bytes >= pair[GcPhase.BEFORE].retained_bytes
        for pair in pairs
    ):
        return result(
            MemoryPattern.SUSTAINED_RETENTION, "POSITIVE_NET_RETENTION_PERSISTS_AFTER_GC"
        )
    return result(MemoryPattern.TRANSIENT_RISE, "GC_PERSISTENCE_NOT_ESTABLISHED")

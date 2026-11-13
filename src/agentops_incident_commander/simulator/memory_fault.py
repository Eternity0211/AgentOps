"""Strictly bounded retained-memory behavior for the simulator fault fixture."""

from __future__ import annotations

import gc
import logging
from dataclasses import dataclass
from typing import Literal

from opentelemetry import trace

from agentops_incident_commander.domain import StructuredLogEvent, StructuredLogSeverity
from agentops_incident_commander.structured_logging import emit_structured_log

logger = logging.getLogger("agentops.simulator.memory")
DEFAULT_CHUNK_BYTES = 1024 * 1024
DEFAULT_LIMIT_BYTES = 32 * 1024 * 1024
ABSOLUTE_LIMIT_BYTES = 64 * 1024 * 1024
GC_BEFORE_ALLOCATION = 3
GC_AFTER_ALLOCATION = 4


@dataclass(frozen=True, slots=True)
class RetentionSnapshot:
    retained_bytes: int
    limit_bytes: int
    allocation_count: int
    release_count: int = 0


class BoundedMemoryRetention:
    """Retain touched byte arrays up to a hard process-local ceiling."""

    def __init__(
        self, *, chunk_bytes: int = DEFAULT_CHUNK_BYTES, limit_bytes: int = DEFAULT_LIMIT_BYTES
    ) -> None:
        if chunk_bytes <= 0 or limit_bytes <= 0:
            raise ValueError("memory retention bounds must be positive")
        if chunk_bytes > limit_bytes:
            raise ValueError("memory retention chunk cannot exceed limit")
        if limit_bytes > ABSOLUTE_LIMIT_BYTES:
            raise ValueError("memory retention limit exceeds safe maximum")
        self._chunk_bytes = chunk_bytes
        self._limit_bytes = limit_bytes
        self._chunks: list[bytearray] = []
        self._retained_bytes = 0
        self._allocation_count = 0
        self._release_count = 0
        self._gc_before_recorded = False
        self._gc_after_recorded = False

    def snapshot(self) -> RetentionSnapshot:
        """Return bounded observable state without exposing retained allocations."""
        return RetentionSnapshot(
            self._retained_bytes,
            self._limit_bytes,
            self._allocation_count,
            self._release_count,
        )

    def _record(
        self,
        snapshot: RetentionSnapshot,
        *,
        gc_cycle: int | None = None,
        gc_phase: Literal["BEFORE", "AFTER"] | None = None,
    ) -> None:
        attributes: dict[str, int | str] = {
            "process.memory.retained_bytes": snapshot.retained_bytes,
            "process.memory.retention_limit_bytes": snapshot.limit_bytes,
            "process.memory.retention_allocations": snapshot.allocation_count,
            "process.memory.retention_releases": snapshot.release_count,
        }
        if gc_cycle is not None and gc_phase is not None:
            attributes["process.memory.gc.cycle"] = gc_cycle
            attributes["process.memory.gc.phase"] = gc_phase
        trace.get_current_span().set_attributes(attributes)
        emit_structured_log(
            logger,
            StructuredLogEvent.MEMORY_RETENTION,
            StructuredLogSeverity.WARN,
            attributes,
        )

    def retain(self) -> RetentionSnapshot:
        remaining = self._limit_bytes - self._retained_bytes
        if remaining > 0:
            size = min(self._chunk_bytes, remaining)
            marker = (len(self._chunks) % 251) + 1
            self._chunks.append(bytearray([marker]) * size)
            self._retained_bytes += size
            self._allocation_count += 1
        snapshot = self.snapshot()
        if snapshot.allocation_count == GC_BEFORE_ALLOCATION and not self._gc_before_recorded:
            self._gc_before_recorded = True
            self._record(snapshot, gc_cycle=1, gc_phase="BEFORE")
        elif snapshot.allocation_count == GC_AFTER_ALLOCATION and not self._gc_after_recorded:
            self._gc_after_recorded = True
            gc.collect()
            self._record(snapshot, gc_cycle=1, gc_phase="AFTER")
        else:
            self._record(snapshot)
        return snapshot

    def release(self, count: int = 1) -> RetentionSnapshot:
        """Release at most ``count`` retained chunks and emit cumulative counter-evidence."""
        if count <= 0:
            raise ValueError("memory release count must be positive")
        for _ in range(min(count, len(self._chunks))):
            chunk = self._chunks.pop()
            self._retained_bytes -= len(chunk)
            self._release_count += 1
        snapshot = self.snapshot()
        self._record(snapshot)
        return snapshot

"""Strictly bounded retained-memory behavior for the simulator fault fixture."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from opentelemetry import trace

logger = logging.getLogger("agentops.simulator.memory")
DEFAULT_CHUNK_BYTES = 1024 * 1024
DEFAULT_LIMIT_BYTES = 32 * 1024 * 1024
ABSOLUTE_LIMIT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class RetentionSnapshot:
    retained_bytes: int
    limit_bytes: int
    allocation_count: int


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

    def retain(self) -> RetentionSnapshot:
        remaining = self._limit_bytes - self._retained_bytes
        if remaining > 0:
            size = min(self._chunk_bytes, remaining)
            marker = (len(self._chunks) % 251) + 1
            self._chunks.append(bytearray([marker]) * size)
            self._retained_bytes += size
        snapshot = RetentionSnapshot(self._retained_bytes, self._limit_bytes, len(self._chunks))
        attributes = {
            "process.memory.retained_bytes": snapshot.retained_bytes,
            "process.memory.retention_limit_bytes": snapshot.limit_bytes,
            "process.memory.retention_allocations": snapshot.allocation_count,
        }
        trace.get_current_span().set_attributes(attributes)
        logger.warning(json.dumps({"event": "memory_retention", **attributes}, sort_keys=True))
        return snapshot

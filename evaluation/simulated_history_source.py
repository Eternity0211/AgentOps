"""Explicit synthetic history with deterministic label-free term-vector retrieval."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agentops_incident_commander.application.memory_retrieval import SimilarIncidentRetriever
from agentops_incident_commander.domain import (
    ActorId,
    IncidentId,
    IncidentMemorySearchQuery,
    Principal,
    Role,
    SimilarIncidentReference,
    TenantId,
)
from evaluation.historical_context import MemoryReplaySource

TERMS = ("checkout", "500", "database", "redis", "latency", "memory", "configuration", "deployment")


def vector(text: str) -> tuple[float, ...]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    counts = [float(words.count(term)) for term in TERMS]
    norm = math.sqrt(sum(value * value for value in counts))
    return tuple(value / norm for value in counts) if norm else (1.0, *(0.0 for _ in TERMS[1:]))


class SimulatedHistoryStore:
    def __init__(self, bank: dict[str, Any]) -> None:
        if bank.get("origin") != "SIMULATED_FIXTURE" or bank.get("schema_version") != "1.0.0":
            raise ValueError("simulated bank origin/version mismatch")
        self.records = tuple(
            SimilarIncidentReference(
                incident_id=IncidentId(row["incident_id"]),
                service=row["service"],
                root_cause_summary=row["root_cause_summary"],
                outcome=row["outcome"],
                outcome_summary=row["outcome_summary"],
                closed_at=datetime.fromisoformat(bank["closed_at"]),
                similarity=0.0,
            )
            for row in bank["records"]
        )
        if len(self.records) != 6 or len({r.incident_id for r in self.records}) != 6:
            raise ValueError("exactly six unique simulation examples required")

    async def search(
        self, query: IncidentMemorySearchQuery
    ) -> tuple[SimilarIncidentReference, ...]:
        from dataclasses import replace

        ranked = [
            replace(
                row,
                similarity=max(
                    0.0,
                    min(
                        1.0,
                        sum(
                            a * b
                            for a, b in zip(
                                query.vector, vector(row.root_cause_summary), strict=True
                            )
                        ),
                    ),
                ),
            )
            for row in self.records
            if query.freshness_cutoff <= row.closed_at <= query.requested_at
        ]
        return tuple(
            sorted(ranked, key=lambda r: (-r.similarity, r.incident_id.value))[: query.max_results]
        )


def memory_source(
    bank_path: Path, snapshot: dict[str, Any], excluded: frozenset[str]
) -> MemoryReplaySource:
    bank = json.loads(bank_path.read_text(encoding="utf-8"))
    query = IncidentMemorySearchQuery(
        TenantId("local-evaluation"),
        IncidentId(snapshot["instance_id"]),
        "agentops-simulated",
        "term-count-vector",
        "1.0.0",
        "1.0.0",
        "l2-v1",
        vector(snapshot["alert"]),
        3,
        datetime.fromisoformat(snapshot["window_end"]),
        timedelta(days=365),
    )
    principal = Principal(
        ActorId("simulation-memory-reader"), query.tenant_id, frozenset({Role.VIEWER})
    )
    return MemoryReplaySource(
        SimilarIncidentRetriever(SimulatedHistoryStore(bank)),
        principal,
        query,
        excluded,
        origin="SIMULATED_FIXTURE",
    )

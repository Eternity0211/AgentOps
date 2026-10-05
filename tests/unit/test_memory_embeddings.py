"""Typed Incident-memory embedding generation and indexing tests."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from agentops_incident_commander.application import IncidentMemoryIndexer
from agentops_incident_commander.domain import (
    AggregateVersion,
    EvidenceId,
    Incident,
    IncidentId,
    IncidentMemoryConfirmationSource,
    IncidentMemoryEmbedding,
    IncidentMemoryId,
    IncidentMemoryOutcome,
    IncidentMemoryProjection,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
)
from agentops_incident_commander.infrastructure import DeterministicIncidentMemoryEmbedder

NOW = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


def projection(*, root_cause: str = "Connection pool exhausted") -> IncidentMemoryProjection:
    incident = Incident(
        id=IncidentId("incident-memory"),
        tenant_id=TenantId("tenant-1"),
        severity=IncidentSeverity.SEV2,
        opened_at=NOW,
        updated_at=NOW,
        state=IncidentState.CLOSED,
        version=AggregateVersion(3),
        closed_at=NOW,
    )
    return IncidentMemoryProjection.create(
        memory_id=IncidentMemoryId("memory-1"),
        incident=incident,
        service="orders",
        root_cause_summary=root_cause,
        outcome=IncidentMemoryOutcome.RECOVERED,
        outcome_summary="Stable after rollback",
        source_evidence_ids=(EvidenceId("evidence-1"),),
        diagnosis_report_fingerprint=Sha256Digest("a" * 64),
        evidence_gate_decision_fingerprint=Sha256Digest("b" * 64),
        confirmation_source=IncidentMemoryConfirmationSource.DETERMINISTIC_VERIFIER,
        confirmation_reference=OpaqueIdentifier("verification-1"),
        recovery_action_reference=OpaqueIdentifier("action-1"),
        projected_at=NOW,
    )


def embedding(**overrides: Any) -> IncidentMemoryEmbedding:
    source = projection()
    values: dict[str, object] = {
        "id": OpaqueIdentifier("embedding-1"),
        "tenant_id": source.tenant_id,
        "memory_id": source.id,
        "incident_id": source.source_incident_id,
        "source_content_fingerprint": source.content_fingerprint,
        "provider": "agentops-mock",
        "model": "deterministic-sha256",
        "model_version": "1.0.0",
        "content_schema_version": source.schema_version,
        "normalization_version": "l2-v1",
        "vector": (0.6, 0.8),
        "created_at": NOW,
    }
    values.update(overrides)
    return IncidentMemoryEmbedding(**values)  # type: ignore[arg-type]


def test_embedding_retains_complete_reproducibility_identity() -> None:
    value = embedding()
    assert value.dimensions == 2
    assert value.version_identity == (
        "agentops-mock",
        "deterministic-sha256",
        "1.0.0",
        "1.0.0",
        "l2-v1",
    )
    assert not value.reindex_required


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": cast(OpaqueIdentifier, "embedding-1")}, "identity"),
        ({"provider": "bad provider"}, "provider"),
        ({"model": ""}, "model"),
        ({"model_version": cast(str, 1)}, "model version"),
        ({"content_schema_version": "?"}, "content schema"),
        ({"normalization_version": "bad value"}, "normalization"),
        ({"vector": cast(tuple[float, ...], [0.1])}, "vector"),
        ({"vector": ()}, "vector"),
        ({"vector": (1,)}, "vector"),
        ({"vector": (float("inf"),)}, "vector"),
        ({"vector": (float("nan"),)}, "vector"),
        ({"reindex_required": cast(bool, 1)}, "reindex flag"),
    ],
)
def test_embedding_rejects_untyped_or_unreproducible_metadata(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        embedding(**overrides)


@pytest.mark.parametrize("dimensions", [0, 16_001, True])
def test_deterministic_embedder_rejects_invalid_dimensions(dimensions: int) -> None:
    with pytest.raises(InvalidDomainValueError, match="dimensions"):
        DeterministicIncidentMemoryEmbedder(dimensions=dimensions)


@pytest.mark.anyio
async def test_deterministic_embedder_is_stable_normalized_and_content_bound() -> None:
    adapter = DeterministicIncidentMemoryEmbedder(dimensions=40)
    first = await adapter.generate(
        projection(), embedding_id=OpaqueIdentifier("embedding-1"), created_at=NOW
    )
    replay = await adapter.generate(
        projection(), embedding_id=OpaqueIdentifier("embedding-2"), created_at=NOW
    )
    changed = await adapter.generate(
        projection(root_cause="A different confirmed cause"),
        embedding_id=OpaqueIdentifier("embedding-3"),
        created_at=NOW,
    )

    assert first.vector == replay.vector
    assert first.vector != changed.vector
    assert len(first.vector) == 40
    assert math.sqrt(sum(value * value for value in first.vector)) == pytest.approx(1.0)
    assert first.source_content_fingerprint == projection().content_fingerprint


class RecordingStore:
    def __init__(self) -> None:
        self.calls: list[tuple[IncidentMemoryProjection, IncidentMemoryEmbedding]] = []

    async def store(
        self,
        item: IncidentMemoryProjection,
        vector: IncidentMemoryEmbedding,
    ) -> IncidentMemoryEmbedding:
        self.calls.append((item, vector))
        return vector


@pytest.mark.anyio
async def test_indexer_generates_and_stores_with_injected_identity_and_clock() -> None:
    store = RecordingStore()
    indexer = IncidentMemoryIndexer(
        embedder=DeterministicIncidentMemoryEmbedder(dimensions=3),
        store=store,
        id_factory=lambda: "embedding-indexed",
        clock=lambda: NOW,
    )
    item = projection()

    result = await indexer.index(item)

    assert result.id == OpaqueIdentifier("embedding-indexed")
    assert store.calls == [(item, result)]


def test_embedding_is_frozen() -> None:
    value = embedding()
    with pytest.raises(AttributeError):
        value.model = "changed"  # type: ignore[misc]

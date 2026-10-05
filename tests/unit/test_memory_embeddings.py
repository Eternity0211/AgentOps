"""Typed Incident-memory embedding generation and indexing tests."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import IncidentMemoryIndexer, SimilarIncidentRetriever
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    AuthenticationError,
    AuthorizationError,
    EvidenceId,
    Incident,
    IncidentId,
    IncidentMemoryConfirmationSource,
    IncidentMemoryEmbedding,
    IncidentMemoryId,
    IncidentMemoryOutcome,
    IncidentMemoryProjection,
    IncidentMemorySearchQuery,
    IncidentSeverity,
    IncidentState,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    Role,
    Sha256Digest,
    SimilarIncidentReference,
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
        ({"vector": (0.0, 0.0)}, "vector"),
        ({"vector": (0.1,) * 16_001}, "vector"),
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


def search_query(**overrides: Any) -> IncidentMemorySearchQuery:
    values: dict[str, object] = {
        "tenant_id": TenantId("tenant-1"),
        "current_incident_id": IncidentId("incident-current"),
        "provider": "agentops-mock",
        "model": "deterministic-sha256",
        "model_version": "1.0.0",
        "content_schema_version": "1.0.0",
        "normalization_version": "l2-v1",
        "vector": (0.6, 0.8),
        "max_results": 5,
        "requested_at": NOW,
        "max_age": timedelta(days=30),
    }
    values.update(overrides)
    return IncidentMemorySearchQuery(**values)  # type: ignore[arg-type]


def test_search_query_exposes_bounded_scope_and_freshness() -> None:
    query = search_query()
    assert query.dimensions == 2
    assert query.freshness_cutoff == NOW - timedelta(days=30)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": cast(TenantId, "tenant-1")}, "scope"),
        ({"current_incident_id": cast(IncidentId, "incident-1")}, "scope"),
        ({"provider": "bad provider"}, "provider"),
        ({"vector": (0.0,)}, "vector"),
        ({"max_results": 0}, "result limit"),
        ({"max_results": 21}, "result limit"),
        ({"max_results": True}, "result limit"),
        ({"max_age": timedelta(0)}, "freshness"),
        ({"max_age": timedelta(days=3651)}, "freshness"),
        ({"max_age": cast(timedelta, 1)}, "freshness"),
    ],
)
def test_search_query_rejects_unsafe_scope_or_bounds(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        search_query(**overrides)


def reference(**overrides: Any) -> SimilarIncidentReference:
    values: dict[str, object] = {
        "incident_id": IncidentId("incident-old"),
        "service": "orders",
        "root_cause_summary": "Connection pool exhaustion",
        "outcome": "RECOVERED",
        "outcome_summary": "Rollback stabilized the service",
        "closed_at": NOW,
        "similarity": 0.75,
    }
    values.update(overrides)
    return SimilarIncidentReference(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"incident_id": cast(IncidentId, "incident-old")}, "identity"),
        ({"service": ""}, "summary"),
        ({"root_cause_summary": cast(str, 1)}, "summary"),
        ({"outcome": ""}, "summary"),
        ({"outcome_summary": ""}, "summary"),
        ({"similarity": cast(float, 1)}, "score"),
        ({"similarity": float("nan")}, "score"),
        ({"similarity": -0.1}, "score"),
        ({"similarity": 1.1}, "score"),
        ({"historical_reference_only": False}, "historical reference"),
    ],
)
def test_similar_reference_rejects_authority_or_unbounded_fields(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        reference(**overrides)


class SearchStore:
    def __init__(self) -> None:
        self.queries: list[IncidentMemorySearchQuery] = []

    async def search(
        self, query: IncidentMemorySearchQuery
    ) -> tuple[SimilarIncidentReference, ...]:
        self.queries.append(query)
        return (reference(),)


@pytest.mark.anyio
async def test_retriever_authorizes_tenant_before_search() -> None:
    store = SearchStore()
    retriever = SimilarIncidentRetriever(store)
    query = search_query()
    viewer = Principal(ActorId("viewer-1"), query.tenant_id, frozenset({Role.VIEWER}))

    assert await retriever.search(viewer, query) == (reference(),)
    assert store.queries == [query]

    with pytest.raises(AuthenticationError):
        await retriever.search(None, query)
    with pytest.raises(AuthorizationError):
        await retriever.search(
            Principal(ActorId("viewer-2"), TenantId("tenant-2"), frozenset({Role.VIEWER})),
            query,
        )
    assert store.queries == [query]

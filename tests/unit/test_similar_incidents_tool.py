"""Versioned historical-reference-only similar-Incident tool tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from agentops_incident_commander.application import ToolAdapterContext, ToolCallRequest, ToolGateway
from agentops_incident_commander.application.tool_gateway import (
    ToolPayloadValidationError,
    _validate_payload,
)
from agentops_incident_commander.domain import (
    MAX_SIMILAR_INCIDENT_RESULTS,
    ActorId,
    AuditEvent,
    AuthorizationError,
    CausationId,
    CorrelationId,
    IncidentId,
    IncidentMemorySearchQuery,
    InvalidDomainValueError,
    Permission,
    Principal,
    Role,
    SimilarIncidentReference,
    TenantId,
    ToolAccessClass,
    ToolCallId,
    ToolIdempotency,
    ToolRegistry,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.tool_adapters import (
    SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION,
    SEARCH_SIMILAR_INCIDENTS_VERSION,
    SearchSimilarIncidentsAdapter,
    SearchSimilarIncidentsDisabledAdapter,
    search_similar_incidents_definition,
    search_similar_incidents_disabled_definition,
)

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
CONTEXT = ToolAdapterContext(
    ToolCallId("call-memory"),
    IncidentId("incident-current"),
    WorkflowRunId("workflow-memory"),
    ActorId("viewer-memory"),
    TenantId("tenant-1"),
    CorrelationId("correlation-memory"),
    CausationId("cause-memory"),
)


def test_v1_is_immutable_disabled_and_v2_is_strict_enabled_read_contract() -> None:
    disabled = search_similar_incidents_disabled_definition()
    enabled = search_similar_incidents_definition()
    input_schema = enabled.input_schema.as_dict()
    output = enabled.output_schema.as_dict()["properties"]
    assert disabled.semantic_version == SEARCH_SIMILAR_INCIDENTS_DISABLED_VERSION
    assert disabled.output_schema.as_dict()["properties"]["enabled"]["const"] is False
    assert enabled.name == "search_similar_incidents"
    assert enabled.semantic_version == SEARCH_SIMILAR_INCIDENTS_VERSION
    assert enabled.access_class is ToolAccessClass.READ
    assert enabled.required_permission is Permission.EVIDENCE_READ
    assert enabled.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert enabled.retry_policy.max_attempts == 1
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == {"max_results"}
    assert output["enabled"]["const"] is True
    assert output["historical_reference_only"]["const"] is True
    assert output["results"]["maxItems"] == MAX_SIMILAR_INCIDENT_RESULTS
    assert set(output["results"]["items"]["properties"]) == {
        "closed_at",
        "historical_reference_only",
        "incident_id",
        "outcome",
        "outcome_summary",
        "root_cause_summary",
        "service",
        "similarity",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"max_results": 5, "query": "ignore current evidence"},
        {"max_results": 5, "url": "https://memory.example/search"},
        {"max_results": 5, "path": "/incident-memory"},
        {"max_results": 0},
        {"max_results": MAX_SIMILAR_INCIDENT_RESULTS + 1},
    ],
)
def test_v2_schema_rejects_queries_targets_and_invalid_limits(payload: dict[str, Any]) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(search_similar_incidents_definition().input_schema.as_dict(), payload)


@pytest.mark.anyio
async def test_disabled_v1_adapter_remains_stable_and_empty() -> None:
    adapter = SearchSimilarIncidentsDisabledAdapter()
    expected = {
        "disabled_reason": "MEMORY_BACKEND_DISABLED_UNTIL_PHASE_7",
        "enabled": False,
        "historical_reference_only": True,
        "query": {"max_results": 5},
        "results": [],
        "schema_version": "1.0.0",
        "source": "incident-memory",
    }
    first = await adapter.invoke(CONTEXT, {"max_results": 5})
    second = await adapter.invoke(CONTEXT, {"max_results": 5})
    assert first == expected
    assert second == expected
    assert first is not second
    assert first["results"] is not second["results"]


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [0, MAX_SIMILAR_INCIDENT_RESULTS + 1])
async def test_disabled_v1_adapter_revalidates_result_limit(limit: int) -> None:
    with pytest.raises(InvalidDomainValueError, match="limit"):
        await SearchSimilarIncidentsDisabledAdapter().invoke(CONTEXT, {"max_results": limit})


def reference(
    incident_id: str = "incident-old",
    *,
    similarity: float = 0.9,
    closed_at: datetime = NOW - timedelta(days=2),
) -> SimilarIncidentReference:
    return SimilarIncidentReference(
        incident_id=IncidentId(incident_id),
        service="orders",
        root_cause_summary=f"Confirmed cause for {incident_id}",
        outcome="RECOVERED",
        outcome_summary="Rollback passed deterministic verification.",
        closed_at=closed_at,
        similarity=similarity,
    )


class QueryProvider:
    def __init__(self, replacement: object | None = None) -> None:
        self.replacement = replacement
        self.calls: list[dict[str, object]] = []

    async def query_for(
        self,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
        max_results: int,
        requested_at: datetime,
        max_age: timedelta,
    ) -> IncidentMemorySearchQuery:
        values = {
            "tenant_id": tenant_id,
            "current_incident_id": incident_id,
            "max_results": max_results,
            "requested_at": requested_at,
            "max_age": max_age,
        }
        self.calls.append(values)
        query = IncidentMemorySearchQuery(
            provider="agentops-mock",
            model="deterministic-sha256",
            model_version="1.0.0",
            content_schema_version="1.0.0",
            normalization_version="l2-v1",
            vector=(1.0, 0.0),
            tenant_id=tenant_id,
            current_incident_id=incident_id,
            max_results=max_results,
            requested_at=requested_at,
            max_age=max_age,
        )
        return cast(IncidentMemorySearchQuery, self.replacement or query)


class SearchStore:
    def __init__(self, results: object) -> None:
        self.results = results
        self.queries: list[IncidentMemorySearchQuery] = []

    async def search(
        self, query: IncidentMemorySearchQuery
    ) -> tuple[SimilarIncidentReference, ...]:
        self.queries.append(query)
        return cast(tuple[SimilarIncidentReference, ...], self.results)


@pytest.mark.anyio
async def test_enabled_v2_adapter_uses_server_query_and_minimal_ordered_output() -> None:
    provider = QueryProvider()
    store = SearchStore(
        (reference("incident-a", similarity=1.0), reference("incident-b", similarity=0.8))
    )
    adapter = SearchSimilarIncidentsAdapter(
        provider, store, clock=lambda: NOW, max_age=timedelta(days=30)
    )
    result = await adapter.invoke(CONTEXT, {"max_results": 5})
    assert provider.calls == [
        {
            "tenant_id": TenantId("tenant-1"),
            "current_incident_id": IncidentId("incident-current"),
            "max_results": 5,
            "requested_at": NOW,
            "max_age": timedelta(days=30),
        }
    ]
    assert store.queries[0].vector == (1.0, 0.0)
    assert result["enabled"] is True
    assert result["schema_version"] == "2.0.0"
    assert [item["incident_id"] for item in result["results"]] == ["incident-a", "incident-b"]
    _validate_payload(search_similar_incidents_definition().output_schema.as_dict(), result)
    assert set(result["results"][0]) == {
        "closed_at",
        "historical_reference_only",
        "incident_id",
        "outcome",
        "outcome_summary",
        "root_cause_summary",
        "service",
        "similarity",
    }


@pytest.mark.parametrize("max_age", [timedelta(0), timedelta(days=3651)])
def test_enabled_adapter_rejects_invalid_freshness_configuration(max_age: timedelta) -> None:
    with pytest.raises(InvalidDomainValueError, match="freshness"):
        SearchSimilarIncidentsAdapter(QueryProvider(), SearchStore(()), max_age=max_age)


@pytest.mark.anyio
@pytest.mark.parametrize("limit", [True, 0, MAX_SIMILAR_INCIDENT_RESULTS + 1])
async def test_enabled_adapter_revalidates_direct_call_limit(limit: int) -> None:
    with pytest.raises(InvalidDomainValueError, match="limit"):
        await SearchSimilarIncidentsAdapter(QueryProvider(), SearchStore(())).invoke(
            CONTEXT, {"max_results": limit}
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field", ["tenant_id", "current_incident_id", "max_results", "requested_at", "max_age"]
)
async def test_enabled_adapter_rejects_server_query_scope_drift(field: str) -> None:
    base = await QueryProvider().query_for(
        tenant_id=CONTEXT.tenant_id,
        incident_id=CONTEXT.incident_id,
        max_results=5,
        requested_at=NOW,
        max_age=timedelta(days=30),
    )
    changes: dict[str, object] = {
        "tenant_id": TenantId("tenant-other"),
        "current_incident_id": IncidentId("incident-other"),
        "max_results": 4,
        "requested_at": NOW - timedelta(seconds=1),
        "max_age": timedelta(days=29),
    }
    provider = QueryProvider(replace(base, **cast(Any, {field: changes[field]})))
    adapter = SearchSimilarIncidentsAdapter(
        provider, SearchStore(()), clock=lambda: NOW, max_age=timedelta(days=30)
    )
    with pytest.raises(InvalidDomainValueError, match="scope drifted"):
        await adapter.invoke(CONTEXT, {"max_results": 5})


@pytest.mark.anyio
async def test_enabled_adapter_rejects_untyped_server_query() -> None:
    adapter = SearchSimilarIncidentsAdapter(
        QueryProvider(cast(IncidentMemorySearchQuery, object())), SearchStore(()), clock=lambda: NOW
    )
    with pytest.raises(InvalidDomainValueError, match="scope drifted"):
        await adapter.invoke(CONTEXT, {"max_results": 5})


@pytest.mark.anyio
@pytest.mark.parametrize(
    "results",
    [
        [],
        tuple(reference(f"incident-{index}") for index in range(6)),
        (cast(SimilarIncidentReference, object()),),
        (reference("incident-current"),),
        (reference("incident-a"), reference("incident-a")),
        (reference("incident-low", similarity=0.5), reference("incident-high", similarity=0.9)),
    ],
)
async def test_enabled_adapter_rejects_invalid_backend_results(results: object) -> None:
    adapter = SearchSimilarIncidentsAdapter(
        QueryProvider(), SearchStore(results), clock=lambda: NOW, max_age=timedelta(days=30)
    )
    with pytest.raises(InvalidDomainValueError, match="backend result"):
        await adapter.invoke(CONTEXT, {"max_results": 5})


class AuditWriter:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def append(self, event: AuditEvent) -> object:
        self.events.append(event)
        return None


class DeniedPrincipal:
    actor_id = ActorId("denied-memory")
    tenant_id = TenantId("tenant-1")
    permissions: frozenset[Permission] = frozenset()


def tool_call(principal: Principal) -> ToolCallRequest:
    return ToolCallRequest.from_mapping(
        call_id=CONTEXT.call_id,
        tool_name="search_similar_incidents",
        tool_version=SEARCH_SIMILAR_INCIDENTS_VERSION,
        incident_id=CONTEXT.incident_id,
        workflow_run_id=CONTEXT.workflow_run_id,
        principal=principal,
        correlation_id=CONTEXT.correlation_id,
        causation_id=CONTEXT.causation_id,
        arguments={"max_results": 5},
    )


def gateway(adapter: SearchSimilarIncidentsAdapter, audit: AuditWriter) -> ToolGateway:
    definition = search_similar_incidents_definition()
    return ToolGateway(
        ToolRegistry((definition,)),
        {definition.identity: adapter},
        audit,
        clock=lambda: NOW,
        audit_id_factory=lambda: f"audit-memory-{len(audit.events)}",
    )


@pytest.mark.anyio
async def test_gateway_audits_permission_denial_before_memory_backend_access() -> None:
    provider = QueryProvider()
    audit = AuditWriter()
    adapter = SearchSimilarIncidentsAdapter(provider, SearchStore(()), clock=lambda: NOW)
    with pytest.raises(AuthorizationError, match="lacks permission"):
        await gateway(adapter, audit).invoke_diagnosis(
            tool_call(cast(Principal, DeniedPrincipal()))
        )
    assert provider.calls == []
    assert [event.type for event in audit.events] == ["tool.call_rejected"]


@pytest.mark.anyio
async def test_gateway_dispatches_enabled_v2_with_tenant_context_and_audit() -> None:
    provider = QueryProvider()
    audit = AuditWriter()
    adapter = SearchSimilarIncidentsAdapter(
        provider, SearchStore((reference(),)), clock=lambda: NOW
    )
    principal = Principal(CONTEXT.actor_id, CONTEXT.tenant_id, frozenset({Role.VIEWER}))
    result = await gateway(adapter, audit).invoke_diagnosis(tool_call(principal))
    assert result.result()["results"][0]["historical_reference_only"] is True
    assert provider.calls[0]["tenant_id"] == CONTEXT.tenant_id
    assert [event.type for event in audit.events] == ["tool.call_started", "tool.call_succeeded"]

"""Versioned get_service_topology definition and adapter tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from agentops_incident_commander.application import ToolAdapterContext
from agentops_incident_commander.application.tool_gateway import (
    ToolPayloadValidationError,
    _validate_payload,
)
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    IncidentId,
    InvalidDomainValueError,
    Permission,
    TenantId,
    ToolAccessClass,
    ToolCallId,
    ToolIdempotency,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.tool_adapters import (
    GET_SERVICE_TOPOLOGY_VERSION,
    MAX_TOPOLOGY_DEPTH,
    MAX_TOPOLOGY_EDGES,
    MAX_TOPOLOGY_NODES,
    GetServiceTopologyAdapter,
    TopologyBackendEdge,
    TopologyBackendNode,
    TopologyBackendResult,
    TopologyNodeKind,
    TopologyQuery,
    TopologyRelation,
    get_service_topology_definition,
)

CONTEXT = ToolAdapterContext(
    ToolCallId("call-topology"),
    IncidentId("incident-topology"),
    WorkflowRunId("workflow-topology"),
    ActorId("viewer-topology"),
    TenantId("tenant-1"),
    CorrelationId("correlation-topology"),
    CausationId("cause-topology"),
)


def arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "environment": "production",
        "max_depth": 3,
        "root_service": "gateway",
    }
    value.update(overrides)
    return value


def node(
    service: str,
    *,
    environment: str = "production",
    kind: TopologyNodeKind = TopologyNodeKind.SERVICE,
) -> TopologyBackendNode:
    return TopologyBackendNode(service, environment, kind)


def edge(
    source: str,
    target: str,
    relation: TopologyRelation = TopologyRelation.CALLS,
) -> TopologyBackendEdge:
    return TopologyBackendEdge(source, target, relation)


class Backend:
    def __init__(self, result: TopologyBackendResult) -> None:
        self.result = result
        self.queries: list[TopologyQuery] = []

    async def get_topology(self, query: TopologyQuery) -> TopologyBackendResult:
        self.queries.append(query)
        return self.result


def graph() -> TopologyBackendResult:
    return TopologyBackendResult(
        (
            node("gateway", kind=TopologyNodeKind.GATEWAY),
            node("orders"),
            node("payments"),
        ),
        (edge("gateway", "orders", TopologyRelation.ROUTES), edge("orders", "payments")),
    )


def test_topology_definition_is_strict_read_only_and_bounded() -> None:
    definition = get_service_topology_definition()
    schema = definition.input_schema.as_dict()
    assert definition.name == "get_service_topology"
    assert definition.semantic_version == GET_SERVICE_TOPOLOGY_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert schema["additionalProperties"] is False
    assert not {"query", "url", "path", "selector"} & set(schema["properties"])
    output = definition.output_schema.as_dict()["properties"]
    assert output["nodes"]["maxItems"] == 100
    assert output["edges"]["maxItems"] == 500


@pytest.mark.parametrize(
    "payload",
    [
        arguments(query="MATCH (n) RETURN n"),
        arguments(root_service="https://catalog.example/graph"),
        arguments(path="/etc/service-catalog"),
    ],
)
def test_topology_schema_rejects_raw_queries_and_targets(payload: dict[str, Any]) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(get_service_topology_definition().input_schema.as_dict(), payload)


def test_topology_backend_types_enforce_bounds_and_values() -> None:
    assert graph().nodes[0].service == "gateway"
    with pytest.raises(InvalidDomainValueError, match="node limit"):
        TopologyBackendResult((node("service"),) * (MAX_TOPOLOGY_NODES + 1), ())
    with pytest.raises(InvalidDomainValueError, match="edge limit"):
        TopologyBackendResult((), (edge("a", "b"),) * (MAX_TOPOLOGY_EDGES + 1))
    with pytest.raises(InvalidDomainValueError, match="service"):
        node("")
    with pytest.raises(InvalidDomainValueError, match="kind"):
        node("orders", kind=cast(TopologyNodeKind, "SERVICE"))
    with pytest.raises(InvalidDomainValueError, match="source"):
        edge("", "orders")
    with pytest.raises(InvalidDomainValueError, match="self edges"):
        edge("orders", "orders")
    with pytest.raises(InvalidDomainValueError, match="relation"):
        edge("orders", "payments", cast(TopologyRelation, "CALLS"))


@pytest.mark.anyio
async def test_topology_adapter_returns_versioned_connected_graph() -> None:
    backend = Backend(graph())
    result = await GetServiceTopologyAdapter(backend).invoke(CONTEXT, arguments())
    assert result == {
        "edges": [
            {"relation": "ROUTES", "source": "gateway", "target": "orders"},
            {"relation": "CALLS", "source": "orders", "target": "payments"},
        ],
        "nodes": [
            {"environment": "production", "kind": "GATEWAY", "service": "gateway"},
            {"environment": "production", "kind": "SERVICE", "service": "orders"},
            {"environment": "production", "kind": "SERVICE", "service": "payments"},
        ],
        "query": arguments(),
        "schema_version": "1.0.0",
        "source": "service-catalog",
    }
    assert backend.queries == [TopologyQuery("gateway", "production", 3)]


@pytest.mark.anyio
@pytest.mark.parametrize("depth", [0, MAX_TOPOLOGY_DEPTH + 1])
async def test_topology_adapter_rejects_invalid_depth(depth: int) -> None:
    backend = Backend(graph())
    with pytest.raises(InvalidDomainValueError, match="depth"):
        await GetServiceTopologyAdapter(backend).invoke(CONTEXT, arguments(max_depth=depth))
    assert backend.queries == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("result", "overrides", "message"),
    [
        (
            TopologyBackendResult((node("orders"), node("gateway")), (edge("gateway", "orders"),)),
            {},
            "nodes are not ordered",
        ),
        (
            TopologyBackendResult(
                (node("gateway"), node("orders")),
                (edge("orders", "gateway"), edge("gateway", "orders")),
            ),
            {},
            "edges are not ordered",
        ),
        (TopologyBackendResult((node("gateway"), node("gateway")), ()), {}, "duplicate nodes"),
        (
            TopologyBackendResult(
                (node("gateway"), node("orders")),
                (edge("gateway", "orders"), edge("gateway", "orders")),
            ),
            {},
            "duplicate edges",
        ),
        (
            TopologyBackendResult(
                (
                    TopologyBackendNode("gateway", "production", TopologyNodeKind.GATEWAY),
                    node("gateway"),
                ),
                (),
            ),
            {},
            "service names",
        ),
        (TopologyBackendResult((node("orders"),), ()), {}, "root service"),
        (TopologyBackendResult((node("gateway", environment="staging"),), ()), {}, "environment"),
        (
            TopologyBackendResult((node("gateway"), node("orders")), (edge("gateway", "missing"),)),
            {},
            "unknown node",
        ),
        (TopologyBackendResult((node("gateway"), node("orders")), ()), {}, "disconnected"),
        (
            graph(),
            {"max_depth": 1},
            "requested depth",
        ),
    ],
)
async def test_topology_adapter_rejects_backend_contract_violations(
    result: TopologyBackendResult, overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(result)
    with pytest.raises(InvalidDomainValueError, match=message):
        await GetServiceTopologyAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert len(backend.queries) == 1

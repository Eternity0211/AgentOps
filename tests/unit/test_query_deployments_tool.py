"""Versioned query_deployments definition and adapter tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

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
    MAX_DEPLOYMENT_QUERY_RECORDS,
    MAX_DEPLOYMENT_QUERY_WINDOW,
    QUERY_DEPLOYMENTS_VERSION,
    DeploymentBackendRecord,
    DeploymentBackendResult,
    DeploymentQuery,
    QueryDeploymentsAdapter,
    query_deployments_definition,
)

NOW = datetime(2026, 10, 4, 11, 0, tzinfo=UTC)
CONTEXT = ToolAdapterContext(
    ToolCallId("call-deployments"),
    IncidentId("incident-deployments"),
    WorkflowRunId("workflow-deployments"),
    ActorId("viewer-deployments"),
    TenantId("tenant-1"),
    CorrelationId("correlation-deployments"),
    CausationId("cause-deployments"),
)


def arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "end": (NOW + timedelta(days=1)).isoformat(),
        "environment": "production",
        "limit": 100,
        "service": "orders",
        "start": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def record(
    *,
    deployment_id: str = "deploy-1",
    service: str = "orders",
    environment: str = "production",
    version: str = "2.0.0",
    occurred_at: datetime = NOW + timedelta(hours=1),
) -> DeploymentBackendRecord:
    return DeploymentBackendRecord(deployment_id, service, environment, version, occurred_at)


class Backend:
    def __init__(self, result: DeploymentBackendResult) -> None:
        self.result = result
        self.queries: list[DeploymentQuery] = []

    async def query_range(self, query: DeploymentQuery) -> DeploymentBackendResult:
        self.queries.append(query)
        return self.result


def test_query_deployments_definition_is_strict_read_only_and_bounded() -> None:
    definition = query_deployments_definition()
    schema = definition.input_schema.as_dict()
    assert definition.name == "query_deployments"
    assert definition.semantic_version == QUERY_DEPLOYMENTS_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert definition.retry_policy.max_attempts == 3
    assert schema["additionalProperties"] is False
    assert not {"query", "url", "path", "command"} & set(schema["properties"])
    assert definition.output_schema.as_dict()["properties"]["records"]["maxItems"] == 500


@pytest.mark.parametrize(
    "payload",
    [
        arguments(query="SELECT * FROM deployments"),
        arguments(service="https://deployments.example/api"),
        arguments(path="/var/run/deployments"),
    ],
)
def test_query_deployments_schema_rejects_raw_queries_and_targets(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(query_deployments_definition().input_schema.as_dict(), payload)


def test_deployment_backend_types_enforce_bounds() -> None:
    assert DeploymentBackendResult((record(),), True).records_dropped == 0
    with pytest.raises(InvalidDomainValueError, match="record limit"):
        DeploymentBackendResult((record(),) * (MAX_DEPLOYMENT_QUERY_RECORDS + 1), True)
    with pytest.raises(InvalidDomainValueError, match="completeness"):
        DeploymentBackendResult((), 1)  # type: ignore[arg-type]
    for dropped in (-1, True, 1.5):
        with pytest.raises(InvalidDomainValueError, match="dropped count"):
            DeploymentBackendResult((), True, dropped)  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="deployment_id"):
        record(deployment_id="")
    with pytest.raises(InvalidDomainValueError, match="service"):
        record(service="orders\nforged")
    with pytest.raises(InvalidDomainValueError, match="environment"):
        record(environment="x" * 33)
    with pytest.raises(InvalidDomainValueError, match="version"):
        record(version="\x00")


@pytest.mark.anyio
async def test_query_deployments_adapter_returns_versioned_scoped_result() -> None:
    backend = Backend(DeploymentBackendResult((record(),), True, 2))
    result = await QueryDeploymentsAdapter(backend).invoke(CONTEXT, arguments())
    assert result == {
        "complete_window": True,
        "query": arguments(),
        "records": [
            {
                "deployment_id": "deploy-1",
                "environment": "production",
                "occurred_at": (NOW + timedelta(hours=1)).isoformat(),
                "service": "orders",
                "version": "2.0.0",
            }
        ],
        "records_dropped": 2,
        "schema_version": "1.0.0",
        "source": "deployment-registry",
    }
    assert backend.queries == [
        DeploymentQuery(
            "orders",
            "production",
            NOW.isoformat(),
            (NOW + timedelta(days=1)).isoformat(),
            100,
        )
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"start": "invalid"}, "timestamps"),
        ({"end": NOW.isoformat()}, "window"),
        (
            {"end": (NOW + MAX_DEPLOYMENT_QUERY_WINDOW + timedelta(seconds=1)).isoformat()},
            "window",
        ),
        ({"limit": 0}, "limit"),
        ({"limit": MAX_DEPLOYMENT_QUERY_RECORDS + 1}, "limit"),
    ],
)
async def test_query_deployments_adapter_rejects_invalid_queries(
    overrides: Mapping[str, Any], message: str
) -> None:
    backend = Backend(DeploymentBackendResult((), True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryDeploymentsAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert backend.queries == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("records", "overrides", "message"),
    [
        ((record(service="payments"),), {}, "scope"),
        ((record(environment="staging"),), {}, "scope"),
        ((record(occurred_at=NOW - timedelta(seconds=1)),), {}, "out-of-window"),
        (
            (
                record(deployment_id="deploy-2", occurred_at=NOW + timedelta(hours=2)),
                record(occurred_at=NOW + timedelta(hours=1)),
            ),
            {},
            "time ordered",
        ),
        ((record(), record()), {}, "deployment ID"),
        (
            (record(), record(deployment_id="deploy-2")),
            {},
            "timestamp",
        ),
        (
            (record(), record(deployment_id="deploy-2", occurred_at=NOW + timedelta(hours=2))),
            {"limit": 1},
            "requested limit",
        ),
    ],
)
async def test_query_deployments_adapter_rejects_backend_contract_violations(
    records: tuple[DeploymentBackendRecord, ...],
    overrides: Mapping[str, Any],
    message: str,
) -> None:
    backend = Backend(DeploymentBackendResult(records, True))
    with pytest.raises(InvalidDomainValueError, match=message):
        await QueryDeploymentsAdapter(backend).invoke(CONTEXT, arguments(**overrides))
    assert len(backend.queries) == 1

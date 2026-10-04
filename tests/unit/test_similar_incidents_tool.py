"""Disabled Phase 4 search_similar_incidents contract tests."""

from __future__ import annotations

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
    ToolAccessClass,
    ToolCallId,
    ToolIdempotency,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.tool_adapters import (
    MAX_SIMILAR_INCIDENT_RESULTS,
    SEARCH_SIMILAR_INCIDENTS_VERSION,
    SearchSimilarIncidentsDisabledAdapter,
    search_similar_incidents_definition,
)

CONTEXT = ToolAdapterContext(
    ToolCallId("call-memory"),
    IncidentId("incident-current"),
    WorkflowRunId("workflow-memory"),
    ActorId("viewer-memory"),
    CorrelationId("correlation-memory"),
    CausationId("cause-memory"),
)


def test_similar_incidents_definition_is_strict_read_only_and_disabled_safe() -> None:
    definition = search_similar_incidents_definition()
    input_schema = definition.input_schema.as_dict()
    output = definition.output_schema.as_dict()["properties"]
    assert definition.name == "search_similar_incidents"
    assert definition.semantic_version == SEARCH_SIMILAR_INCIDENTS_VERSION
    assert definition.access_class is ToolAccessClass.READ
    assert definition.required_permission is Permission.EVIDENCE_READ
    assert definition.idempotency is ToolIdempotency.NOT_APPLICABLE
    assert definition.retry_policy.max_attempts == 1
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["properties"]) == {"max_results"}
    assert output["enabled"]["const"] is False
    assert output["historical_reference_only"]["const"] is True
    assert output["results"]["maxItems"] == MAX_SIMILAR_INCIDENT_RESULTS


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
def test_similar_incidents_schema_rejects_queries_targets_and_invalid_limits(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(search_similar_incidents_definition().input_schema.as_dict(), payload)


@pytest.mark.anyio
async def test_disabled_adapter_returns_stable_empty_historical_reference_result() -> None:
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
async def test_disabled_adapter_revalidates_result_limit(limit: int) -> None:
    with pytest.raises(InvalidDomainValueError, match="limit"):
        await SearchSimilarIncidentsDisabledAdapter().invoke(CONTEXT, {"max_results": limit})

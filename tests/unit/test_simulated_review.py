"""Simulated review cannot infer missing report bindings."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from evaluation.simulated_review import review_diagnosis

from agentops_incident_commander.domain import ActorId, IncidentId, Principal, Role, TenantId


@pytest.mark.parametrize("missing", [False, True])
def test_simulated_review_rejects_missing_or_wrong_workflow(missing: bool) -> None:
    class Reports:
        async def latest(self, **kwargs: Any) -> Any:
            return (
                None if missing else SimpleNamespace(workflow_run_id=SimpleNamespace(value="other"))
            )

    principal = Principal(ActorId("viewer"), TenantId("tenant"), frozenset({Role.VIEWER}))
    result = asyncio.run(
        review_diagnosis(
            Reports(),
            cast(Any, None),
            cast(Any, None),
            cast(Any, None),
            principal=principal,
            incident=IncidentId("incident"),
            workflow_id="workflow",
        )
    )
    assert result["task_successes"] == 0 and result["required_tasks"] == 1
    assert result["approval_decided"] is False and result["human_time_saved"] is None

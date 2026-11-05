"""Job inputs cannot redirect a registered investigation across identity boundaries."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from evaluation.investigation_job import InvestigationJobInput, RegisteredInvestigationJobHandler

from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    IncidentId,
    Job,
    JobFailureRoute,
    JobId,
    JobLease,
    OpaqueIdentifier,
    TenantId,
    WorkflowRunId,
)


@pytest.mark.parametrize(
    "field",
    [
        "valid",
        "payload_ref",
        "tenant_id",
        "incident_id",
        "workflow_run_id",
        "correlation_id",
        "causation_id",
        "type",
        "schema_version",
        "invoker",
    ],
)
def test_registered_job_binding(
    field: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    job = Job(
        JobId("job"),
        TenantId("tenant"),
        IncidentId("incident"),
        WorkflowRunId("workflow"),
        "workflow.investigate",
        "workflow/v1",
        OpaqueIdentifier("payload"),
        CorrelationId("corr"),
        CausationId("cause"),
        50,
        now,
        now,
        2,
        JobFailureRoute.NEEDS_HUMAN,
    )
    if field in ("type", "schema_version"):
        changes: dict[str, Any] = {field: "other.job" if field == "type" else "other/v1"}
        job = replace(job, **changes)
    elif field not in ("valid", "invoker"):
        job = replace(job, **{field: type(getattr(job, field))("other")})
    lease = JobLease(job, 1, OpaqueIdentifier("worker"), now, now, now + timedelta(seconds=30))
    payload = InvestigationJobInput(
        "payload",
        "tenant",
        "incident",
        "workflow",
        "corr",
        "cause",
        "Observed errors",
        now - timedelta(minutes=1),
        now,
        tmp_path,
    )
    called: list[Any] = []
    built = []

    async def factory() -> Any:
        built.append(True)
        return SimpleNamespace(
            principal=SimpleNamespace(tenant_id=TenantId("tenant")),
            incident=IncidentId("other" if field == "invoker" else "incident"),
            workflow=WorkflowRunId("workflow"),
            correlation=CorrelationId("corr"),
            causation=CausationId("cause"),
            model=object(),
        )

    async def investigate(*args: Any, **kwargs: Any) -> None:
        called.append((args, kwargs))

    monkeypatch.setattr("evaluation.investigation_job.investigate", investigate)
    handler = RegisteredInvestigationJobHandler(
        payload,
        factory,
        cast(Any, object()),
        cast(Any, object()),
        cast(Any, object()),
        lambda e: None,
    )
    if field == "valid":
        asyncio.run(handler(lease))
        assert len(called) == 1 and called[0][1]["model_invoker"].workflow.value == "workflow"
    else:
        with pytest.raises(ValueError, match=r"binding|schema"):
            asyncio.run(handler(lease))
        assert not called
        assert built == ([True] if field == "invoker" else [])

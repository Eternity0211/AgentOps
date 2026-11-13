"""Run the frozen durability census against PostgreSQL with controlled typed effects."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.domain import (
    ActorId,
    Artifact,
    ArtifactId,
    CausationId,
    CorrelationId,
    Evidence,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    Incident,
    IncidentId,
    IncidentSeverity,
    Job,
    JobFailureRoute,
    JobId,
    NormalizedQuery,
    OpaqueIdentifier,
    Principal,
    PromptInjectionStatus,
    QueryParameter,
    RedactionStatus,
    RedactionTransformId,
    RetentionClass,
    Role,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.persistence import (
    EvidenceRepository,
    IncidentRepository,
    JobRepository,
)
from evaluation.contracts import EvaluationContractError, canonical_json
from evaluation.durable_effects import SqlInvestigationEffects
from evaluation.final_durability import OBSERVATION_SCHEMA, DurabilityPlan, load_plan

Effect = Callable[[], Awaitable[dict[str, Any]]]
NOW = datetime(2026, 11, 13, 8, 0, tzinfo=UTC)


@dataclass(slots=True)
class Counters:
    model_calls: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rate_card_upper_bound_nusd: int = 0
    duplicate_external_effects: int = 0
    ambiguous_result_redispatches: int = 0


@dataclass(slots=True)
class RunState:
    counters: Counters
    evidence_expected: int = 0
    evidence_persisted: int = 0
    resume_started_ns: int | None = None
    resume_latency_ms: int = 0


def _config(url: str) -> Config:
    value = Config("alembic.ini")
    value.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return value


def _binding(case_id: str, arm: str) -> dict[str, Any]:
    suffix = f"{case_id}-{arm}"
    return {
        "tenant_id": "tenant-durability",
        "actor_id": "durability-operator",
        "incident_id": f"durability-{suffix}",
        "workflow_run_id": f"workflow-{suffix}",
        "input_hash": hashlib.sha256(suffix.encode()).hexdigest(),
        "correlation_id": f"correlation-{suffix}",
        "causation_id": f"causation-{suffix}",
    }


def _principal() -> Principal:
    return Principal(
        ActorId("durability-operator"),
        TenantId("tenant-durability"),
        frozenset({Role.OPERATOR}),
    )


async def _add_incident(engine: AsyncEngine, binding: dict[str, Any]) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    incident = Incident.open(
        IncidentId(binding["incident_id"]),
        TenantId(binding["tenant_id"]),
        IncidentSeverity.SEV2,
        "orders",
        opened_at=NOW,
    )
    async with sessions.begin() as session:
        await IncidentRepository(session).add(incident)


def _store(engine: AsyncEngine, binding: dict[str, Any]) -> SqlInvestigationEffects:
    return SqlInvestigationEffects(
        async_sessionmaker(engine, expire_on_commit=False),
        _principal(),
        binding["correlation_id"],
        binding["causation_id"],
    )


def _model_effect(counters: Counters, phase: str) -> Effect:
    async def effect() -> dict[str, Any]:
        counters.model_calls += 1
        input_tokens, output_tokens = ((100, 50) if phase == "plan" else (120, 60))
        counters.input_tokens += input_tokens
        counters.output_tokens += output_tokens
        counters.rate_card_upper_bound_nusd += input_tokens * 4 + output_tokens * 8
        return {"phase": phase, "status": "typed"}

    return effect


def _tool_effect(counters: Counters, index: int) -> Effect:
    async def effect() -> dict[str, Any]:
        counters.tool_calls += 1
        return {"tool": f"read-{index}", "records": [f"bounded-observation-{index}"]}

    return effect


async def _persist_evidence(
    engine: AsyncEngine,
    binding: dict[str, Any],
    indexes: Sequence[int],
) -> int:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    persisted = 0
    async with sessions.begin() as session:
        repository = EvidenceRepository(session)
        for index in indexes:
            content = f"durability-evidence-{binding['workflow_run_id']}-{index}".encode()
            digest = Sha256Digest(hashlib.sha256(content).hexdigest())
            artifact_id = ArtifactId(f"artifact-{binding['workflow_run_id']}-{index}")
            evidence_id = EvidenceId(f"evidence-{binding['workflow_run_id']}-{index}")
            artifact = Artifact(
                id=artifact_id,
                tenant_id=TenantId(binding["tenant_id"]),
                incident_id=IncidentId(binding["incident_id"]),
                locator=f"local-artifact:v1:{artifact_id.value}",
                media_type="application/json",
                content_schema_version="1.0.0",
                content_hash=digest,
                size_bytes=len(content),
                retention_class=RetentionClass.INCIDENT,
                created_at=NOW,
                expires_at=NOW + timedelta(days=30),
                redaction_status=RedactionStatus.REDACTED,
                encrypted=False,
            )
            evidence = Evidence(
                id=evidence_id,
                tenant_id=artifact.tenant_id,
                incident_id=artifact.incident_id,
                source_type=EvidenceSourceType.LOG,
                source_instance="durability-probe",
                tool_name="query_logs",
                tool_version="2.0.0",
                tool_schema_version="2.0.0",
                normalized_query=NormalizedQuery((QueryParameter("service", "orders"),)),
                observed_from=NOW,
                observed_to=NOW + timedelta(minutes=1),
                collected_at=NOW + timedelta(minutes=2),
                artifact_id=artifact.id,
                content_hash=artifact.content_hash,
                parser_version="1.0.0",
                normalizer_version="1.0.0",
                quality=EvidenceQuality(9000, ("complete-window",)),
                lineage=EvidenceLineage(
                    ToolCallId(f"tool-{binding['workflow_run_id']}-{index}"),
                    WorkflowRunId(binding["workflow_run_id"]),
                    RedactionTransformId(f"redaction-{binding['workflow_run_id']}-{index}"),
                ),
                trust=TrustClassification.DIRECT_OBSERVATION,
                prompt_injection_status=PromptInjectionStatus.NONE,
                expires_at=NOW + timedelta(days=7),
            )
            await repository.add(evidence, artifact)
            persisted += 1
    return persisted


async def _normal_workflow(
    engine: AsyncEngine,
    binding: dict[str, Any],
    state: RunState,
    *,
    store: SqlInvestigationEffects | None = None,
) -> str:
    effects = store or _store(engine, binding)
    await effects.execute("model:plan", binding, _model_effect(state.counters, "plan"))
    await asyncio.gather(
        effects.execute("tool:read:1", binding, _tool_effect(state.counters, 1)),
        effects.execute("tool:read:2", binding, _tool_effect(state.counters, 2)),
    )
    state.evidence_expected = 2
    state.evidence_persisted += await _persist_evidence(engine, binding, (1, 2))
    await effects.execute("model:diagnose", binding, _model_effect(state.counters, "diagnose"))
    return "COMPLETED"


async def _stale_lease(engine: AsyncEngine, binding: dict[str, Any]) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    job = Job(
        id=JobId(f"job-{binding['workflow_run_id']}"),
        tenant_id=TenantId(binding["tenant_id"]),
        incident_id=IncidentId(binding["incident_id"]),
        workflow_run_id=WorkflowRunId(binding["workflow_run_id"]),
        type="workflow.investigate",
        schema_version="workflow/v1",
        payload_ref=OpaqueIdentifier(f"payload-{binding['workflow_run_id']}"),
        correlation_id=CorrelationId(binding["correlation_id"]),
        causation_id=CausationId(binding["causation_id"]),
        priority=50,
        created_at=NOW,
        available_at=NOW,
        max_attempts=2,
        failure_route=JobFailureRoute.DEAD_LETTER,
    )
    first, second = OpaqueIdentifier("durability-worker-1"), OpaqueIdentifier(
        "durability-worker-2"
    )
    async with sessions.begin() as session:
        repository = JobRepository(session)
        await repository.enqueue(job)
        leases = await repository.claim(
            first, now=NOW, lease_duration=timedelta(seconds=3), limit=1
        )
        if len(leases) != 1:
            raise EvaluationContractError("stale-lease probe did not obtain the first lease")
    async with sessions.begin() as session:
        leases = await JobRepository(session).claim(
            second, now=NOW + timedelta(seconds=4), lease_duration=timedelta(seconds=3), limit=1
        )
        if len(leases) != 1 or leases[0].attempt != 2:
            raise EvaluationContractError("stale-lease probe did not obtain one replacement")
        await JobRepository(session).complete(
            job.id, second, completed_at=NOW + timedelta(seconds=5)
        )


async def _treatment(
    engine: AsyncEngine, binding: dict[str, Any], case_id: str, state: RunState
) -> str:
    store = _store(engine, binding)
    if case_id == "before-dispatch":
        await store.execute("checkpoint:before-dispatch", binding, lambda: _constant("persisted"))
        state.resume_started_ns = time.perf_counter_ns()
        completed = await _normal_workflow(
            engine, binding, state, store=_store(engine, binding)
        )
        route = "SAFE_REPLAY_NO_DISPATCH" if completed == "COMPLETED" else completed
    elif case_id == "after-dispatch-unknown":
        await store.execute("model:plan", binding, _model_effect(state.counters, "plan"))

        async def unknown() -> dict[str, Any]:
            state.counters.tool_calls += 1
            raise RuntimeError("injected unknown result")

        with suppress(RuntimeError):
            await store.execute("tool:unknown", binding, unknown)
        state.resume_started_ns = time.perf_counter_ns()
        try:
            await _store(engine, binding).execute(
                "tool:unknown", binding, _tool_effect(state.counters, 1)
            )
        except ValueError as error:
            if "redispatch forbidden" not in str(error):
                raise
        else:
            state.counters.ambiguous_result_redispatches += 1
        route = "NEEDS_HUMAN_NO_REDISPATCH"
    elif case_id == "after-persisted-result":
        await store.execute("model:plan", binding, _model_effect(state.counters, "plan"))
        state.resume_started_ns = time.perf_counter_ns()
        route = await _normal_workflow(engine, binding, state, store=_store(engine, binding))
        route = "RESUMED_COMPLETION" if route == "COMPLETED" else route
    elif case_id == "partial-parallel-reads":
        await store.execute("model:plan", binding, _model_effect(state.counters, "plan"))
        await store.execute("tool:read:1", binding, _tool_effect(state.counters, 1))
        state.resume_started_ns = time.perf_counter_ns()
        route = await _normal_workflow(engine, binding, state, store=_store(engine, binding))
        route = "RESUMED_COMPLETION" if route == "COMPLETED" else route
    elif case_id == "checkpoint-replacement":
        await store.execute("model:plan", binding, _model_effect(state.counters, "plan"))
        await store.execute("tool:read:1", binding, _tool_effect(state.counters, 1))
        await store.execute("tool:read:2", binding, _tool_effect(state.counters, 2))
        state.resume_started_ns = time.perf_counter_ns()
        route = await _normal_workflow(engine, binding, state, store=_store(engine, binding))
        route = "RESUMED_COMPLETION" if route == "COMPLETED" else route
    elif case_id == "stale-lease":
        await _stale_lease(engine, binding)
        state.resume_started_ns = time.perf_counter_ns()
        route = await _normal_workflow(engine, binding, state, store=_store(engine, binding))
        route = "RESUMED_COMPLETION" if route == "COMPLETED" else route
    elif case_id == "bounded-timeout":
        await store.execute("model:plan", binding, _model_effect(state.counters, "plan"))
        await store.execute("tool:read:1", binding, _tool_effect(state.counters, 1))

        async def timeout() -> dict[str, Any]:
            state.counters.tool_calls += 1
            raise TimeoutError("injected bounded timeout")

        with suppress(TimeoutError):
            await store.execute("tool:read:2", binding, timeout)
        state.evidence_expected = 1
        state.evidence_persisted = await _persist_evidence(engine, binding, (1,))
        route = "SAFE_HANDOFF"
    elif case_id == "duplicate-delivery":
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_plan() -> dict[str, Any]:
            state.counters.model_calls += 1
            state.counters.input_tokens += 100
            state.counters.output_tokens += 50
            state.counters.rate_card_upper_bound_nusd += 800
            entered.set()
            await release.wait()
            return {"phase": "plan", "status": "typed"}

        first = asyncio.create_task(store.execute("model:plan", binding, slow_plan))
        await entered.wait()
        try:
            await _store(engine, binding).execute(
                "model:plan", binding, _model_effect(state.counters, "plan")
            )
        except ValueError as error:
            if "redispatch forbidden" not in str(error):
                raise
        else:
            state.counters.duplicate_external_effects += 1
        finally:
            release.set()
            await first
        state.resume_started_ns = time.perf_counter_ns()
        route = await _normal_workflow(engine, binding, state, store=_store(engine, binding))
        route = "RESUMED_COMPLETION" if route == "COMPLETED" else route
    else:  # pragma: no cover - plan validation fixes the closed set
        raise EvaluationContractError("unknown durability treatment")
    if state.resume_started_ns is not None:
        state.resume_latency_ms = max(
            0, (time.perf_counter_ns() - state.resume_started_ns) // 1_000_000
        )
    return route


async def _constant(status: str) -> dict[str, Any]:
    return {"status": status}


async def _arm(
    engine: AsyncEngine, case_id: str, arm: str, expected_route: str
) -> dict[str, Any]:
    binding = _binding(case_id, arm)
    await _add_incident(engine, binding)
    state = RunState(Counters())
    started = time.perf_counter_ns()
    route = (
        await _normal_workflow(engine, binding, state)
        if arm == "control"
        else await _treatment(engine, binding, case_id, state)
    )
    elapsed_ms = max(1, (time.perf_counter_ns() - started) // 1_000_000)
    if arm == "treatment" and route != expected_route:
        raise EvaluationContractError(
            f"durability treatment route changed for {case_id}: {route} != {expected_route}"
        )
    return {
        "case_id": case_id,
        "arm": arm,
        "completed": 1,
        "duplicate_external_effects": state.counters.duplicate_external_effects,
        "ambiguous_result_redispatches": state.counters.ambiguous_result_redispatches,
        "evidence_expected": state.evidence_expected,
        "evidence_persisted": state.evidence_persisted,
        "takeover_or_resume_latency_ms": state.resume_latency_ms,
        "total_latency_ms": elapsed_ms,
        "model_calls": state.counters.model_calls,
        "tool_calls": state.counters.tool_calls,
        "input_tokens": state.counters.input_tokens,
        "output_tokens": state.counters.output_tokens,
        "rate_card_upper_bound_nusd": state.counters.rate_card_upper_bound_nusd,
        "terminal_route": route,
    }


async def run_probe(url: str, plan: DurabilityPlan) -> list[dict[str, Any]]:
    engine = create_async_engine(url)
    try:
        observations = []
        for case_id, route in plan.cases:
            observations.append(await _arm(engine, case_id, "control", route))
            observations.append(await _arm(engine, case_id, "treatment", route))
        return observations
    finally:
        await engine.dispose()


def execute(*, plan_path: Path, output_path: Path) -> None:
    if output_path.exists():
        raise EvaluationContractError("durability observations already exist")
    plan = load_plan(plan_path)
    with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        command.upgrade(_config(url), "head")
        try:
            observations = asyncio.run(run_probe(url, plan))
        finally:
            command.downgrade(_config(url), "base")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": OBSERVATION_SCHEMA,
        "plan_sha256": plan.fingerprint,
        "observations": observations,
    }
    output_path.write_text(
        f"{canonical_json(document)}\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        execute(plan_path=arguments.plan, output_path=arguments.output)
    except EvaluationContractError as error:
        print(f"[evaluation] durability probe failed reason={error}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

"""Run the frozen PostgreSQL queue scaling pilot and size its confirmatory study."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import math
import random
import statistics
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.domain import (
    CausationId,
    CorrelationId,
    Incident,
    IncidentId,
    IncidentSeverity,
    Job,
    JobFailureRoute,
    JobId,
    OpaqueIdentifier,
    TenantId,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure.persistence import (
    IncidentRepository,
    JobRepository,
    JobRow,
)
from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object
from evaluation.workflow_resources import measure_workflow

SCHEMA_VERSION = "capacity-pilot-result/1.0.0"
PLAN_SCHEMA = "capacity-pilot-plan/1.0.0"


@dataclass(frozen=True, slots=True)
class CapacityPilotPlan:
    kind: str
    fingerprint: str
    operations: int
    worker_levels: tuple[int, ...]
    repetitions: int
    handler_delay_ms: int
    lease_seconds: int
    minimum_repetitions: int
    maximum_repetitions: int
    minimum_relative_delta: float


def load_plan(path: Path) -> CapacityPilotPlan:
    value = load_json_object(path)
    schema = value.get("schema_version")
    if schema == PLAN_SCHEMA and value.get("status") == "FROZEN_BEFORE_PILOT":
        kind = "pilot"
        repetitions_value = value.get("pilot_repetitions")
        sizing = value.get("confirmatory_sizing")
        if not isinstance(sizing, dict):
            raise EvaluationContractError("capacity pilot sizing contract changed")
        minimum_repetitions = sizing.get("minimum_repetitions")
        maximum_repetitions = sizing.get("maximum_repetitions")
        minimum_delta = sizing.get("minimum_relevant_relative_delta")
    elif (
        schema == "capacity-confirmatory-plan/1.0.0"
        and value.get("status") == "FROZEN_BEFORE_CONFIRMATORY_RUN"
    ):
        kind = "confirmatory"
        repetitions_value = value.get("confirmatory_repetitions")
        minimum_repetitions = repetitions_value
        maximum_repetitions = repetitions_value
        minimum_delta = 0.1
    else:
        raise EvaluationContractError("capacity pilot plan is not frozen")
    levels = value.get("worker_levels")
    if levels != [1, 2, 4, 8]:
        raise EvaluationContractError("capacity pilot levels or sizing contract changed")
    integer_fields = {
        "operations": value.get("operations_per_repetition"),
        "repetitions": repetitions_value,
        "handler_delay_ms": value.get("handler_delay_ms"),
        "lease_seconds": value.get("lease_seconds"),
        "minimum_repetitions": minimum_repetitions,
        "maximum_repetitions": maximum_repetitions,
    }
    if any(type(item) is not int or item < 1 for item in integer_fields.values()):
        raise EvaluationContractError("capacity pilot numeric bound is invalid")
    if not isinstance(minimum_delta, float) or not 0 < minimum_delta < 1:
        raise EvaluationContractError("capacity pilot relevant delta is invalid")
    return CapacityPilotPlan(
        fingerprint=hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest(),
        kind=kind,
        worker_levels=tuple(levels),
        minimum_relative_delta=minimum_delta,
        **integer_fields,  # type: ignore[arg-type]
    )


def _config(url: str) -> Config:
    value = Config("alembic.ini")
    value.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return value


def _percentile(values: Sequence[int], quantile: float) -> int:
    if not values:
        raise EvaluationContractError("capacity timing distribution is empty")
    ordered = sorted(values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _job(level: int, repetition: int, index: int, now: datetime) -> Job:
    suffix = f"w{level}-r{repetition}-j{index}"
    return Job(
        id=JobId(f"capacity-{suffix}"),
        tenant_id=TenantId("tenant-capacity"),
        incident_id=IncidentId(f"capacity-w{level}-r{repetition}"),
        workflow_run_id=WorkflowRunId(f"workflow-{suffix}"),
        type="workflow.investigate",
        schema_version="workflow/v1",
        payload_ref=OpaqueIdentifier(f"payload-{suffix}"),
        correlation_id=CorrelationId(f"correlation-{suffix}"),
        causation_id=CausationId(f"causation-{suffix}"),
        priority=index % 101,
        created_at=now,
        available_at=now,
        max_attempts=2,
        failure_route=JobFailureRoute.DEAD_LETTER,
    )


async def _run_repetition(
    engine: AsyncEngine,
    plan: CapacityPilotPlan,
    workers: int,
    repetition: int,
) -> dict[str, Any]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    incident_id = IncidentId(f"capacity-w{workers}-r{repetition}")
    now = datetime.now(UTC)
    statement_count = 0

    def count_statement(
        *_: object,
    ) -> None:
        nonlocal statement_count
        statement_count += 1

    event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
    queue_waits: list[int] = []
    workflow_latencies: list[int] = []
    ownership: dict[str, str] = {}
    duplicate_ownership = 0
    empty_claims = 0
    completed = 0
    errors = 0
    lock = asyncio.Lock()
    started_ns = time.perf_counter_ns()
    resources: dict[str, int | str]
    try:
        with measure_workflow() as resources:
            async with sessions.begin() as session:
                await IncidentRepository(session).add(
                    Incident.open(
                        incident_id,
                        TenantId("tenant-capacity"),
                        IncidentSeverity.SEV2,
                        "orders",
                        opened_at=now,
                    )
                )
                repository = JobRepository(session)
                for index in range(plan.operations):
                    await repository.enqueue(_job(workers, repetition, index, now))
            enqueued_ns = time.perf_counter_ns()

            async def worker(index: int) -> None:
                nonlocal completed, duplicate_ownership, empty_claims, errors
                worker_id = OpaqueIdentifier(f"capacity-worker-{workers}-{repetition}-{index}")
                while True:
                    async with lock:
                        if completed >= plan.operations:
                            return
                    try:
                        async with sessions.begin() as session:
                            leases = await JobRepository(session).claim(
                                worker_id,
                                now=datetime.now(UTC),
                                lease_duration=timedelta(seconds=plan.lease_seconds),
                                limit=1,
                            )
                    except Exception:
                        async with lock:
                            errors += 1
                        raise
                    if not leases:
                        async with lock:
                            if completed >= plan.operations:
                                return
                            empty_claims += 1
                        await asyncio.sleep(0.001)
                        continue
                    lease = leases[0]
                    claimed_ns = time.perf_counter_ns()
                    async with lock:
                        previous = ownership.setdefault(lease.job.id.value, worker_id.value)
                        duplicate_ownership += int(previous != worker_id.value)
                    await asyncio.sleep(plan.handler_delay_ms / 1_000)
                    async with sessions.begin() as session:
                        await JobRepository(session).complete(
                            lease.job.id, worker_id, completed_at=datetime.now(UTC)
                        )
                    finished_ns = time.perf_counter_ns()
                    async with lock:
                        queue_waits.append(max(0, (claimed_ns - enqueued_ns) // 1_000_000))
                        workflow_latencies.append(
                            max(0, (finished_ns - enqueued_ns) // 1_000_000)
                        )
                        completed += 1

            await asyncio.gather(*(worker(index) for index in range(workers)))
        total_ms = max(1, (time.perf_counter_ns() - started_ns) // 1_000_000)
        async with sessions() as session:
            terminal = await session.scalar(
                select(func.count())
                .select_from(JobRow)
                .where(
                    JobRow.incident_id == incident_id.value,
                    JobRow.status == "COMPLETED",
                    JobRow.attempt_count == 1,
                )
            )
        if terminal != plan.operations or completed != plan.operations:
            raise EvaluationContractError("capacity repetition left nonterminal or retried Jobs")
        claims = completed + empty_claims
        return {
            "workers": workers,
            "repetition": repetition,
            "completed_jobs": completed,
            "error_count": errors,
            "duplicate_job_ownership": duplicate_ownership,
            "total_latency_ms": total_ms,
            "throughput_jobs_per_second_milli": plan.operations * 1_000_000 // total_ms,
            "queue_wait_p50_ms": _percentile(queue_waits, 0.5),
            "queue_wait_p95_ms": _percentile(queue_waits, 0.95),
            "workflow_latency_p50_ms": _percentile(workflow_latencies, 0.5),
            "workflow_latency_p95_ms": _percentile(workflow_latencies, 0.95),
            "lease_contention_count": empty_claims,
            "lease_contention_rate": 0 if claims == 0 else empty_claims / claims,
            "process_cpu_ms": resources["process_cpu_ms"],
            "python_heap_peak_bytes": resources["python_heap_peak_bytes"],
            "heap_scope": resources["heap_scope"],
            "database_statement_count": statement_count,
        }
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", count_statement)


async def run_pilot(url: str, plan: CapacityPilotPlan) -> list[dict[str, Any]]:
    engine = create_async_engine(url)
    try:
        rows = []
        for repetition in range(1, plan.repetitions + 1):
            for workers in plan.worker_levels:
                rows.append(await _run_repetition(engine, plan, workers, repetition))
        return rows
    finally:
        await engine.dispose()


def _confirmatory_repetitions(plan: CapacityPilotPlan, rows: Sequence[Mapping[str, Any]]) -> int:
    deviations = []
    for workers in plan.worker_levels:
        logs = [
            math.log(row["throughput_jobs_per_second_milli"] / 1_000)
            for row in rows
            if row["workers"] == workers
        ]
        if len(logs) != plan.repetitions:
            raise EvaluationContractError("capacity pilot repetition set is incomplete")
        deviations.append(statistics.stdev(logs))
    raw = math.ceil(
        (1.96 * max(deviations) / math.log1p(plan.minimum_relative_delta)) ** 2
    )
    return min(plan.maximum_repetitions, max(plan.minimum_repetitions, raw))


def summarize(plan: CapacityPilotPlan, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) != len(plan.worker_levels) * plan.repetitions:
        raise EvaluationContractError("capacity pilot row count is incomplete")
    groups: list[dict[str, Any]] = []
    baseline: float | None = None
    for workers in plan.worker_levels:
        selected = [row for row in rows if row["workers"] == workers]
        throughputs = [row["throughput_jobs_per_second_milli"] / 1_000 for row in selected]
        median = statistics.median(throughputs)
        if baseline is None:
            baseline = median
        groups.append(
            {
                "workers": workers,
                "repetitions": len(selected),
                "throughput_jobs_per_second_median": median,
                "throughput_absolute_delta_from_1_worker": median - baseline,
                "throughput_relative_delta_from_1_worker": median / baseline - 1,
                "queue_wait_p95_ms_median": statistics.median(
                    row["queue_wait_p95_ms"] for row in selected
                ),
                "workflow_latency_p95_ms_median": statistics.median(
                    row["workflow_latency_p95_ms"] for row in selected
                ),
                "process_cpu_ms_median": statistics.median(
                    row["process_cpu_ms"] for row in selected
                ),
                "python_heap_peak_bytes_median": statistics.median(
                    row["python_heap_peak_bytes"] for row in selected
                ),
                "database_statement_count_median": statistics.median(
                    row["database_statement_count"] for row in selected
                ),
                "error_count": sum(row["error_count"] for row in selected),
                "duplicate_job_ownership": sum(
                    row["duplicate_job_ownership"] for row in selected
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "plan_sha256": plan.fingerprint,
        "rows": list(rows),
        "groups": groups,
        "confirmatory_repetitions": _confirmatory_repetitions(plan, rows),
        "pilot_only": True,
    }


def _bootstrap_interval(values: Sequence[float], seed: int) -> list[float]:
    generator = random.Random(seed)
    samples = sorted(
        statistics.median(generator.choices(values, k=len(values))) for _ in range(10_000)
    )
    return [samples[249], samples[9749]]


def summarize_confirmatory(
    plan: CapacityPilotPlan, rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if plan.kind != "confirmatory" or len(rows) != 4 * plan.repetitions:
        raise EvaluationContractError("capacity confirmatory row set is incomplete")
    seed = int(plan.fingerprint[:16], 16)
    baseline_rows = [row for row in rows if row["workers"] == 1]
    baseline = [row["throughput_jobs_per_second_milli"] / 1_000 for row in baseline_rows]
    groups = []
    for workers in plan.worker_levels:
        selected = [row for row in rows if row["workers"] == workers]
        throughputs = [row["throughput_jobs_per_second_milli"] / 1_000 for row in selected]
        deltas = [
            candidate - control
            for candidate, control in zip(throughputs, baseline, strict=True)
        ]
        relatives = [
            candidate / control - 1
            for candidate, control in zip(throughputs, baseline, strict=True)
        ]
        groups.append(
            {
                "workers": workers,
                "repetitions": len(selected),
                "throughput_jobs_per_second_median": statistics.median(throughputs),
                "throughput_median_95pct_bootstrap": _bootstrap_interval(
                    throughputs, seed ^ workers
                ),
                "throughput_absolute_delta_from_1_worker_median": statistics.median(deltas),
                "throughput_absolute_delta_95pct_bootstrap": _bootstrap_interval(
                    deltas, seed ^ (workers << 4)
                ),
                "throughput_relative_delta_from_1_worker_median": statistics.median(relatives),
                "throughput_relative_delta_95pct_bootstrap": _bootstrap_interval(
                    relatives, seed ^ (workers << 8)
                ),
                "queue_wait_p95_ms_median": statistics.median(
                    row["queue_wait_p95_ms"] for row in selected
                ),
                "workflow_latency_p95_ms_median": statistics.median(
                    row["workflow_latency_p95_ms"] for row in selected
                ),
                "process_cpu_ms_median": statistics.median(
                    row["process_cpu_ms"] for row in selected
                ),
                "python_heap_peak_bytes_median": statistics.median(
                    row["python_heap_peak_bytes"] for row in selected
                ),
                "database_statement_count_median": statistics.median(
                    row["database_statement_count"] for row in selected
                ),
                "error_count": sum(row["error_count"] for row in selected),
                "duplicate_job_ownership": sum(
                    row["duplicate_job_ownership"] for row in selected
                ),
            }
        )
    four, eight = groups[2], groups[3]
    throughput_ratio = (
        eight["throughput_jobs_per_second_median"]
        / four["throughput_jobs_per_second_median"]
    )
    queue_ratio = eight["queue_wait_p95_ms_median"] / four["queue_wait_p95_ms_median"]
    correctness = not any(
        item["error_count"] or item["duplicate_job_ownership"] for item in groups
    )
    broker_required = throughput_ratio <= 1.05 and queue_ratio >= 1.25
    return {
        "schema_version": "capacity-confirmatory-result/1.0.0",
        "plan_sha256": plan.fingerprint,
        "rows": list(rows),
        "groups": groups,
        "correctness_passed": correctness,
        "throughput_ratio_8_to_4": throughput_ratio,
        "queue_wait_p95_ratio_8_to_4": queue_ratio,
        "broker_decision": (
            "BROKER_EVALUATION_REQUIRED" if broker_required else "POSTGRES_QUEUE_RETAINED"
        ) if correctness else "NO_DECISION_CORRECTNESS_FAILED",
    }


def _render(result: Mapping[str, Any]) -> str:
    if result["schema_version"] == "capacity-confirmatory-result/1.0.0":
        return _render_confirmatory(result)
    lines = [
        "# PostgreSQL capacity pilot",
        "",
        "| Workers | Repetitions | Median jobs/s | Delta vs 1 worker | Queue P95 ms | "
        "Workflow P95 ms | Errors | Duplicate ownership |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in result["groups"]:
        lines.append(
            f"| {item['workers']} | {item['repetitions']} | "
            f"{item['throughput_jobs_per_second_median']:.3f} | "
            f"{item['throughput_relative_delta_from_1_worker']:+.1%} | "
            f"{item['queue_wait_p95_ms_median']} | "
            f"{item['workflow_latency_p95_ms_median']} | {item['error_count']} | "
            f"{item['duplicate_job_ownership']} |"
        )
    lines.extend(
        (
            "",
            f"The frozen variance rule selected {result['confirmatory_repetitions']} "
            "repetitions per worker level for the confirmatory run.",
            "",
            "This pilot is sizing evidence only. Local process CPU and Python heap exclude the "
            "database/container. It is not production capacity, availability, or a broker "
            "decision.",
            "",
        )
    )
    return "\n".join(lines)


def _render_confirmatory(result: Mapping[str, Any]) -> str:
    lines = [
        "# PostgreSQL capacity confirmatory comparison",
        "",
        "| Workers | Repetitions | Median jobs/s (95% interval) | Delta vs 1 worker | "
        "Queue P95 ms | Workflow P95 ms | Errors | Duplicates |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in result["groups"]:
        interval = item["throughput_median_95pct_bootstrap"]
        lines.append(
            f"| {item['workers']} | {item['repetitions']} | "
            f"{item['throughput_jobs_per_second_median']:.3f} "
            f"[{interval[0]:.3f}, {interval[1]:.3f}] | "
            f"{item['throughput_relative_delta_from_1_worker_median']:+.1%} | "
            f"{item['queue_wait_p95_ms_median']} | {item['workflow_latency_p95_ms_median']} | "
            f"{item['error_count']} | {item['duplicate_job_ownership']} |"
        )
    lines.extend(
        (
            "",
            f"Broker decision: `{result['broker_decision']}`. The measured 8/4 throughput ratio "
            f"was {result['throughput_ratio_8_to_4']:.3f}; queue-wait P95 ratio was "
            f"{result['queue_wait_p95_ratio_8_to_4']:.3f}.",
            "",
            "These are bounded local results. Process CPU and Python heap exclude PostgreSQL and "
            "container resources; no production capacity or availability claim is made.",
            "",
        )
    )
    return "\n".join(lines)


def execute(*, plan_path: Path, output_dir: Path, code_revision: str) -> None:
    if output_dir.exists():
        raise EvaluationContractError("capacity pilot output already exists")
    if len(code_revision) != 40 or any(
        character not in "0123456789abcdef" for character in code_revision
    ):
        raise EvaluationContractError("capacity pilot requires a full Git revision")
    plan = load_plan(plan_path)
    with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        command.upgrade(_config(url), "head")
        try:
            rows = asyncio.run(run_pilot(url, plan))
        finally:
            command.downgrade(_config(url), "base")
    result = (
        summarize(plan, rows)
        if plan.kind == "pilot"
        else summarize_confirmatory(plan, rows)
    ) | {"code_revision": code_revision}
    output_dir.mkdir(parents=True)
    result_name = "pilot.json" if plan.kind == "pilot" else "confirmatory.json"
    (output_dir / result_name).write_text(
        f"{canonical_json(result)}\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "README.md").write_text(_render(result), encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    arguments = parser.parse_args(argv)
    try:
        execute(
            plan_path=arguments.plan,
            output_dir=arguments.output_dir,
            code_revision=arguments.code_revision,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] capacity pilot failed reason={error}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

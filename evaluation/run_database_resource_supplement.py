"""Run the frozen FC10 PostgreSQL-container resource supplement."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import random
import statistics
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from alembic import command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object
from evaluation.run_capacity_pilot import (
    CapacityPilotPlan,
    _config,
    _run_repetition,
    load_plan,
)

PLAN_SCHEMA = "database-resource-plan/1.0.0"
RESULT_SCHEMA = "database-resource-result/1.0.0"
CONTAINER_METRICS = (
    "postgres_container_cpu_usage_usec",
    "postgres_container_memory_peak_observed_bytes",
    "postgres_container_io_read_bytes",
    "postgres_container_io_write_bytes",
)
POSTGRES_METRICS = (
    "xact_commit",
    "xact_rollback",
    "blks_read",
    "blks_hit",
    "temp_bytes",
    "deadlocks",
    "tup_returned",
    "tup_fetched",
    "tup_inserted",
    "tup_updated",
    "tup_deleted",
)


@dataclass(frozen=True, slots=True)
class DatabaseResourcePlan:
    fingerprint: str
    parent_result: Path
    parent_sha256: str
    workload_source: Path
    workload_sha256: str
    operations: int
    worker_levels: tuple[int, ...]
    repetitions: int
    handler_delay_ms: int
    lease_seconds: int
    poll_interval_ms: int
    required_rows: int
    minimum_memory_samples: int


@dataclass(frozen=True, slots=True)
class ContainerCounters:
    cpu_usage_usec: int
    memory_usage_bytes: int
    io_read_bytes: int
    io_write_bytes: int


class ContainerLike(Protocol):
    def stats(self, **kwargs: object) -> object: ...


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_resource_plan(path: Path) -> DatabaseResourcePlan:
    value = load_json_object(path)
    if value.get("schema_version") != PLAN_SCHEMA or value.get("status") != (
        "FROZEN_BEFORE_MEASUREMENT"
    ):
        raise EvaluationContractError("database resource plan is not frozen")
    levels = value.get("worker_levels")
    container_metrics = value.get("container_metrics")
    postgres_metrics = value.get("postgres_metrics")
    instrumentation = value.get("instrumentation")
    acceptance = value.get("acceptance")
    if levels != [1, 2, 4, 8]:
        raise EvaluationContractError("database resource worker levels changed")
    if container_metrics != list(CONTAINER_METRICS) or postgres_metrics != list(POSTGRES_METRICS):
        raise EvaluationContractError("database resource metric contract changed")
    if not isinstance(instrumentation, dict) or not isinstance(acceptance, dict):
        raise EvaluationContractError("database resource instrumentation contract is missing")
    integers = {
        "operations": value.get("operations_per_repetition"),
        "repetitions": value.get("repetitions"),
        "handler_delay_ms": value.get("handler_delay_ms"),
        "lease_seconds": value.get("lease_seconds"),
        "poll_interval_ms": instrumentation.get("poll_interval_ms"),
        "required_rows": acceptance.get("required_rows"),
        "minimum_memory_samples": acceptance.get("minimum_memory_samples_per_row"),
    }
    if any(type(item) is not int or item < 1 for item in integers.values()):
        raise EvaluationContractError("database resource numeric contract is invalid")
    required_rows = cast(int, integers["required_rows"])
    repetitions = cast(int, integers["repetitions"])
    if required_rows != len(levels) * repetitions:
        raise EvaluationContractError("database resource row count is inconsistent")
    parent, workload = Path(value["parent_result"]), Path(value["workload_source"])
    parent_sha, workload_sha = value["parent_result_sha256"], value["workload_source_sha256"]
    if not all(isinstance(item, str) and len(item) == 64 for item in (parent_sha, workload_sha)):
        raise EvaluationContractError("database resource source binding is invalid")
    if _sha256(parent) != parent_sha or _sha256(workload) != workload_sha:
        raise EvaluationContractError("database resource source binding changed")
    return DatabaseResourcePlan(
        fingerprint=hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest(),
        parent_result=parent,
        parent_sha256=parent_sha,
        workload_source=workload,
        workload_sha256=workload_sha,
        worker_levels=tuple(levels),
        **integers,  # type: ignore[arg-type]
    )


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise EvaluationContractError(f"container stats {name} is unavailable")
    return value


def parse_container_stats(value: Mapping[str, Any]) -> ContainerCounters:
    try:
        cpu_ns = value["cpu_stats"]["cpu_usage"]["total_usage"]
        memory = value["memory_stats"]["usage"]
        entries = value["blkio_stats"]["io_service_bytes_recursive"]
    except (KeyError, TypeError) as error:
        raise EvaluationContractError("container stats contract is unavailable") from error
    if not isinstance(entries, list):
        raise EvaluationContractError("container block I/O stats are unavailable")
    read_bytes = 0
    write_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict):
            raise EvaluationContractError("container block I/O entry is malformed")
        operation = entry.get("op")
        amount = _nonnegative_integer(entry.get("value"), "block I/O value")
        if operation == "read":
            read_bytes += amount
        elif operation == "write":
            write_bytes += amount
    return ContainerCounters(
        cpu_usage_usec=_nonnegative_integer(cpu_ns, "CPU usage") // 1_000,
        memory_usage_bytes=_nonnegative_integer(memory, "memory usage"),
        io_read_bytes=read_bytes,
        io_write_bytes=write_bytes,
    )


def _read_container_stats(container: ContainerLike) -> ContainerCounters:
    value = container.stats(stream=False, one_shot=True)
    if not isinstance(value, dict):
        raise EvaluationContractError("container stats response is malformed")
    return parse_container_stats(value)


async def _postgres_counters(engine: AsyncEngine) -> dict[str, int]:
    columns = ", ".join(POSTGRES_METRICS)
    async with engine.connect() as connection:
        row = (
            (
                await connection.execute(
                    text(
                        f"SELECT {columns} FROM pg_stat_database WHERE datname = current_database()"
                    )
                )
            )
            .mappings()
            .one()
        )
    return {name: _nonnegative_integer(row[name], name) for name in POSTGRES_METRICS}


def _delta(after: int, before: int, name: str) -> int:
    value = after - before
    if value < 0:
        raise EvaluationContractError(f"database resource cumulative counter regressed: {name}")
    return value


async def _measure_repetition(
    engine: AsyncEngine,
    container: ContainerLike,
    workload: CapacityPilotPlan,
    plan: DatabaseResourcePlan,
    workers: int,
    repetition: int,
) -> dict[str, Any]:
    before_container = await asyncio.to_thread(_read_container_stats, container)
    before_postgres = await _postgres_counters(engine)
    memory_samples = [before_container.memory_usage_bytes]
    stop = asyncio.Event()

    async def sample_memory() -> None:
        while not stop.is_set():
            measured = await asyncio.to_thread(_read_container_stats, container)
            memory_samples.append(measured.memory_usage_bytes)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=plan.poll_interval_ms / 1_000)

    sampler = asyncio.create_task(sample_memory())
    try:
        row = await _run_repetition(engine, workload, workers, repetition)
    finally:
        stop.set()
        await sampler
    after_container = await asyncio.to_thread(_read_container_stats, container)
    memory_samples.append(after_container.memory_usage_bytes)
    after_postgres = await _postgres_counters(engine)
    if len(memory_samples) < plan.minimum_memory_samples:
        raise EvaluationContractError("database resource memory sampling is incomplete")
    resources = {
        "postgres_container_cpu_usage_usec": _delta(
            after_container.cpu_usage_usec,
            before_container.cpu_usage_usec,
            "container CPU",
        ),
        "postgres_container_memory_peak_observed_bytes": max(memory_samples),
        "postgres_container_io_read_bytes": _delta(
            after_container.io_read_bytes,
            before_container.io_read_bytes,
            "container read bytes",
        ),
        "postgres_container_io_write_bytes": _delta(
            after_container.io_write_bytes,
            before_container.io_write_bytes,
            "container write bytes",
        ),
    }
    resources.update(
        {
            f"postgres_{name}": _delta(after_postgres[name], before_postgres[name], name)
            for name in POSTGRES_METRICS
        }
    )
    return row | resources | {"postgres_memory_sample_count": len(memory_samples)}


def _execution_order(levels: tuple[int, ...], repetition: int) -> tuple[int, ...]:
    offset = (repetition - 1) % len(levels)
    return levels[offset:] + levels[:offset]


async def run_supplement(
    url: str,
    container: ContainerLike,
    workload: CapacityPilotPlan,
    plan: DatabaseResourcePlan,
) -> list[dict[str, Any]]:
    if (
        workload.operations != plan.operations
        or workload.worker_levels != plan.worker_levels
        or workload.handler_delay_ms != plan.handler_delay_ms
        or workload.lease_seconds != plan.lease_seconds
    ):
        raise EvaluationContractError("database resource workload differs from the frozen parent")
    engine = create_async_engine(url)
    try:
        rows = []
        for repetition in range(1, plan.repetitions + 1):
            for workers in _execution_order(plan.worker_levels, repetition):
                rows.append(
                    await _measure_repetition(
                        engine, container, workload, plan, workers, repetition
                    )
                )
        return rows
    finally:
        await engine.dispose()


def _bootstrap_interval(values: Sequence[float], seed: int) -> list[float]:
    generator = random.Random(seed)
    samples = sorted(
        statistics.median(generator.choices(values, k=len(values))) for _ in range(10_000)
    )
    return [samples[249], samples[9749]]


def _resource_metrics() -> tuple[str, ...]:
    return CONTAINER_METRICS + tuple(f"postgres_{name}" for name in POSTGRES_METRICS)


def summarize(plan: DatabaseResourcePlan, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if len(rows) != plan.required_rows:
        raise EvaluationContractError("database resource row set is incomplete")
    indexed = {(row["workers"], row["repetition"]): row for row in rows}
    expected = {
        (workers, repetition)
        for workers in plan.worker_levels
        for repetition in range(1, plan.repetitions + 1)
    }
    if set(indexed) != expected or len(indexed) != len(rows):
        raise EvaluationContractError("database resource rows are missing or duplicated")
    if any(
        row["completed_jobs"] != plan.operations
        or row["error_count"]
        or row["duplicate_job_ownership"]
        or row["postgres_memory_sample_count"] < plan.minimum_memory_samples
        for row in rows
    ):
        raise EvaluationContractError("database resource correctness gate failed")
    metrics = _resource_metrics()
    for row in rows:
        for metric in metrics:
            _nonnegative_integer(row.get(metric), metric)
    seed = int(plan.fingerprint[:16], 16)
    groups = []
    comparisons = []
    baseline_rows = [indexed[(1, repetition)] for repetition in range(1, plan.repetitions + 1)]
    for workers in plan.worker_levels:
        selected = [indexed[(workers, repetition)] for repetition in range(1, plan.repetitions + 1)]
        groups.append(
            {
                "workers": workers,
                "repetitions": plan.repetitions,
                "metrics": {
                    metric: {"median": statistics.median(row[metric] for row in selected)}
                    for metric in metrics
                },
            }
        )
        if workers == 1:
            continue
        for metric_index, metric in enumerate(metrics):
            baseline_values = [float(row[metric]) for row in baseline_rows]
            candidate_values = [float(row[metric]) for row in selected]
            deltas = [
                candidate - baseline
                for candidate, baseline in zip(candidate_values, baseline_values, strict=True)
            ]
            relative_deltas = [
                (candidate / baseline - 1) if baseline else None
                for candidate, baseline in zip(candidate_values, baseline_values, strict=True)
            ]
            finite_relatives = [value for value in relative_deltas if value is not None]
            baseline_median = statistics.median(baseline_values)
            candidate_median = statistics.median(candidate_values)
            comparisons.append(
                {
                    "workers": workers,
                    "metric": metric,
                    "denominator_pairs": plan.repetitions,
                    "baseline_median": baseline_median,
                    "candidate_median": candidate_median,
                    "absolute_delta_of_arm_medians": candidate_median - baseline_median,
                    "relative_delta_of_arm_medians": (
                        None if baseline_median == 0 else candidate_median / baseline_median - 1
                    ),
                    "paired_absolute_delta_median": statistics.median(deltas),
                    "paired_absolute_delta_median_95pct_bootstrap": _bootstrap_interval(
                        deltas, seed ^ (workers << 12) ^ metric_index
                    ),
                    "paired_relative_delta_median": (
                        statistics.median(finite_relatives) if finite_relatives else None
                    ),
                    "paired_relative_delta_median_95pct_bootstrap": (
                        _bootstrap_interval(finite_relatives, seed ^ (workers << 20) ^ metric_index)
                        if finite_relatives
                        else None
                    ),
                    "interpretation": "RESOURCE_LOAD_NOT_BENEFIT",
                }
            )
    return {
        "schema_version": RESULT_SCHEMA,
        "plan_sha256": plan.fingerprint,
        "parent_result_sha256": plan.parent_sha256,
        "rows": list(rows),
        "groups": groups,
        "comparisons": comparisons,
        "accepted": True,
        "scope": "LOCAL_DOCKER_POSTGRESQL_CONTAINER_ONLY",
    }


def render_markdown(result: Mapping[str, Any]) -> str:
    lines = [
        "# FC10 PostgreSQL database-resource supplement",
        "",
        "All values are local Docker PostgreSQL-container load, not application benefit or "
        "production capacity. Each arm contains eleven paired repetitions.",
        "",
        "| Workers | Metric | Baseline median | Candidate median | Arm-median delta | "
        "Paired delta median (95% interval) | Relative arm delta |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in result["comparisons"]:
        interval = item["paired_absolute_delta_median_95pct_bootstrap"]
        relative = item["relative_delta_of_arm_medians"]
        relative_text = "N/A" if relative is None else f"{relative:+.1%}"
        lines.append(
            f"| {item['workers']} | `{item['metric']}` | {item['baseline_median']:.3f} | "
            f"{item['candidate_median']:.3f} | "
            f"{item['absolute_delta_of_arm_medians']:+.3f} | "
            f"{item['paired_absolute_delta_median']:+.3f} "
            f"[{interval[0]:+.3f}, {interval[1]:+.3f}] | {relative_text} |"
        )
    lines.extend(
        (
            "",
            f"Acceptance: `{'PASS' if result['accepted'] else 'FAIL'}`. The result retains all "
            "44 rows and rejects missing counters, negative cumulative deltas, task errors or "
            "duplicate ownership.",
            "",
        )
    )
    return "\n".join(lines)


def execute(
    *,
    plan_path: Path,
    workload_plan_path: Path,
    output_dir: Path,
    code_revision: str,
) -> None:
    if output_dir.exists():
        raise EvaluationContractError("database resource output already exists")
    if len(code_revision) != 40 or any(
        character not in "0123456789abcdef" for character in code_revision
    ):
        raise EvaluationContractError("database resource run requires a full Git revision")
    plan = load_resource_plan(plan_path)
    workload = load_plan(workload_plan_path)
    with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as postgres:
        url = postgres.get_connection_url()
        command.upgrade(_config(url), "head")
        try:
            rows = asyncio.run(
                run_supplement(url, postgres.get_wrapped_container(), workload, plan)
            )
        finally:
            command.downgrade(_config(url), "base")
    result = summarize(plan, rows) | {"code_revision": code_revision}
    output_dir.mkdir(parents=True)
    (output_dir / "result.json").write_text(
        f"{canonical_json(result)}\n", encoding="utf-8", newline="\n"
    )
    (output_dir / "README.md").write_text(render_markdown(result), encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--workload-plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    arguments = parser.parse_args(argv)
    try:
        execute(
            plan_path=arguments.plan,
            workload_plan_path=arguments.workload_plan,
            output_dir=arguments.output_dir,
            code_revision=arguments.code_revision,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] database resource supplement failed reason={error}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

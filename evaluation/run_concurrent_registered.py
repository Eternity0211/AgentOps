"""Bounded real-provider shared-PostgreSQL concurrent workflow experiment."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.infrastructure import postgres_diagnosis_checkpointer
from agentops_incident_commander.infrastructure.persistence.models import Base
from evaluation.batch_queue import BatchQueue
from evaluation.investigation_job import InvestigationJobInput
from evaluation.lab_prompts import LAB_TENANT, prepare_lab_prompts
from evaluation.live_gateway import local_definitions
from evaluation.observation_snapshot import SnapshotReadAdapter, capture_reads
from evaluation.registered_case import run_registered_case
from evaluation.run_lab_bootstrap import write
from evaluation.run_live_diagnosis import ROOT, checkout, ready
from evaluation.structured_model import StructuredEvaluationModel
from evaluation.workflow_resources import measure_workflow


def run(output: Path, key: str) -> dict[str, Any]:
    if not key or key.strip() != key:
        raise ValueError("DEEPSEEK_API_KEY is required")
    protocol = ROOT / "evaluation/registered_protocol/concurrent-v1.json"
    plan = json.loads(protocol.read_text(encoding="utf-8"))
    if plan["batch_sizes"] != [2, 4] or plan["max_total_calls"] != 33:
        raise ValueError("concurrent protocol mismatch")
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    def journal(event: dict[str, Any]) -> None:
        record = {"at": datetime.now(UTC).isoformat(), **event}
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        events.append(record)

    write(
        output / "metadata.json",
        {
            "schema_version": "concurrent-registered/1.0.0",
            "provider_kind": "REAL_DEEPSEEK",
            "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
            "base_revision": subprocess.check_output(
                ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"], text=True
            ).strip(),
            "source_hashes": {
                p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / "evaluation").glob("*.py")
            },
        },
    )

    async def execute(url: str) -> None:
        engine = create_async_engine(url)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            references = await prepare_lab_prompts(
                sessions,
                StructuredEvaluationModel(key, journal, max_calls=3),
                output / "bootstrap",
                journal,
                fixture_version="4.0.0",
            )
            if len(references) != 3:
                journal({"event": "concurrent.bootstrap_refused"})
                return
            async with postgres_diagnosis_checkpointer(
                url.replace("postgresql+asyncpg://", "postgresql://")
            ) as saver:
                with httpx.Client(timeout=15, trust_env=False) as client:
                    ready(client)
                    for size in (2, 4):
                        start = datetime.now(UTC)
                        probes = [
                            checkout(client, sku="evaluation-concurrent-" + uuid4().hex[:12])
                            for _ in range(8)
                        ]
                        await asyncio.sleep(20)
                        end = datetime.now(UTC)
                        reads = await capture_reads(start, end)
                        capture_path = output / f"capture-{size}.json"
                        write(
                            capture_path,
                            {
                                "start": start.isoformat(),
                                "end": end.isoformat(),
                                "probes": probes,
                                "reads": reads,
                            },
                        )
                        queue = BatchQueue(sessions, size, size, timeout=180)
                        batch_cases: list[dict[str, Any]] = []

                        identifiers = {i: "concurrent-" + uuid4().hex[:20] for i in range(size)}

                        async def one(
                            index: int,
                            *,
                            probes: list[dict[str, Any]] = probes,
                            start: datetime = start,
                            end: datetime = end,
                            reads: dict[str, Any] = reads,
                            queue: BatchQueue = queue,
                            batch_cases: list[dict[str, Any]] = batch_cases,
                            size: int = size,
                            identifiers: dict[int, str] = identifiers,
                        ) -> None:
                            incident = identifiers[index]
                            started = time.monotonic_ns()
                            payload = InvestigationJobInput(
                                "payload-" + incident,
                                LAB_TENANT.value,
                                incident,
                                "workflow-" + incident,
                                "corr-" + incident,
                                "cause-" + incident,
                                "Gateway checkout observations: " + json.dumps(probes),
                                start,
                                end,
                                output / "cases" / incident / "evidence",
                            )
                            try:
                                result = await run_registered_case(
                                    sessions,
                                    saver,
                                    StructuredEvaluationModel(key, journal, max_calls=5),
                                    references,
                                    payload,
                                    journal,
                                    adapters={
                                        d.identity: SnapshotReadAdapter(d.name, reads)
                                        for d in local_definitions()
                                    },
                                    consume=queue.consume,
                                )
                            except Exception as error:
                                result = {
                                    "incident_id": incident,
                                    "status": "FAILED",
                                    "error_type": type(error).__name__,
                                }
                            result.update(
                                batch_size=size,
                                case_index=index,
                                elapsed_ms=(time.monotonic_ns() - started) // 1000000,
                            )
                            write(output / f"case-{size}-{index}.json", result)
                            batch_cases.append(result)

                        before = len(events)
                        started = time.monotonic_ns()
                        with measure_workflow() as resources:
                            tasks: list[asyncio.Task[Any]] = [
                                asyncio.create_task(one(i)) for i in range(size)
                            ]
                            tasks.append(asyncio.create_task(queue.run()))
                            try:
                                completed = await asyncio.wait_for(
                                    asyncio.gather(*tasks, return_exceptions=True), 240
                                )
                            except Exception as error:
                                completed = [error]
                            finally:
                                for task in tasks:
                                    task.cancel()
                                await asyncio.gather(*tasks, return_exceptions=True)
                        for index in range(size):
                            if not any(c["case_index"] == index for c in batch_cases):
                                missing = {
                                    "incident_id": identifiers[index],
                                    "status": "FAILED",
                                    "error_type": "UNFINISHED_BATCH_CASE",
                                    "batch_size": size,
                                    "case_index": index,
                                }
                                write(output / f"case-{size}-{index}.json", missing)
                                batch_cases.append(missing)
                        record = {
                            "batch_size": size,
                            "elapsed_ms": (time.monotonic_ns() - started) // 1000000,
                            "peak_investigation_handlers": queue.peak,
                            "completed_jobs": completed[-1]
                            if isinstance(completed[-1], int)
                            else None,
                            "batch_error_type": type(completed[-1]).__name__
                            if isinstance(completed[-1], BaseException)
                            else None,
                            "cases": batch_cases,
                            "provider_starts": sum(
                                e.get("status") == "STARTED" for e in events[before:]
                            ),
                            "capture_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                            **resources,
                        }
                        results.append(record)
                        write(output / f"batch-{size}.json", record)
                        print(
                            (
                                f"Concurrent registered batch {size}: cases={len(batch_cases)} "
                                f"peak={queue.peak}"
                            ),
                            flush=True,
                        )
        finally:
            try:
                async with sessions() as session:
                    full = {
                        name: [dict(r) for r in (await session.execute(select(table))).mappings()]
                        for name, table in Base.metadata.tables.items()
                    }
                    absent = []
                    for name in (
                        "checkpoints",
                        "checkpoint_blobs",
                        "checkpoint_writes",
                        "checkpoint_migrations",
                    ):
                        if (
                            await session.scalar(text("SELECT to_regclass(:name)"), {"name": name})
                            is None
                        ):
                            absent.append(name)
                            full[name] = []
                            continue
                        full[name] = [
                            dict(r)
                            for r in (
                                await session.execute(text(f'SELECT * FROM "{name}"'))
                            ).mappings()
                        ]

                    def encode(value: Any) -> Any:
                        if isinstance(value, bytes):
                            return {"encoding": "base64", "data": base64.b64encode(value).decode()}
                        return str(value)

                    write(output / "sql-records.json", json.loads(json.dumps(full, default=encode)))
                    write(
                        output / "sql-export-state.json",
                        {"uninitialized_checkpoint_tables": absent},
                    )
            except Exception as error:
                summary["sql_export_error_type"] = type(error).__name__
            finally:
                await engine.dispose()

    summary: dict[str, Any] = {
        "approval_decisions": 0,
        "recovery_executions": 0,
        "actual_bill": None,
    }
    try:
        with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as database:
            url = database.get_connection_url()
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "head")
            if sys.platform == "win32":
                with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                    runner.run(execute(url))
            else:
                asyncio.run(execute(url))
    except Exception as error:
        summary["operational_error_type"] = type(error).__name__
    summary.update(
        batches=len(results),
        cases=sum(len(r["cases"]) for r in results),
        provider_starts=sum(e.get("status") == "STARTED" for e in events),
    )
    write(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.output_dir, os.environ.get("DEEPSEEK_API_KEY", "")))


if __name__ == "__main__":
    main()

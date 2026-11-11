"""Actual local telemetry/provider/SQL workflow; no approval or recovery execution."""

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

from agentops_incident_commander.faults import SCENARIO_TARGETS, ScenarioName, clean, inject
from agentops_incident_commander.infrastructure import postgres_diagnosis_checkpointer
from agentops_incident_commander.infrastructure.persistence.models import (
    ApprovalRow,
    Base,
    IncidentRow,
    JobRow,
    ModelCallTraceRow,
)
from evaluation.investigation_job import InvestigationJobInput
from evaluation.lab_prompts import LAB_TENANT, prepare_lab_prompts
from evaluation.registered_case import run_registered_case
from evaluation.run_lab_bootstrap import write
from evaluation.run_live_diagnosis import ENVIRONMENT, ROOT, checkout, ready, wait_target
from evaluation.structured_model import VERSION, StructuredEvaluationModel
from evaluation.workflow_resources import measure_workflow

CASES: tuple[ScenarioName | None, ...] = (None, "http-500", "memory-leak")


FULL_CASES: tuple[ScenarioName | None, ...] = (
    None,
    "http-500",
    "db-pool-exhaustion",
    "redis-timeout",
    "downstream-latency",
    "memory-leak",
    "bad-configuration",
)


def run(
    output: Path, key: str, *, cases: tuple[ScenarioName | None, ...] = CASES
) -> dict[str, Any]:
    if not key or key.strip() != key:
        raise ValueError("DEEPSEEK_API_KEY is required")
    if (
        not cases
        or len(cases) > 7
        or len(set(cases)) != len(cases)
        or any(s is not None and s not in SCENARIO_TARGETS for s in cases)
    ):
        raise ValueError("registered live protocol contains an unknown scenario")
    output.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []

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
            "schema_version": "registered-live/2.1.0",
            "resource_scope": (
                "Process CPU and Python traced heap only; excludes native allocations, "
                "child containers, database and provider"
            ),
            "transport_version": VERSION,
            "base_revision": subprocess.check_output(
                ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "provider_kind": "REAL_DEEPSEEK",
            "observation_origin": "LIVE_COMPOSE_TELEMETRY",
            "bootstrap_origin": "SEPARATE_SYNTHETIC_SAFETY_FIXTURE",
            "concurrency": 1,
            "cases": list(cases),
            "full_matrix_protocol_sha256": (
                hashlib.sha256(
                    (ROOT / "evaluation/registered_protocol/live-v2.json").read_bytes()
                ).hexdigest()
                if cases == FULL_CASES
                else None
            ),
            "max_bootstrap_calls": 3,
            "max_calls_per_case": 5,
            "source_hashes": {
                p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / "evaluation").glob("*.py")
            },
        },
    )
    results: list[dict[str, Any]] = []
    environment = {**os.environ, **ENVIRONMENT}

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
                journal({"event": "registered_live.bootstrap_refused"})
                return
            connection = url.replace("postgresql+asyncpg://", "postgresql://")
            async with postgres_diagnosis_checkpointer(connection) as saver:
                with httpx.Client(timeout=15, trust_env=False) as client:
                    ready(client)
                    sku = f"evaluation-{uuid4().hex[:16]}"
                    for index, scenario in enumerate(cases):
                        active = False
                        identifier = f"registered-{uuid4().hex[:20]}"
                        record: dict[str, Any] = {
                            "instance_id": identifier,
                            "evaluator_scenario": scenario,
                            "approval_decided": False,
                            "recovery_executed": False,
                        }
                        measurements: dict[str, int | str] = {}
                        try:
                            record["baseline"] = checkout(client, sku=sku)
                            if record["baseline"]["status"] != 200:
                                raise RuntimeError("baseline checkout failed")
                            if scenario is not None:
                                active = True
                                if inject(scenario, root=ROOT, environment=environment) != 0:
                                    raise RuntimeError("fault injection failed")
                                wait_target(SCENARIO_TARGETS[scenario], environment)
                            start = datetime.now(UTC)
                            probes = [checkout(client, sku=sku) for _ in range(8)]
                            await asyncio.sleep(20)
                            end = datetime.now(UTC)
                            record["probes"] = probes
                            # No scenario/target/labels enter the model or workflow payload.
                            payload = InvestigationJobInput(
                                f"payload-{identifier}",
                                LAB_TENANT.value,
                                identifier,
                                f"workflow-{identifier}",
                                f"corr-{identifier}",
                                f"cause-{identifier}",
                                "Gateway checkout observations: "
                                + json.dumps(probes)
                                + " Rehearsal checklist: use query_deployments and query_metrics "
                                "for a service selected from the checkout path to check deployment "
                                "history and independently observed version. Also collect evidence "
                                "for the symptom. Report uncertainty when observations do not "
                                "support a cause or version claim.",
                                start,
                                end,
                                output / "cases" / identifier / "evidence",
                            )
                            before = len(events)
                            started = time.monotonic_ns()
                            with measure_workflow() as measurements:
                                record.update(
                                    await run_registered_case(
                                        sessions,
                                        saver,
                                        StructuredEvaluationModel(key, journal, max_calls=5),
                                        references,
                                        payload,
                                        journal,
                                    )
                                )
                            record["workflow_ms"] = (time.monotonic_ns() - started) // 1_000_000
                            record["provider_starts"] = sum(
                                e.get("status") == "STARTED" for e in events[before:]
                            )
                        except Exception as error:
                            record.update(status="FAILED", error_type=type(error).__name__)
                        finally:
                            record.update(measurements)
                            if active and scenario is not None:
                                record["cleanup_exit"] = clean(root=ROOT, environment=environment)
                                wait_target(SCENARIO_TARGETS[scenario], environment)
                            record["after_checkout"] = checkout(client, sku=sku)
                            results.append(record)
                            write(output / f"case-{index}.json", record)
                        print(f"Registered live case {index}: {record['status']}", flush=True)
            async with sessions() as session:
                # Export content-free SQL state before the isolated database is removed.
                exports = {}
                for name, table, fields in (
                    ("incidents", IncidentRow, ("id", "state", "version")),
                    ("jobs", JobRow, ("id", "status", "attempt_count")),
                    (
                        "model_traces",
                        ModelCallTraceRow,
                        (
                            "id",
                            "workflow_run_id",
                            "node",
                            "status",
                            "request_hash",
                            "response_hash",
                        ),
                    ),
                    ("approvals", ApprovalRow, ("id", "status", "incident_id")),
                ):
                    rows = (await session.scalars(select(table))).all()
                    exports[name] = [{f: getattr(row, f) for f in fields} for row in rows]
                write(output / "sql-state.json", exports)
                full = {}
                for name, mapped in Base.metadata.tables.items():
                    full[name] = [
                        dict(r) for r in (await session.execute(select(mapped))).mappings()
                    ]
                for name in (
                    "checkpoints",
                    "checkpoint_blobs",
                    "checkpoint_writes",
                    "checkpoint_migrations",
                ):
                    full[name] = [
                        dict(r)
                        for r in (await session.execute(text(f'SELECT * FROM "{name}"'))).mappings()
                    ]

                def encode(value: Any) -> Any:
                    if isinstance(value, bytes):
                        return {"encoding": "base64", "data": base64.b64encode(value).decode()}
                    return str(value)

                write(output / "sql-records.json", json.loads(json.dumps(full, default=encode)))
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
        cases=len(results),
        provider_starts=sum(e.get("status") == "STARTED" for e in events),
        pending_approvals=sum(r.get("status") == "PENDING_APPROVAL" for r in results),
    )
    write(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--full-matrix", action="store_true")
    args = parser.parse_args()
    print(
        run(
            args.output_dir,
            os.environ.get("DEEPSEEK_API_KEY", ""),
            cases=FULL_CASES if args.full_matrix else CASES,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()

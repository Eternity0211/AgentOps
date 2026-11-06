"""Run actual-provider lab registration preflight in a disposable PostgreSQL database."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.domain import CorrelationId
from agentops_incident_commander.infrastructure.persistence.models import PromptVersionRow
from agentops_incident_commander.infrastructure.persistence.repositories import AuditRepository
from evaluation.lab_prompts import LAB_TENANT, prepare_lab_prompts
from evaluation.structured_model import VERSION, StructuredEvaluationModel

ROOT = Path(__file__).resolve().parents[1]


def write(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def run(root: Path, key: str, *, fixture_version: str = "3.0.0") -> dict[str, Any]:
    if not key or key.strip() != key:
        raise ValueError("DEEPSEEK_API_KEY is required")
    if fixture_version not in {"1.0.0", "2.0.0", "3.0.0"}:
        raise ValueError("unknown lab regression fixture version")
    root.mkdir(parents=True, exist_ok=False)
    events: list[dict[str, Any]] = []

    def journal(event: dict[str, Any]) -> None:
        document = {"at": datetime.now(UTC).isoformat(), **event}
        with (root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(document, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        events.append(document)

    write(
        root / "metadata.json",
        {
            "schema_version": "1.0.0",
            "started_at": datetime.now(UTC).isoformat(),
            "base_revision": subprocess.check_output(
                ["git", "-c", f"safe.directory={ROOT.as_posix()}", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
            "provider_kind": "REAL_DEEPSEEK",
            "observation_origin": "SYNTHETIC_SAFETY_FIXTURE_NOT_HISTORY",
            "model": "deepseek-flash",
            "temperature": 0,
            "thinking": "disabled",
            "max_output_tokens": 2048,
            "maximum_provider_calls": 3,
            "concurrency": 1,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
            "fixture_version": fixture_version,
            "transport_version": VERSION,
            "source_hashes": {
                name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                for name in (
                    "evaluation/lab_prompts.py",
                    "evaluation/run_lab_bootstrap.py",
                    "evaluation/structured_model.py",
                    "evaluation/live_evidence.py",
                    f"evaluation/registered_protocol/v{fixture_version[0]}/bootstrap.json",
                )
            },
        },
    )

    async def execute(url: str) -> int:
        engine = create_async_engine(url)
        try:
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            references = await prepare_lab_prompts(
                sessions,
                StructuredEvaluationModel(key, journal, max_calls=3),
                root / "regression",
                journal,
                fixture_version=fixture_version,
            )
            async with sessions() as session:
                rows = (
                    await session.scalars(
                        select(PromptVersionRow).where(
                            PromptVersionRow.tenant_id == LAB_TENANT.value,
                        )
                    )
                ).all()
                write(
                    root / "registry.json",
                    [
                        {
                            "prompt_id": r.prompt_id,
                            "version": r.version,
                            "status": r.status,
                            "content_fingerprint": r.content_fingerprint,
                        }
                        for r in rows
                    ],
                )
                audit = await AuditRepository(session).by_correlation(
                    CorrelationId("lab-prompt-regression")
                )
                write(
                    root / "audit.json",
                    [
                        {
                            "event_type": r.event.type,
                            "sequence": r.sequence,
                            "tenant_sequence": r.tenant_sequence,
                            "event_fingerprint": r.event_fingerprint.value,
                            "actor_id": r.event.actor_id.value,
                            "occurred_at": r.event.occurred_at.isoformat(),
                            "target_type": r.event.target.type,
                            "target_id": r.event.target.id.value,
                            "request_hash": r.event.request_hash.value
                            if r.event.request_hash
                            else None,
                            "result_hash": r.event.result_hash.value
                            if r.event.result_hash
                            else None,
                        }
                        for r in audit
                    ],
                )
            return len(references)
        finally:
            await engine.dispose()

    summary: dict[str, Any] = {
        "provider_kind": "REAL_DEEPSEEK",
        "fixture_origin": "SYNTHETIC_SAFETY_FIXTURE_NOT_HISTORY",
        "fixture_version": fixture_version,
        "activated_count": 0,
        "actual_bill": None,
        "approval_decisions": 0,
        "recovery_executions": 0,
    }
    try:
        with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="asyncpg") as postgres:
            url = postgres.get_connection_url()
            config = Config(str(ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(ROOT / "migrations"))
            config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
            command.upgrade(config, "head")
            if sys.platform == "win32":
                with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                    summary["activated_count"] = runner.run(execute(url))
            else:
                summary["activated_count"] = asyncio.run(execute(url))
        summary["status"] = (
            "ACTIVATED_LAB_ONLY" if summary["activated_count"] == 3 else "REGRESSION_REFUSED"
        )
    except Exception as error:
        summary.update(status="OPERATIONAL_FAILURE", error_type=type(error).__name__)
    measured = [e for e in events if isinstance(e.get("usage"), dict)]
    summary.update(
        provider_starts=sum(e.get("status") == "STARTED" for e in events),
        metered_responses=len(measured),
        input_tokens=sum(e["usage"]["prompt_tokens"] for e in measured),
        output_tokens=sum(e["usage"]["completion_tokens"] for e in measured),
        ephemeral_database=True,
    )
    write(root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture-version", choices=("1.0.0", "2.0.0", "3.0.0"), default="3.0.0")
    args = parser.parse_args()
    result = run(
        args.output_dir,
        os.environ.get("DEEPSEEK_API_KEY", ""),
        fixture_version=args.fixture_version,
    )
    print(f"Lab Prompt preflight: {result['status']}; activated={result['activated_count']}/3")


if __name__ == "__main__":  # pragma: no cover
    main()

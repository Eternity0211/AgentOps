"""Autonomous investigations replay completed PostgreSQL checkpoints without model/tool effects."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from evaluation.autonomous_diagnosis import investigate
from evaluation.live_gateway import SOURCES, local_definitions
from evaluation.structured_model import StructuredEvaluationModel
from testcontainers.community.postgres import PostgresContainer

from agentops_incident_commander.infrastructure import postgres_diagnosis_checkpointer


def test_completed_autonomous_run_replays_after_postgres_saver_replacement(tmp_path: Path) -> None:
    effects = {"model": 0, "tool": 0}
    plan = {
        "plan": {
            "schema_version": "1.0.0",
            "plan_id": "plan",
            "summary": "Inspect logs",
            "steps": [
                {
                    "step_id": "logs",
                    "objective": "Inspect errors",
                    "expected_source": "LOG",
                    "parallel_group": 0,
                }
            ],
        },
        "tool_calls": [
            {
                "step_id": "logs",
                "tool_name": "query_logs",
                "tool_version": "2.0.0",
                "arguments": {"service": "order"},
            }
        ],
    }
    report = {
        "schema_version": "1.0.0",
        "incident_id": "checkpoint-incident",
        "disposition": "HUMAN_HANDOFF",
        "candidates": [],
        "missing_evidence": ["independent source"],
        "explanation": "Need current independent evidence",
    }

    def respond(request: httpx.Request) -> httpx.Response:
        effects["model"] += 1
        payload = json.loads(request.content)
        schema = json.loads(payload["messages"][1]["content"])["output_schema"]
        output = plan if "plan" in schema["properties"] else report
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}],
            },
        )

    class Adapter:
        def __init__(self, name: str) -> None:
            self.name = name

        async def invoke(self, context: Any, arguments: Any) -> dict[str, Any]:
            effects["tool"] += 1
            return {
                "source": SOURCES[self.name],
                "summary": "Observed dependency error",
                "provenance": json.dumps({"tool": self.name, "version": "2.0.0"}),
                "complete_window": False,
                "records_seen": 1,
            }

    async def run(url: str) -> None:
        now = datetime.now(UTC)
        adapters = {
            definition.identity: Adapter(definition.name) for definition in local_definitions()
        }
        first_model = StructuredEvaluationModel(
            "test-only", lambda e: None, transport=httpx.MockTransport(respond)
        )
        async with postgres_diagnosis_checkpointer(url) as saver:
            first, services = await investigate(
                first_model,
                "checkpoint-incident",
                "Observed errors",
                tmp_path,
                now - timedelta(minutes=1),
                now,
                lambda e: None,
                adapters=adapters,
                checkpointer=saver,
            )
            assert not services.resumed
        before = dict(effects)
        second_model = StructuredEvaluationModel(
            "test-only", lambda e: None, transport=httpx.MockTransport(respond)
        )
        async with postgres_diagnosis_checkpointer(url) as replacement:
            second, services = await investigate(
                second_model,
                "checkpoint-incident",
                "Observed errors",
                tmp_path,
                now - timedelta(minutes=1),
                now,
                lambda e: None,
                adapters=adapters,
                checkpointer=replacement,
            )
        assert first == second and services.resumed
        assert first.phase.value == "HUMAN_HANDOFF"
        assert effects == before == {"model": 2, "tool": 1}

    with PostgresContainer("pgvector/pgvector:0.8.6-pg18", driver="psycopg") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg://", "postgresql://")
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                runner.run(run(url))
        else:
            asyncio.run(run(url))

"""Capture one bounded Docker memory-evidence audit and always restore the lab."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from agentops_incident_commander.faults import clean, inject
from evaluation.autonomous_diagnosis import build_candidate_diagnosis_context
from evaluation.live_gateway import LocalReadAdapter
from evaluation.run_live_diagnosis import ENVIRONMENT, ROOT, checkout, ready, wait_target


async def _collect(start: datetime, end: datetime) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    for tool in ("query_traces", "query_logs", "query_deployments"):
        deadline = time.monotonic() + (30 if tool == "query_traces" else 0)
        while True:
            result = await LocalReadAdapter(tool, start, end).invoke(None, {"service": "order"})  # type: ignore[arg-type]
            if (
                tool != "query_traces"
                or "process.memory.retained_bytes" in str(result["summary"])
                or time.monotonic() >= deadline
            ):
                break
            await asyncio.sleep(2)
        observations.append(
            {
                "id": f"runtime-{tool.removeprefix('query_')}",
                "source": str(result["source"]),
                "summary": str(result["summary"]),
                "observed_from": start.isoformat(),
                "observed_to": end.isoformat(),
                "provenance": str(result["provenance"]),
                "records_seen": str(result["records_seen"]),
                "complete_window": str(result["complete_window"]).lower(),
            }
        )
    return observations


def build_audit_document(
    *,
    run_id: str,
    start: datetime,
    end: datetime,
    checkouts: list[dict[str, Any]],
    observations: list[dict[str, str]],
    cleanup_exit: int,
    after_cleanup_status: int,
) -> dict[str, Any]:
    context_inputs = [
        {key: value for key, value in observation.items() if key != "provenance"}
        for observation in observations
    ]
    context = build_candidate_diagnosis_context(
        context_inputs, {}, window_start=start, window_end=end
    )
    document = {
        "schema_version": "memory-runtime-audit/1.0.0",
        "evaluator_run_id": run_id,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "checkout_statuses": [item["status"] for item in checkouts],
        "checkout_durations_ms": [item["duration_ms"] for item in checkouts],
        "observations": observations,
        "memory_facts": context["memory_retention_by_service"],
        "service_facts": context["alert_aligned_service_facts"],
        "deployment_facts": context["deployment_facts"],
        "context_budget": context["context_budget"],
        "referenceable_evidence_ids": context["evidence_ids"],
        "cleanup_exit": cleanup_exit,
        "after_cleanup_status": after_cleanup_status,
        "recovery_credit": False,
    }
    memory = document["memory_facts"]
    raw = "\n".join(observation["summary"] for observation in observations)
    document["acceptance"] = {
        "six_successful_checkouts": document["checkout_statuses"] == [200] * 6,
        "sustained_retention": any(
            fact.get("classification") == "SUSTAINED_RETENTION" for fact in memory
        ),
        "complete_gc_pair": any(fact.get("gc_pair_count", 0) >= 1 for fact in memory),
        "release_counter_observed": "process.memory.retention_releases" in raw,
        "fault_deployment_observed": any(
            fact.get("version") == "2.0.0" for fact in document["deployment_facts"]
        ),
        "cleanup_verified": cleanup_exit == 0 and after_cleanup_status == 200,
    }
    document["accepted"] = all(document["acceptance"].values())
    return document


def capture(output: Path) -> None:
    if output.exists():
        raise FileExistsError("memory runtime audit output already exists")
    environment = {**os.environ, **ENVIRONMENT}
    run_id = f"run-{uuid4().hex[:12]}"
    cleanup_exit = -1
    after_cleanup_status = 0
    start = datetime.now(UTC)
    end = start
    checkouts: list[dict[str, Any]] = []
    observations: list[dict[str, str]] = []
    try:
        if inject("memory-leak", run_id=run_id, root=ROOT, environment=environment) != 0:
            raise RuntimeError("memory fault injection failed")
        wait_target("order", environment)
        with httpx.Client(timeout=10, trust_env=False) as client:
            ready(client)
            start = datetime.now(UTC)
            checkouts = [checkout(client, sku=f"fc3i-{index}") for index in range(6)]
            time.sleep(6)
            end = datetime.now(UTC)
            observations = asyncio.run(_collect(start, end))
    finally:
        cleanup_exit = clean(run_id=run_id, root=ROOT, environment=environment)
        if cleanup_exit == 0:
            wait_target("order", environment)
            with httpx.Client(timeout=10, trust_env=False) as client:
                ready(client)
                after_cleanup_status = int(checkout(client, sku="fc3i-clean")["status"])
    document = build_audit_document(
        run_id=run_id,
        start=start,
        end=end,
        checkouts=checkouts,
        observations=observations,
        cleanup_exit=cleanup_exit,
        after_cleanup_status=after_cleanup_status,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not document["accepted"]:
        raise RuntimeError("memory runtime audit acceptance failed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capture(args.output)


if __name__ == "__main__":  # pragma: no cover
    main()

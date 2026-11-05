"""Actual model-selected read investigation over local faults; never approves recovery."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from agentops_incident_commander.faults import SCENARIO_TARGETS, clean, inject
from evaluation.autonomous_diagnosis import investigate
from evaluation.run_live_diagnosis import ENVIRONMENT, ROOT, checkout, ready, wait_target
from evaluation.structured_model import StructuredEvaluationModel


def run(output: Path, *, smoke: bool = False) -> None:
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY required")
    output.mkdir(parents=True, exist_ok=False)
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    environment = {**os.environ, **ENVIRONMENT}
    results = []
    sku = f"evaluation-{uuid4().hex[:16]}"
    scenarios = [(None, "gateway")] if smoke else list(SCENARIO_TARGETS.items())
    with httpx.Client(timeout=15, trust_env=False) as client:
        ready(client)
        for index, (scenario, target) in enumerate(scenarios, 1):
            incident = f"autonomous-{sku.removeprefix('evaluation-')}-{index}"

            def journal(event: dict[str, Any], incident_id: str = incident) -> None:
                with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "incident_id": incident_id,
                                "at": datetime.now(UTC).isoformat(),
                                **event,
                            }
                        )
                        + "\n"
                    )
                    stream.flush()
                    os.fsync(stream.fileno())

            record: dict[str, Any] = {
                "incident_id": incident,
                "scenario": scenario,
                "product_recovery_executed": False,
            }
            active = False
            try:
                record["baseline"] = checkout(client, sku=sku)
                if record["baseline"]["status"] != 200:
                    raise RuntimeError("baseline checkout failed")
                if scenario is not None:
                    active = True
                    if inject(scenario, root=ROOT, environment=environment) != 0:
                        raise RuntimeError("injection failed")
                    wait_target(target, environment)
                start = datetime.now(UTC)
                probes = [checkout(client, sku=sku) for _ in range(8)]
                time.sleep(20)
                end = datetime.now(UTC)
                # Input derives only from measured gateway behavior, not evaluator labels/target.
                alert = "Gateway checkout observations: " + json.dumps(probes)
                model = StructuredEvaluationModel(key, journal, max_calls=4)
                phase_started = time.monotonic_ns()
                state, services = asyncio.run(
                    investigate(
                        model,
                        incident,
                        alert,
                        ROOT / "artifacts" / "autonomous-evidence" / output.name / incident,
                        start,
                        end,
                        journal,
                    )
                )
                record.update(
                    phase=state.phase.value,
                    graph_error=state.error_code,
                    tool_calls=state.budgets.used_tool_calls,
                    model_calls=state.budgets.used_model_calls,
                    diagnosis_ms=(time.monotonic_ns() - phase_started) // 1_000_000,
                    candidates=[c.candidate_id for c in services.report.candidates]
                    if services.report
                    else [],
                    gate=[
                        {
                            "candidate": d.candidate_id,
                            "outcome": d.outcome.value,
                            "reasons": [r.code.value for r in d.reasons],
                        }
                        for d in services.gates
                    ],
                    usage=services.usage,
                    evidence_count=len(services.evidence.records) if services.evidence else 0,
                )
            except Exception as error:
                record.update(phase="FAILED", error_type=type(error).__name__)
                # Provider and telemetry exception bodies may contain untrusted text: omit them.
            finally:
                if active:
                    record["cleanup_exit"] = clean(root=ROOT, environment=environment)
                    wait_target(target, environment)
                record["after_checkout"] = checkout(client, sku=sku)
                results.append(record)
                with (output / "cases.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record) + "\n")
            print(f"autonomous case {index}: {record['phase']}", flush=True)
    document = {
        "schema_version": "autonomous-local-evaluation/1.0.0",
        "code_revision": revision,
        "smoke": smoke,
        "results": results,
        "limitations": [
            "Local evaluation composition; PostgreSQL/prompt promotion pending C3",
            "No approvals or product writes; cleanup is evaluator infrastructure",
            "No memory alert is fabricated if measured gateway requests remain healthy",
        ],
    }
    (output / "results.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    run(args.output_dir, smoke=args.smoke)


if __name__ == "__main__":  # pragma: no cover
    main()

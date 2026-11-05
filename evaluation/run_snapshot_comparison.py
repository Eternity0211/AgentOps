"""Run one immutable observation instance without loading evaluator labels."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agentops_incident_commander.domain import EvidenceGateDecision
from evaluation.autonomous_diagnosis import investigate
from evaluation.live_gateway import local_definitions
from evaluation.observation_snapshot import SnapshotReadAdapter, load_snapshot
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import CAUSES, MODES, Outcome
from evaluation.structured_model import ModelPurpose, StructuredEvaluationModel, StructuredResult


class ComparisonModel(StructuredEvaluationModel):
    def invoke(
        self,
        purpose: ModelPurpose,
        context: dict[str, Any],
        *,
        gate: EvidenceGateDecision | None = None,
    ) -> StructuredResult:
        return super().invoke(
            purpose,
            {
                **context,
                "public_cause_taxonomy": list(CAUSES),
                "candidate_id_rule": (
                    "Use exact public cause IDs for root-cause candidates. "
                    "If unsupported, hand off with missing evidence."
                ),
                "historical_references": [],
            },
            gate=gate,
        )


def run_snapshot(
    path: Path,
    expected_hash: str,
    mode: str,
    output: Path,
    protocol_hash: str,
    *,
    key: str,
    transport: Any = None,
) -> Outcome:
    if mode not in MODES:
        raise ValueError("unknown comparison mode")
    snapshot = load_snapshot(path, expected_hash=expected_hash)
    identity = snapshot["instance_id"]
    run_root = output / mode / identity
    run_root.mkdir(parents=True, exist_ok=False)
    (run_root / "mode.json").write_text(
        json.dumps(
            {
                "mode": mode,
                "historical_reference_count": 0,
                "memory_status": "NO_HISTORY_SUPPLIED",
                "quality_comparison_eligible": mode != "controlled-graph-memory",
            }
        ),
        encoding="utf-8",
    )
    events: list[dict[str, Any]] = []

    def journal(event: dict[str, Any]) -> None:
        events.append(dict(event))
        with (run_root / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    model = ComparisonModel(key, journal, max_calls=4, transport=transport)
    started = time.monotonic_ns()
    values: dict[str, Any] = {}
    try:
        _state, services = asyncio.run(
            investigate(
                model,
                identity,
                snapshot["alert"],
                run_root / "evidence",
                datetime.fromisoformat(snapshot["window_start"]),
                datetime.fromisoformat(snapshot["window_end"]),
                journal,
                adapters={
                    d.identity: SnapshotReadAdapter(d.name, snapshot["reads"])
                    for d in local_definitions()
                },
                single_pass=mode == "single-agent",
            )
        )
        if services.report is None:
            raise ValueError("no completed report")
        report = services.report
        values = {
            "status": "SUCCEEDED",
            "candidates": tuple(c.candidate_id for c in report.candidates),
            "disposition": report.disposition.value,
            "missing_evidence_count": len(report.missing_evidence),
            "gate_pass": any(g.outcome.value == "PASS" for g in services.gates),
            "counter_evidence_addressed": any(
                c.counter_evidence_ids and c.counter_evidence_explanation for c in report.candidates
            ),
        }
    except Exception as error:
        journal({"event": "comparison.failed", "error_type": type(error).__name__})
        values = {"status": "FAILED"}
    usage = [e["usage"] for e in events if isinstance(e.get("usage"), dict)]
    # Missing provider usage stays unknown, including calls that fail before receiving usage.
    finished = [e for e in events if e.get("status") in ("SUCCEEDED", "FAILED")]
    if usage and len(usage) == len(finished):
        values["input_tokens"] = sum(u["prompt_tokens"] for u in usage)
        values["output_tokens"] = sum(u["completion_tokens"] for u in usage)
        values["cost_upper_bound_nanousd"] = (
            values["input_tokens"] * 300 + values["output_tokens"] * 1200
        )
    outcome = Outcome(
        instance_id=identity,
        mode=mode,
        protocol_hash=protocol_hash,
        input_hash=expected_hash,
        duration_ms=(time.monotonic_ns() - started) // 1_000_000,
        **values,
    )
    OutcomeLedger(output / "outcomes").append(outcome)
    return outcome

"""Run one immutable observation instance without loading evaluator labels."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agentops_incident_commander.domain import EvidenceGateDecision
from evaluation.autonomous_diagnosis import investigate
from evaluation.historical_context import MemoryReplaySource
from evaluation.live_gateway import local_definitions
from evaluation.observation_snapshot import SnapshotReadAdapter, load_snapshot, sanitize_output
from evaluation.outcome_ledger import OutcomeLedger
from evaluation.real_scoring import CAUSES, MODES, Outcome
from evaluation.structured_model import (
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredResult,
    fingerprint,
)


class ComparisonModel(StructuredEvaluationModel):
    history: tuple[dict[str, Any], ...] = ()

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
                "historical_references": list(self.history),
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
    memory_source: MemoryReplaySource | None = None,
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
    source_root = Path(__file__).resolve().parents[1]
    sources = (
        "evaluation/run_snapshot_comparison.py",
        "evaluation/autonomous_diagnosis.py",
        "evaluation/structured_model.py",
        "evaluation/live_evidence.py",
        "evaluation/live_gateway.py",
    )
    runtime = {
        "code_revision": subprocess.check_output(
            ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_hashes": {
            name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in sources
        },
        "protocol_hash": protocol_hash,
        "snapshot_hash": expected_hash,
        "evidence_clock": "CAPTURE_WINDOW_END_PLUS_ONE_SECOND",
        "provider_timing": "REAL_MONOTONIC",
    }
    with (run_root / "runtime.json").open("x", encoding="utf-8") as stream:
        json.dump(runtime, stream, sort_keys=True)
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
        if memory_source is not None:
            if mode != "controlled-graph-memory":
                raise ValueError("history is exclusive to memory comparison")
            model.history = asyncio.run(memory_source.for_incident(identity))
            (run_root / "mode.json").write_text(
                json.dumps(
                    {
                        "mode": mode,
                        "historical_reference_count": len(model.history),
                        "memory_status": "AUTHORIZED_RETRIEVAL",
                        "quality_comparison_eligible": True,
                    }
                ),
                encoding="utf-8",
            )
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
                evaluation_at=datetime.fromisoformat(snapshot["window_end"]) + timedelta(seconds=1),
            )
        )
        if services.report is None:
            raise ValueError("no completed report")
        report = services.report
        original = report.model_dump(mode="json")
        sanitized = sanitize_output(original)
        with (run_root / "diagnosis-report.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "report": sanitized,
                    "validated_report_hash": fingerprint(original),
                    "stored_report_hash": fingerprint(sanitized),
                    "redaction_applied": sanitized != original,
                },
                stream,
                sort_keys=True,
            )
            stream.flush()
            os.fsync(stream.fileno())
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
        frame = traceback.extract_tb(error.__traceback__)[-1]
        journal(
            {
                "event": "comparison.failed",
                "error_type": type(error).__name__,
                "failure_site": f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}",
            }
        )
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

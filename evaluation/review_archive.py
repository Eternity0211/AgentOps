"""Re-evaluate archived provider report bindings and evidence without inventing SQL traces."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    evaluate_evidence_gate,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    Evidence,
    EvidenceGateRules,
    EvidenceId,
    IncidentId,
    Principal,
    Role,
    TenantId,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.workflows import DiagnosisReport
from evaluation.structured_model import fingerprint


class ArchivedEvidence:
    def __init__(self, records: dict[EvidenceId, Evidence]) -> None:
        self.records = records

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        item = self.records.get(evidence_id)
        return (
            item
            if item and item.tenant_id == tenant_id and item.incident_id == incident_id
            else None
        )


def review_archive(root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic_ns()
    tasks: dict[str, str] = {"report_binding": "FAIL"}
    gate_outcomes = {}
    declared = unresolved = 0
    reason = None
    try:
        report_document = json.loads((root / "diagnosis-report.json").read_text(encoding="utf-8"))
        payload = report_document["report"]
        if (
            report_document["redaction_applied"]
            or fingerprint(payload) != report_document["stored_report_hash"]
            or report_document["stored_report_hash"] != report_document["validated_report_hash"]
        ):
            raise ValueError("report binding mismatch")
        report = DiagnosisReport.model_validate_json(json.dumps(payload))
        if report.incident_id != snapshot["instance_id"]:
            raise ValueError("report incident mismatch")
        events = [
            json.loads(line)
            for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        if not any(
            e.get("purpose") == "DIAGNOSE"
            and e.get("status") == "SUCCEEDED"
            and e.get("validated_output_hash") == report_document["validated_report_hash"]
            for e in events
        ):
            raise ValueError("validated model output binding unavailable")
        tasks["report_binding"] = "PASS"
        records = {}
        for path in (root / "evidence").glob("evidence-records*.json"):
            for row in json.loads(path.read_text(encoding="utf-8")):
                item = TypeAdapter(Evidence).validate_json(json.dumps(row["evidence"]).encode())
                if item.id in records:
                    raise ValueError("duplicate archived Evidence identity")
                records[item.id] = item
        principal = Principal(
            ActorId("simulated-reviewer"), TenantId("local-evaluation"), frozenset({Role.VIEWER})
        )
        at = datetime.fromisoformat(snapshot["window_end"]) + timedelta(seconds=1)

        async def review() -> None:
            nonlocal declared, unresolved
            for candidate in report.candidates:
                claim = report.evidence_gate_claim(candidate.candidate_id)
                resolution = await resolve_gate_evidence_references(
                    claim,
                    tenant_id=principal.tenant_id,
                    principal=principal,
                    reader=ArchivedEvidence(records),
                    artifact_storage=LocalArtifactStorage(root / "evidence"),
                    at=at,
                )
                declared += len(
                    set((*candidate.supporting_evidence_ids, *candidate.counter_evidence_ids))
                )
                unresolved += len(
                    set((*candidate.supporting_evidence_ids, *candidate.counter_evidence_ids))
                ) - len(resolution.verified_evidence)
                gate = evaluate_evidence_gate(claim, resolution, rules=EvidenceGateRules(), at=at)
                tasks["gate:" + candidate.candidate_id] = "PASS"
                gate_outcomes[candidate.candidate_id] = gate.outcome.value

        asyncio.run(review())
        if declared:
            tasks["citation_resolution"] = "PASS" if unresolved == 0 else "FAIL"
    except Exception as error:
        reason = type(error).__name__
        if tasks["report_binding"] == "PASS":
            tasks["evidence_review"] = "FAIL"
    return {
        "actor_kind": "DETERMINISTIC_EVALUATOR_NOT_HUMAN",
        "source_kind": "ARCHIVED_REAL_PROVIDER_OUTPUT",
        "instance_id": snapshot["instance_id"],
        "tasks": tasks,
        "gate_outcomes": gate_outcomes,
        "task_successes": sum(v == "PASS" for v in tasks.values()),
        "required_tasks": len(tasks),
        "declared_citations": declared,
        "unresolved_citations": unresolved,
        "failure_type": reason,
        "backend_review_ms": (time.monotonic_ns() - started) // 1_000_000,
        "approval_review": "NOT_APPLICABLE_NO_PROPOSAL",
        "approval_decided": False,
        "recovery_executed": False,
        "human_time_saved": None,
    }

"""Immutable local experiment Evidence records and the existing deterministic Gate."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    evaluate_evidence_gate,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    ArtifactId,
    Evidence,
    EvidenceBuildRequest,
    EvidenceGateRules,
    EvidenceId,
    EvidenceLineage,
    EvidenceNormalizer,
    EvidenceSourceType,
    IncidentId,
    NormalizedQuery,
    Principal,
    PromptInjectionStatus,
    QualitySignals,
    QueryParameter,
    RedactionTransformId,
    Role,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
    inspect_untrusted_telemetry,
    redact_sensitive_data,
)
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.workflows import DiagnosisReport


class ExperimentEvidence:
    def __init__(
        self,
        root: Path,
        incident: str,
        observations: list[dict[str, str]],
        *,
        observed_from: datetime,
    ) -> None:
        self.tenant = TenantId("local-evaluation")
        self.incident = IncidentId(incident)
        self.records: dict[EvidenceId, Evidence] = {}
        self.storage = LocalArtifactStorage(root)
        self.observations: list[dict[str, str]] = []
        now = datetime.now(UTC)
        source_types = {
            "metrics": EvidenceSourceType.METRIC,
            "logs": EvidenceSourceType.LOG,
            "traces": EvidenceSourceType.TRACE,
            "http-probes": EvidenceSourceType.METRIC,
        }
        manifest = []
        for observation in observations:
            identifier = observation["id"]
            artifact_id = ArtifactId(f"artifact-{incident}-{identifier}")
            redaction = redact_sensitive_data(
                observation["summary"],
                transform_id=RedactionTransformId(f"redaction-{identifier}"),
                lineage_key=secrets.token_bytes(32),
            )
            text = str(redaction.value)
            inspection = inspect_untrusted_telemetry(text, source_artifact_id=artifact_id)
            if inspection.status is PromptInjectionStatus.SUSPECTED:
                continue
            normalized = EvidenceNormalizer().normalize(
                EvidenceBuildRequest(
                    evidence_id=EvidenceId(identifier),
                    artifact_id=artifact_id,
                    tenant_id=self.tenant,
                    incident_id=self.incident,
                    source_type=source_types[observation["source"]],
                    source_instance=f"local-{observation['source']}",
                    tool_name="bounded_live_probe",
                    tool_version="1.0.0",
                    tool_schema_version="1.0.0",
                    normalized_query=NormalizedQuery(
                        (QueryParameter("source", observation["source"]),)
                    ),
                    observed_from=observed_from,
                    observed_to=now,
                    collected_at=now,
                    expires_at=now + timedelta(hours=1),
                    artifact_expires_at=now + timedelta(days=7),
                    parser_version="1.0.0",
                    normalizer_version="1.0.0",
                    quality_signals=QualitySignals(
                        True, False, int(text != "[]"), parser_warning_count=int(len(text) >= 2048)
                    ),
                    lineage=EvidenceLineage(
                        ToolCallId(f"call-{identifier}"),
                        WorkflowRunId(f"workflow-{incident}"),
                        redaction.transform_id,
                    ),
                    trust=TrustClassification.DIRECT_OBSERVATION,
                    prompt_injection_status=PromptInjectionStatus.NONE,
                    redaction_status=redaction.status,
                ),
                {"summary": text},
            )
            self.storage.store(normalized.artifact, normalized.content)
            self.records[normalized.evidence.id] = normalized.evidence
            self.observations.append({**observation, "summary": text})
            manifest.append(
                {"evidence": asdict(normalized.evidence), "artifact": asdict(normalized.artifact)}
            )
        with (root / "evidence-records.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, default=str, indent=2)

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None:
        if tenant_id != self.tenant or incident_id != self.incident:
            return None
        return self.records.get(evidence_id)

    def gate(self, report: DiagnosisReport) -> dict[str, Any]:
        async def evaluate() -> list[dict[str, Any]]:
            decisions = []
            for candidate in report.candidates:
                claim = report.evidence_gate_claim(candidate.candidate_id)
                now = datetime.now(UTC)
                resolution = await resolve_gate_evidence_references(
                    claim,
                    tenant_id=self.tenant,
                    principal=Principal(
                        ActorId("evaluation-reader"), self.tenant, frozenset({Role.VIEWER})
                    ),
                    reader=self,
                    artifact_storage=self.storage,
                    at=now,
                )
                decision = evaluate_evidence_gate(
                    claim, resolution, rules=EvidenceGateRules(), at=now
                )
                decisions.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "outcome": decision.outcome.value,
                        "resolved_references": len(resolution.verified_evidence),
                        "reasons": [reason.code.value for reason in decision.reasons],
                    }
                )
            return decisions

        return {
            "candidate_decisions": asyncio.run(evaluate()),
            "stored_evidence_count": len(self.records),
            "backend": "immutable-local-experiment",
        }

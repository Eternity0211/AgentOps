"""Immutable local experiment Evidence records and the existing deterministic Gate."""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
        provenance_by_id: dict[str, dict[str, Any]] | None = None,
        existing: ExperimentEvidence | None = None,
        tenant: str = "local-evaluation",
        workflow: str | None = None,
    ) -> None:
        self.tenant = TenantId(tenant)
        self.incident = IncidentId(incident)
        self.workflow = WorkflowRunId(workflow or f"workflow-{incident}")
        if existing is not None and (
            existing.incident != self.incident
            or existing.tenant != self.tenant
            or existing.workflow != self.workflow
        ):
            raise ValueError("cannot merge evidence across incidents")
        self.records: dict[EvidenceId, Evidence] = dict(existing.records) if existing else {}
        self.storage: LocalArtifactStorage = (
            existing.storage if existing else LocalArtifactStorage(root)
        )
        self.observations: list[dict[str, str]] = list(existing.observations) if existing else []
        self.batch: int = existing.batch + 1 if existing else 0
        now = datetime.now(UTC)
        source_types = {
            "metrics": EvidenceSourceType.METRIC,
            "logs": EvidenceSourceType.LOG,
            "traces": EvidenceSourceType.TRACE,
            "http-probes": EvidenceSourceType.METRIC,
            "deployments": EvidenceSourceType.DEPLOYMENT,
            "topology": EvidenceSourceType.TOPOLOGY,
        }
        manifest = []
        for observation in observations:
            identifier = observation["id"]
            if EvidenceId(identifier) in self.records:
                raise ValueError("evidence identity is immutable across investigation rounds")
            provenance = (provenance_by_id or {}).get(identifier, {})
            query_text = json.dumps(provenance, sort_keys=True, separators=(",", ":"))
            query_encoding = base64.urlsafe_b64encode(query_text.encode()).decode()
            query_fields = [QueryParameter("source", observation["source"])]
            if provenance:
                query_fields.append(QueryParameter("request_spec_encoding", "base64url-json-v1"))
                query_fields.extend(
                    QueryParameter(f"request_spec_{n:02d}", query_encoding[pos : pos + 480])
                    for n, pos in enumerate(range(0, len(query_encoding), 480))
                )
            artifact_id = ArtifactId(
                "artifact-"
                + hashlib.sha256(f"{tenant}:{incident}:{identifier}".encode()).hexdigest()
            )
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
                    tool_name=provenance.get("tool", "bounded_live_probe"),
                    tool_version=provenance.get("version", "1.0.0"),
                    tool_schema_version=provenance.get("version", "1.0.0"),
                    normalized_query=NormalizedQuery(tuple(query_fields)),
                    observed_from=observed_from,
                    observed_to=now,
                    collected_at=now,
                    expires_at=now + timedelta(hours=1),
                    artifact_expires_at=now + timedelta(days=7),
                    parser_version="1.0.0",
                    normalizer_version="1.0.0",
                    quality_signals=QualitySignals(
                        True,
                        False,
                        provenance.get("records_seen", int(text != "[]")),
                        records_dropped=provenance.get("dropped_records", 0),
                        parser_warning_count=(0 if provenance else int(len(text) >= 2048)),
                    ),
                    lineage=EvidenceLineage(
                        ToolCallId(provenance.get("call_id", f"call-{identifier}")),
                        self.workflow,
                        redaction.transform_id,
                    ),
                    trust=TrustClassification.DIRECT_OBSERVATION,
                    prompt_injection_status=PromptInjectionStatus.NONE,
                    redaction_status=redaction.status,
                ),
                {"summary": text, "provenance": query_text},
            )
            self.storage.store(normalized.artifact, normalized.content)
            self.records[normalized.evidence.id] = normalized.evidence
            self.observations.append({**observation, "summary": text})
            manifest.append(
                {"evidence": asdict(normalized.evidence), "artifact": asdict(normalized.artifact)}
            )
        name = "evidence-records.json" if self.batch == 0 else f"evidence-records-{self.batch}.json"
        with (root / name).open("x", encoding="utf-8") as stream:
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

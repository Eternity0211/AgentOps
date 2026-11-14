"""Real-model investigation through existing plan compiler, Gateway and LangGraph."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from itertools import pairwise
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    PlanningBudgets,
    ToolCallRequest,
    ToolGateway,
    ToolGatewayError,
    evaluate_evidence_gate,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    Artifact,
    CausationId,
    CorrelationId,
    Evidence,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateRules,
    EvidenceId,
    IncidentId,
    Principal,
    RedactionTransformId,
    Role,
    TenantId,
    ToolCallId,
    ToolRegistry,
    WorkflowRunId,
    redact_sensitive_data,
)
from agentops_incident_commander.infrastructure import diagnosis_checkpoint_serializer
from agentops_incident_commander.infrastructure.diagnosis_runtime import DiagnosisWorkflowRunner
from agentops_incident_commander.workflows import (
    ContextLoadResult,
    DiagnosisGraphState,
    DiagnosisProgressRecorder,
    DiagnosisReport,
    DiagnosisRuntimeContext,
    EvidencePersistenceResult,
    GateNodeResult,
    GateRoute,
    GraphBudgetState,
    GraphPhase,
    GraphPromptReference,
    HypothesisNodeResult,
    PlanNodeResult,
    PlanToolCallReference,
    build_diagnosis_graph,
)
from evaluation.baselines.controlled_graph import _Progress
from evaluation.durable_effects import StoredModelResult, WorkflowEffectStore
from evaluation.live_evidence import ExperimentEvidence
from evaluation.live_gateway import SERVICES, SOURCES, LocalReadAdapter, local_definitions
from evaluation.memory_evidence import GcPhase, MemorySample, assess_memory_series
from evaluation.registered_model import RegisteredModelInvoker
from evaluation.structured_model import (
    INSTRUCTIONS,
    InvestigationProposal,
    ModelPurpose,
    StructuredEvaluationModel,
    StructuredResult,
    compile_real_plan,
    fingerprint,
)


class JournalAudit:
    def __init__(self, journal: Callable[[dict[str, Any]], None]) -> None:
        self.journal = journal

    async def append(self, event: Any) -> None:
        self.journal(
            {
                "kind": "tool-audit",
                "event_type": event.type,
                "fingerprint": fingerprint(str(event)),
                "call_id": event.target.id.value,
                "correlation_id": event.correlation_id.value,
                "request_hash": event.request_hash.value if event.request_hash else None,
                "result_hash": event.result_hash.value if event.result_hash else None,
            }
        )


class FixedPromptReference:
    async def require_approved(
        self, state: DiagnosisGraphState, *, node_name: str, operation_id: str
    ) -> None:
        if state.prompt.content_fingerprint != fingerprint(INSTRUCTIONS):
            raise ValueError("evaluation prompt fingerprint mismatch")


class EvidenceStrategy(StrEnum):
    """Explicit evaluation-only evidence strategy; never an execution authority."""

    LEGACY = "legacy/1.0.0"
    GC_AWARE = "gc-aware/1.0.0"
    GC_AWARE_CAUSAL_SCOPE = "gc-aware-causal-scope/1.0.0"


def _completed_evidence_query(evidence: Evidence) -> tuple[str, str] | None:
    parameters = evidence.normalized_query.as_dict()
    encoded = "".join(
        value
        for name, value in sorted(parameters.items())
        if name.startswith("request_spec_") and name != "request_spec_encoding"
    )
    if not encoded:
        return None
    encoded += "=" * (-len(encoded) % 4)
    try:
        request = json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, json.JSONDecodeError):
        return None
    tool, service = request.get("tool"), request.get("service")
    if isinstance(tool, str) and isinstance(service, str):
        return tool, service
    return None


def _attribute_value(attribute: dict[str, Any]) -> object | None:
    value = attribute.get("value")
    if not isinstance(value, dict):
        return None
    for name in ("intValue", "doubleValue", "stringValue", "boolValue"):
        if name in value:
            result: object = value[name]
            return result
    return None


def memory_retention_by_service(
    observations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Extract chronological, Evidence-bound retained-memory facts from trace summaries."""
    grouped: dict[str, dict[tuple[int, int], dict[str, Any]]] = {}
    for observation in observations:
        if observation.get("source") != "traces":
            continue
        try:
            spans = json.loads(observation["summary"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict) or not isinstance(span.get("attributes"), list):
                continue
            attributes = {
                item.get("key"): _attribute_value(item)
                for item in span["attributes"]
                if isinstance(item, dict) and isinstance(item.get("key"), str)
            }
            retained = attributes.get("process.memory.retained_bytes")
            timestamp: object = span.get("end") or span.get("start")
            service = span.get("service")
            if (
                not isinstance(retained, (str, int))
                or isinstance(retained, bool)
                or not isinstance(timestamp, (str, int))
                or isinstance(timestamp, bool)
            ):
                continue
            try:
                retained_value, timestamp_value = int(retained), int(timestamp)
            except (TypeError, ValueError):
                continue
            if not isinstance(service, str) or not service:
                continue
            sample = grouped.setdefault(service, {}).setdefault(
                (timestamp_value, retained_value),
                {
                    "observed_at_unix_nano": timestamp_value,
                    "retained_bytes": retained_value,
                    "retention_limit_bytes": attributes.get("process.memory.retention_limit_bytes"),
                    "retention_allocations": attributes.get("process.memory.retention_allocations"),
                    "evidence_ids": [],
                },
            )
            if observation["id"] not in sample["evidence_ids"]:
                sample["evidence_ids"].append(observation["id"])
    result = []
    for service, keyed_samples in sorted(grouped.items()):
        samples = sorted(keyed_samples.values(), key=lambda item: item["observed_at_unix_nano"])
        values = [item["retained_bytes"] for item in samples]
        changes = [right - left for left, right in pairwise(values)]
        direction = (
            "SINGLE_SAMPLE"
            if not changes
            else "INCREASING"
            if all(change > 0 for change in changes)
            else "DECREASING"
            if all(change < 0 for change in changes)
            else "FLAT_OR_MIXED"
        )
        result.append(
            {
                "service": service,
                "sample_count": len(samples),
                "first_retained_bytes": values[0],
                "last_retained_bytes": values[-1],
                "delta_bytes": values[-1] - values[0],
                "direction": direction,
                "sustained_increase_observed": len(samples) >= 3
                and all(change > 0 for change in changes),
                "samples": samples,
            }
        )
    return result


def discriminative_memory_retention_by_service(
    observations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Build GC-aware candidate facts without upgrading missing data into proof."""
    grouped: dict[str, list[MemorySample]] = {}
    for observation in observations:
        if observation.get("source") != "traces":
            continue
        try:
            spans = json.loads(observation["summary"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(spans, list):
            continue
        for span in spans:
            if not isinstance(span, dict) or not isinstance(span.get("attributes"), list):
                continue
            attributes = {
                item.get("key"): _attribute_value(item)
                for item in span["attributes"]
                if isinstance(item, dict) and isinstance(item.get("key"), str)
            }

            def integer(value: object) -> int:
                if isinstance(value, bool) or not isinstance(value, (str, int)):
                    raise ValueError("invalid memory integer")
                return int(value)

            try:
                phase_value = attributes.get("process.memory.gc.phase")
                phase = GcPhase(str(phase_value)) if phase_value is not None else None
                cycle_value = attributes.get("process.memory.gc.cycle")
                sample = MemorySample(
                    integer(span.get("end") or span["start"]),
                    integer(attributes["process.memory.retained_bytes"]),
                    integer(attributes.get("process.memory.retention_allocations", 0)),
                    integer(attributes.get("process.memory.retention_releases", 0)),
                    integer(attributes["process.memory.retention_limit_bytes"]),
                    (observation["id"],),
                    None if cycle_value is None else integer(cycle_value),
                    phase,
                )
            except (KeyError, TypeError, ValueError):
                continue
            service = span.get("service")
            if isinstance(service, str) and service:
                grouped.setdefault(service, []).append(sample)
    facts: list[dict[str, Any]] = []
    for service, samples in sorted(grouped.items()):
        try:
            assessment = assess_memory_series(tuple(samples))
        except ValueError:
            facts.append({"service": service, "classification": "INVALID_SERIES"})
            continue
        facts.append(
            {
                "service": service,
                "classification": assessment.pattern.value,
                "reason": assessment.reason,
                "sample_count": assessment.sample_count,
                "delta_bytes": assessment.delta_bytes,
                "slope_bytes_per_second": assessment.slope_bytes_per_second,
                "net_allocation_count": assessment.net_allocation_count,
                "gc_pair_count": assessment.gc_pair_count,
                "reclaimed_bytes_after_gc": assessment.reclaimed_bytes_after_gc,
                "evidence_ids": list(assessment.evidence_ids),
            }
        )
    return facts


def build_candidate_diagnosis_context(
    all_observations: list[dict[str, str]],
    failed_reads: dict[str, dict[str, Any]],
    *,
    byte_budget: int = 24_000,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Candidate context that replaces the three-rise heuristic with GC-aware facts."""
    selected, temporally_excluded = _select_alert_window(
        all_observations, window_start=window_start, window_end=window_end
    )
    context = _build_diagnosis_context(
        selected,
        failed_reads,
        byte_budget=byte_budget,
        memory_facts=discriminative_memory_retention_by_service(selected),
        temporally_excluded_evidence_ids=temporally_excluded,
    )
    context["memory_evidence_contract"] = "gc-aware/1.0.0"
    return context


def _memory_fact_evidence_ids(fact: dict[str, Any]) -> list[str]:
    direct = fact.get("evidence_ids")
    if isinstance(direct, list):
        return [item for item in direct if isinstance(item, str)]
    return [
        evidence_id
        for sample in fact.get("samples", [])
        if isinstance(sample, dict)
        for evidence_id in sample.get("evidence_ids", [])
        if isinstance(evidence_id, str)
    ]


def deployment_facts(observations: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Retain bounded version facts without inferring that deployment caused an incident."""
    facts: list[dict[str, Any]] = []
    for observation in observations:
        if observation.get("source") != "deployments":
            continue
        try:
            rows = json.loads(observation["summary"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            facts.append(
                {
                    "evidence_id": observation["id"],
                    "service": row.get("service"),
                    "version": row.get("version"),
                    "previous_version": row.get("previous_version"),
                    "causal_inference": "NOT_ESTABLISHED_BY_DEPLOYMENT_RECORD",
                }
            )
    return facts


def alert_aligned_service_facts(
    observations: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Summarize bounded latency/error signals and surface exact-record contradictions."""
    grouped: dict[str, dict[str, Any]] = {}
    identities: dict[tuple[str, str, str, str], tuple[str, str]] = {}
    contradictions: dict[str, set[str]] = {}
    for observation in observations:
        if observation.get("source") != "traces":
            continue
        try:
            records = json.loads(observation["summary"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("service"), str):
                continue
            service = record["service"]
            attributes = {
                item.get("key"): _attribute_value(item)
                for item in record.get("attributes", [])
                if isinstance(item, dict) and isinstance(item.get("key"), str)
            }
            raw_status = attributes.get("http.response.status_code") or attributes.get(
                "http_response_status_code"
            )
            span_status = record.get("status")
            try:
                status_is_error = (
                    isinstance(raw_status, (str, int))
                    and not isinstance(raw_status, bool)
                    and int(raw_status) >= 500
                )
            except (TypeError, ValueError):
                status_is_error = False
            is_error = status_is_error or (
                isinstance(span_status, dict)
                and span_status.get("code") in (2, "STATUS_CODE_ERROR")
            )
            outcome = "ERROR" if is_error else "SUCCESS"
            identity = (
                service,
                str(record.get("name")),
                str(record.get("start")),
                str(record.get("end")),
            )
            previous = identities.get(identity)
            if previous is not None and previous[0] != outcome:
                contradictions.setdefault(service, set()).update((previous[1], observation["id"]))
            else:
                identities[identity] = (outcome, observation["id"])
            fact = grouped.setdefault(
                service,
                {"success_count": 0, "error_count": 0, "durations_ms": [], "evidence_ids": set()},
            )
            fact["success_count" if outcome == "SUCCESS" else "error_count"] += 1
            fact["evidence_ids"].add(observation["id"])
            try:
                start, end = int(record["start"]), int(record["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if end >= start:
                fact["durations_ms"].append((end - start) / 1_000_000)
    result: list[dict[str, Any]] = []
    for service, fact in sorted(grouped.items()):
        durations = sorted(fact.pop("durations_ms"))
        conflicting = sorted(contradictions.get(service, set()))
        result.append(
            {
                "service": service,
                "classification": "CONTRADICTORY" if conflicting else "OBSERVED",
                "success_count": fact["success_count"],
                "error_count": fact["error_count"],
                "p95_duration_ms": (
                    durations[max(0, (95 * len(durations) + 99) // 100 - 1)] if durations else None
                ),
                "evidence_ids": sorted(fact["evidence_ids"]),
                "contradictory_evidence_ids": conflicting,
            }
        )
    return result


def _record_attributes(record: dict[str, Any]) -> dict[str, object | None]:
    return {
        item["key"]: _attribute_value(item)
        for item in record.get("attributes", [])
        if isinstance(item, dict) and isinstance(item.get("key"), str)
    }


def _record_is_error(record: dict[str, Any], attributes: dict[str, object | None]) -> bool:
    raw_status = attributes.get("http.response.status_code") or attributes.get(
        "http_response_status_code"
    )
    try:
        status_is_error = (
            isinstance(raw_status, (str, int))
            and not isinstance(raw_status, bool)
            and int(raw_status) >= 500
        )
    except (TypeError, ValueError):
        status_is_error = False
    span_status = record.get("status")
    return status_is_error or (
        isinstance(span_status, dict) and span_status.get("code") in (2, "STATUS_CODE_ERROR")
    )


def _has_decisive_service_reads(service: str, completed_queries: set[tuple[str, str]]) -> bool:
    return ("query_deployments", service) in completed_queries and any(
        (tool, service) in completed_queries
        for tool in ("query_logs", "query_metrics", "query_traces")
    )


def required_downstream_causal_scope(
    observations: list[dict[str, str]],
    completed_queries: set[tuple[str, str]],
) -> str | None:
    """Select one deepest observed failing dependency that still lacks decisive reads."""
    edges: dict[str, set[str]] = {}
    error_targets: set[str] = set()
    for observation in observations:
        try:
            records = json.loads(observation["summary"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(records, list):
            continue
        if observation.get("source") == "topology":
            for record in records:
                if not isinstance(record, dict):
                    continue
                source, target = record.get("source"), record.get("target")
                if source in SERVICES and target in SERVICES:
                    edges.setdefault(source, set()).add(target)
        if observation.get("source") not in ("traces", "logs"):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            attributes = _record_attributes(record)
            stream = record.get("stream")
            if isinstance(stream, dict):
                attributes.update(stream)
            target = attributes.get("server.address") or attributes.get("server_address")
            if target in SERVICES and _record_is_error(record, attributes):
                error_targets.add(target)

    observed_services = {
        service for tool, service in completed_queries if tool in ("query_traces", "query_logs")
    }
    topology_targets = {target for targets in edges.values() for target in targets}
    roots = sorted(observed_services - topology_targets) or sorted(observed_services)
    depths: dict[str, int] = {service: 0 for service in roots}
    frontier = list(roots)
    while frontier:
        source = frontier.pop(0)
        for target in sorted(edges.get(source, set())):
            proposed = depths[source] + 1
            if target not in depths or proposed < depths[target]:
                depths[target] = proposed
                frontier.append(target)

    observed_targets = [service for service in error_targets if depths.get(service, 0) > 0]
    if not observed_targets:
        return None
    target = max(observed_targets, key=lambda service: (depths[service], service))
    return None if _has_decisive_service_reads(target, completed_queries) else target


def build_diagnosis_context(
    all_observations: list[dict[str, str]],
    failed_reads: dict[str, dict[str, Any]],
    *,
    byte_budget: int = 24_000,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> dict[str, Any]:
    """Build auditable bounded context while retaining compact cross-record facts."""
    selected, temporally_excluded = _select_alert_window(
        all_observations, window_start=window_start, window_end=window_end
    )
    return _build_diagnosis_context(
        selected,
        failed_reads,
        byte_budget=byte_budget,
        memory_facts=memory_retention_by_service(selected),
        temporally_excluded_evidence_ids=temporally_excluded,
    )


def _select_alert_window(
    observations: list[dict[str, str]],
    *,
    window_start: datetime | None,
    window_end: datetime | None,
) -> tuple[list[dict[str, str]], list[str]]:
    if (window_start is None) != (window_end is None):
        raise ValueError("alert window requires both start and end")
    if window_start is None or window_end is None:
        return observations, []
    if window_start.tzinfo is None or window_end.tzinfo is None or window_start >= window_end:
        raise ValueError("alert window must be timezone-aware and increasing")
    selected: list[dict[str, str]] = []
    excluded: list[str] = []
    for observation in observations:
        try:
            observed_from = datetime.fromisoformat(observation["observed_from"])
            observed_to = datetime.fromisoformat(observation["observed_to"])
        except (KeyError, TypeError, ValueError):
            excluded.append(observation["id"])
            continue
        if (
            observed_from.tzinfo is None
            or observed_to.tzinfo is None
            or observed_from > observed_to
            or observed_to < window_start
            or observed_from > window_end
        ):
            excluded.append(observation["id"])
            continue
        selected.append(observation)
    return selected, excluded


def _build_diagnosis_context(
    all_observations: list[dict[str, str]],
    failed_reads: dict[str, dict[str, Any]],
    *,
    byte_budget: int,
    memory_facts: list[dict[str, Any]],
    temporally_excluded_evidence_ids: list[str],
) -> dict[str, Any]:
    if byte_budget <= 0:
        raise ValueError("diagnosis context byte budget must be positive")
    deployment_records = deployment_facts(all_observations)
    service_records = alert_aligned_service_facts(all_observations)
    all_compact_fact_evidence_ids = sorted(
        {evidence_id for fact in memory_facts for evidence_id in _memory_fact_evidence_ids(fact)}
        | {fact["evidence_id"] for fact in deployment_records}
        | {evidence_id for fact in service_records for evidence_id in fact["evidence_ids"]}
    )
    compact_fact_bytes = len(
        json.dumps(
            {
                "memory_retention_by_service": memory_facts,
                "deployment_facts": deployment_records,
                "alert_aligned_service_facts": service_records,
            },
            sort_keys=True,
        ).encode()
    )
    excluded_compact_fact_evidence_ids: list[str] = []
    if compact_fact_bytes > byte_budget:
        excluded_compact_fact_evidence_ids = all_compact_fact_evidence_ids
        memory_facts = []
        deployment_records = []
        service_records = []
        compact_fact_bytes = 0
    observations: list[dict[str, str]] = []
    excluded: list[str] = []
    used = compact_fact_bytes
    for item in sorted(all_observations, key=lambda value: value["source"] != "traces"):
        size = len(json.dumps(item, sort_keys=True).encode())
        if used + size > byte_budget:
            excluded.append(item["id"])
            continue
        observations.append(item)
        used += size
    unavailable = [
        {
            "call_id": call_id,
            "source": value["source"],
            "tool_name": value["tool_name"],
            "error_code": value["error_code"],
            "attempts": value["attempts"],
        }
        for call_id, value in sorted(failed_reads.items())
    ]
    compact_fact_evidence_ids = sorted(
        {evidence_id for fact in memory_facts for evidence_id in _memory_fact_evidence_ids(fact)}
        | {fact["evidence_id"] for fact in deployment_records}
        | {evidence_id for fact in service_records for evidence_id in fact["evidence_ids"]}
    )
    admitted_evidence_ids = [item["id"] for item in observations]
    referenceable_evidence_ids = list(
        dict.fromkeys([*admitted_evidence_ids, *compact_fact_evidence_ids])
    )
    return {
        "evidence_ids": referenceable_evidence_ids,
        "observations": observations,
        "memory_retention_by_service": memory_facts,
        "deployment_facts": deployment_records,
        "alert_aligned_service_facts": service_records,
        "unavailable_reads": unavailable,
        "context_budget": {
            "limit_bytes": byte_budget,
            "admitted_bytes": used,
            "raw_observation_bytes": used - compact_fact_bytes,
            "compact_fact_bytes": compact_fact_bytes,
            "admitted_evidence_ids": admitted_evidence_ids,
            "compact_fact_evidence_ids": compact_fact_evidence_ids,
            "excluded_evidence_ids": excluded,
            "excluded_compact_fact_evidence_ids": excluded_compact_fact_evidence_ids,
            "temporally_excluded_evidence_ids": temporally_excluded_evidence_ids,
        },
    }


class WorkflowEvidenceStore(Protocol):
    async def add(self, evidence: Evidence, artifact: Artifact) -> None: ...

    async def get(
        self, evidence_id: EvidenceId, *, tenant_id: TenantId, incident_id: IncidentId
    ) -> Evidence | None: ...


class AutonomousServices:
    def __init__(
        self,
        model: StructuredEvaluationModel,
        gateway: ToolGateway,
        registry: ToolRegistry,
        incident: str,
        alert: str,
        root: Path,
        start: datetime,
        evidence_store: WorkflowEvidenceStore | None = None,
        model_invoker: RegisteredModelInvoker | None = None,
        effects: WorkflowEffectStore | None = None,
        end: datetime | None = None,
        allow_incomplete_reads: bool = False,
        evidence_strategy: EvidenceStrategy = EvidenceStrategy.LEGACY,
    ) -> None:
        if end is None or start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("autonomous evidence window must be timezone-aware and increasing")
        self.model, self.gateway, self.registry = model, gateway, registry
        self.incident, self.alert, self.root, self.start, self.end = (
            incident,
            alert,
            root,
            start,
            end,
        )
        self.compiled: Any = None
        self.results: dict[str, dict[str, Any]] = {}
        self.evidence: ExperimentEvidence | None = None
        self.report: DiagnosisReport | None = None
        self.gates: list[EvidenceGateDecision] = []
        self.principal = Principal(
            ActorId("evaluation-operator"), TenantId("local-evaluation"), frozenset({Role.OPERATOR})
        )
        if model_invoker is not None:
            self.principal = model_invoker.principal
        self.model_invoker = model_invoker
        self.usage: list[dict[str, int]] = []
        self.resumed = False
        self.round = 0
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.persisted_evidence = evidence_store
        self.scope = hashlib.sha256(incident.encode()).hexdigest()[:16]
        self.effects = effects
        self.allow_incomplete_reads = allow_incomplete_reads
        self.evidence_strategy = evidence_strategy
        self.completed_queries: set[tuple[str, str]] = set()
        self.required_causal_scope: str | None = None
        self.failed_reads: dict[str, dict[str, Any]] = {}
        self.input_hash = fingerprint(
            {
                "alert": alert,
                "evidence_strategy": evidence_strategy.value,
                "start": start.isoformat(),
                "end": end.isoformat() if end else None,
                "instructions": INSTRUCTIONS,
                "catalog": [
                    {
                        "name": d.name,
                        "version": d.semantic_version.value,
                        "input": d.input_schema.as_dict(),
                        "output": d.output_schema.as_dict(),
                    }
                    for d in gateway.diagnosis_catalog()
                ],
                "sources": {
                    name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                    for name in (
                        "autonomous_diagnosis.py",
                        "durable_effects.py",
                        "live_evidence.py",
                        "live_gateway.py",
                        "structured_model.py",
                    )
                },
            }
        )

    def effect_binding(self, state: DiagnosisGraphState) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "graph_version": state.graph_version,
            "state_schema_version": state.state_schema_version,
            "tenant_id": state.tenant_id,
            "incident_id": state.incident_id,
            "workflow_run_id": state.workflow_run_id,
            "actor_id": self.principal.actor_id.value,
            "correlation_id": state.correlation_id,
            "causation_id": state.causation_id,
            "input_hash": self.input_hash,
            "prompt": state.prompt.model_dump(mode="json"),
        }

    async def invoke_model_effect(
        self, state: DiagnosisGraphState, purpose: ModelPurpose, context: dict[str, Any]
    ) -> StructuredResult:
        async def invoke() -> dict[str, Any]:
            result = await self.invoke_model(purpose, context, self.round + 1)
            return StoredModelResult.capture(result).model_dump(mode="json")

        if self.effects is None:
            return await self.invoke_model(purpose, context, self.round + 1)
        value = await self.effects.execute(
            f"model:{purpose.value}:r{self.round}", self.effect_binding(state), invoke
        )
        return StoredModelResult.model_validate_json(json.dumps(value)).restore(purpose)

    async def restore_plan(self, state: DiagnosisGraphState) -> None:
        self.round = state.budgets.used_replans
        if self.compiled is not None:
            return
        if self.effects is None:
            raise ValueError("durable plan unavailable for resumed investigation")
        value = await self.effects.load(f"model:PLAN:r{self.round}", self.effect_binding(state))
        if value is None:
            raise ValueError("checkpoint plan effect missing")
        result = StoredModelResult.model_validate_json(json.dumps(value)).restore(ModelPurpose.PLAN)
        count = len(cast(InvestigationProposal, result.output).tool_calls)
        remaining = 12 - (len(state.tool_call_ids) - count)
        self.compiled = compile_real_plan(
            result,
            self.registry,
            PlanningBudgets(min(8, remaining), 4, 160000, 32000, 1000000000),
            prior_query_fingerprints=frozenset(state.tool_query_fingerprints[:-count]),
        )
        references = tuple(self.call_id(call.step_id) for call in self.compiled.calls)
        if (
            references != state.tool_call_ids[-count:]
            or tuple(call.query_fingerprint for call in self.compiled.calls)
            != state.tool_query_fingerprints[-count:]
        ):
            raise ValueError("checkpoint plan references changed")

    def call_id(self, step_id: str) -> str:
        return f"call-{self.scope}-r{self.round}-{step_id}"

    async def invoke_model(
        self, purpose: ModelPurpose, context: dict[str, Any], attempt: int
    ) -> StructuredResult:
        if self.model_invoker is not None:
            return await self.model_invoker.invoke(purpose, context, attempt=attempt)
        return await asyncio.to_thread(self.model.invoke, purpose, context)

    async def load_context(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> ContextLoadResult:
        return ContextLoadResult()

    async def prior_tool_queries(self, state: DiagnosisGraphState) -> list[dict[str, Any]]:
        if not state.budgets.used_replans:
            return []
        compiled = self.compiled
        if self.effects is not None:
            saved = await self.effects.load("model:PLAN:r0", self.effect_binding(state))
            if saved is None:
                raise ValueError("prior plan effect missing for replanning")
            compiled = compile_real_plan(
                StoredModelResult.model_validate_json(json.dumps(saved)).restore(ModelPurpose.PLAN),
                self.registry,
                PlanningBudgets(8, 4, 160000, 32000, 1000000000),
            )
        if compiled is None or tuple(c.query_fingerprint for c in compiled.calls) != tuple(
            state.tool_query_fingerprints
        ):
            raise ValueError("prior plan queries do not match checkpoint")
        return [
            {
                "tool_name": c.tool_name,
                "tool_version": c.tool_version.value,
                "arguments": json.loads(c.arguments_json),
                "query_fingerprint": c.query_fingerprint,
            }
            for c in compiled.calls
        ]

    def refresh_required_causal_scope(self) -> None:
        if self.evidence_strategy is not EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE:
            self.required_causal_scope = None
            return
        top_candidate = (
            self.report.candidates[0].candidate_id
            if self.report is not None and self.report.candidates
            else None
        )
        if self.required_causal_scope is None and top_candidate != "http-500":
            return
        observed = required_downstream_causal_scope(
            self.evidence.observations if self.evidence is not None else [],
            self.completed_queries,
        )
        if observed is not None:
            self.required_causal_scope = observed
        elif self.required_causal_scope is not None and _has_decisive_service_reads(
            self.required_causal_scope, self.completed_queries
        ):
            self.required_causal_scope = None

    async def plan(self, state: DiagnosisGraphState, *, operation_id: str) -> PlanNodeResult:
        self.round = state.budgets.used_replans
        if state.evidence_ids and self.evidence is None:
            await self.restore_evidence(state, completed_round=self.round - 1)
        if state.budgets.used_replans and self.report is None:
            await self.restore_report(state, self.round - 1)
        if state.budgets.used_replans:
            self.refresh_required_causal_scope()
        remaining = 12 - state.budgets.used_tool_calls
        context = {
            "incident_id": self.incident,
            "alert": self.alert,
            "environment": "local",
            "read_only": True,
            "budgets": {"steps": min(8, remaining), "parallelism": 4, "calls": remaining},
            "previous_missing_evidence": list(self.report.missing_evidence)
            + [m for c in self.report.candidates for m in c.missing_evidence]
            if self.report
            else [],
            "previous_evidence": self.evidence.observations[:2] if self.evidence else [],
            "required_causal_scope": (
                {
                    "service": self.required_causal_scope,
                    "required_reads": [
                        "query_deployments",
                        "one of query_logs/query_metrics/query_traces",
                    ],
                    "reason": (
                        "A current failing downstream dependency was observed, but its own "
                        "configuration and telemetry Evidence are absent."
                    ),
                }
                if self.required_causal_scope is not None
                else None
            ),
            "prior_queries": [call for call in state.tool_query_fingerprints],
            "prior_tool_queries": await self.prior_tool_queries(state),
            "replan_instruction": (
                "Do not repeat prior tool/version/argument combinations. "
                "Request only missing evidence."
            ),
            "catalog": [
                {
                    "name": d.name,
                    "version": d.semantic_version.value,
                    "input_schema": d.input_schema.as_dict(),
                    "source": {
                        "metrics": "METRIC",
                        "logs": "LOG",
                        "traces": "TRACE",
                        "deployments": "DEPLOYMENT",
                        "topology": "TOPOLOGY",
                    }[SOURCES[d.name]],
                }
                for d in self.gateway.diagnosis_catalog()
            ],
        }
        result = await self.invoke_model_effect(state, ModelPurpose.PLAN, context)
        self.compiled = compile_real_plan(
            result,
            self.registry,
            PlanningBudgets(min(8, remaining), 4, 160000, 32000, 1000000000),
            prior_query_fingerprints=frozenset(state.tool_query_fingerprints),
        )
        self.usage.append({"input": result.input_tokens, "output": result.output_tokens})
        references = tuple(
            PlanToolCallReference(
                call_id=self.call_id(call.step_id),
                step_id=call.step_id,
                tool_name=call.tool_name,
                tool_version=call.tool_version.value,
            )
            for call in self.compiled.calls
        )
        return PlanNodeResult(
            result.call_id or f"model-{self.scope}-plan-{self.round}",
            self.compiled.plan,
            references,
            tuple(call.query_fingerprint for call in self.compiled.calls),
            len(references),
            result.input_tokens + result.output_tokens,
            result.cost_upper_bound_nanousd,
        )

    async def load_tool_batches(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> tuple[tuple[str, ...], ...]:
        await self.restore_plan(state)
        groups = sorted({call.parallel_group for call in self.compiled.calls})
        return tuple(
            tuple(
                self.call_id(call.step_id)
                for call in self.compiled.calls
                if call.parallel_group == group
            )
            for group in groups
        )

    async def execute_read_tool(
        self, state: DiagnosisGraphState, tool_call_id: str, *, operation_id: str
    ) -> None:
        await self.restore_plan(state)
        selected = next(
            call for call in self.compiled.calls if self.call_id(call.step_id) == tool_call_id
        )
        request = ToolCallRequest(
            call_id=ToolCallId(tool_call_id),
            tool_name=selected.tool_name,
            tool_version=selected.tool_version,
            incident_id=IncidentId(self.incident),
            workflow_run_id=WorkflowRunId(state.workflow_run_id),
            principal=self.principal,
            correlation_id=CorrelationId(state.correlation_id),
            causation_id=CausationId(state.causation_id),
            arguments_json=selected.arguments_json,
        )

        async def invoke() -> dict[str, Any]:
            try:
                result = await self.gateway.invoke_diagnosis(request)
            except ToolGatewayError as error:
                if not self.allow_incomplete_reads:
                    raise
                return {
                    "tool_failure": True,
                    "error_code": error.code,
                    "attempts": error.attempts,
                    "source": SOURCES[selected.tool_name],
                    "tool_name": selected.tool_name,
                }
            value = result.result()
            if self.effects is not None:
                redaction = redact_sensitive_data(
                    value,
                    transform_id=RedactionTransformId("durable-read-result"),
                    lineage_key=secrets.token_bytes(32),
                )
                return cast(dict[str, Any], redaction.value)
            return value

        value = (
            await self.effects.execute(
                f"read:{tool_call_id}",
                self.effect_binding(state) | {"query_fingerprint": selected.query_fingerprint},
                invoke,
            )
            if self.effects is not None
            else await invoke()
        )
        if value.get("tool_failure") is True:
            self.failed_reads[tool_call_id] = value
        else:
            self.results[tool_call_id] = value
            arguments = json.loads(selected.arguments_json)
            service = arguments.get("service")
            if isinstance(service, str):
                self.completed_queries.add((selected.tool_name, service))

    async def persist_evidence(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> EvidencePersistenceResult:
        await self.restore_plan(state)
        if state.evidence_ids and self.evidence is None:
            await self.restore_evidence(state, completed_round=self.round - 1)
        for call in self.compiled.calls:
            identifier = self.call_id(call.step_id)
            if identifier in self.failed_reads:
                continue
            if identifier not in self.results:
                value = (
                    await self.effects.load(
                        f"read:{identifier}",
                        self.effect_binding(state) | {"query_fingerprint": call.query_fingerprint},
                    )
                    if self.effects is not None
                    else None
                )
                if value is None:
                    raise ValueError("checkpoint read result missing")
                if value.get("tool_failure") is True and self.allow_incomplete_reads:
                    self.failed_reads[identifier] = value
                    continue
                self.results[identifier] = value
                arguments = json.loads(call.arguments_json)
                service = arguments.get("service")
                if isinstance(service, str):
                    self.completed_queries.add((call.tool_name, service))
        if self.effects is None:
            return await self._persist_evidence(state)

        async def persist() -> dict[str, Any]:
            result = await self._persist_evidence(state)
            return {"evidence_ids": list(result.evidence_ids)}

        value = await self.effects.execute(
            f"evidence:r{self.round}", self.effect_binding(state), persist
        )
        identifiers = tuple(value["evidence_ids"])
        if self.evidence is None:
            await self.restore_evidence(
                state.model_copy(
                    update={
                        "evidence_ids": tuple(dict.fromkeys((*state.evidence_ids, *identifiers)))
                    }
                )
            )
        return EvidencePersistenceResult(identifiers)

    async def _persist_evidence(self, state: DiagnosisGraphState) -> EvidencePersistenceResult:
        observations, provenance = [], {}
        for call in self.compiled.calls:
            call_identifier = self.call_id(call.step_id)
            if call_identifier in self.failed_reads:
                failure = self.failed_reads[call_identifier]
                identifier = f"ev-{self.scope}-r{self.round}-{call.step_id}"
                observations.append(
                    {
                        "id": identifier,
                        "source": failure["source"],
                        "summary": json.dumps(
                            {
                                "status": "UNAVAILABLE",
                                "error_code": failure["error_code"],
                            },
                            sort_keys=True,
                        ),
                    }
                )
                provenance[identifier] = {
                    "tool": failure["tool_name"],
                    "version": call.tool_version.value,
                    "records_seen": 0,
                    "source_available": False,
                    "error_code": failure["error_code"],
                    "attempts": failure["attempts"],
                    "call_id": call_identifier,
                }
                continue
            record = self.results[call_identifier]
            scope = hashlib.sha256(self.incident.encode()).hexdigest()[:16]
            identifier = f"ev-{scope}-r{self.round}-{call.step_id}"
            observations.append(
                {"id": identifier, "source": record["source"], "summary": record["summary"]}
            )
            provenance[identifier] = {
                **json.loads(record["provenance"]),
                "records_seen": record["records_seen"],
                "call_id": self.call_id(call.step_id),
            }
        self.evidence = ExperimentEvidence(
            self.root,
            self.incident,
            observations,
            observed_from=self.start,
            observed_to=self.end,
            at=self.clock(),
            provenance_by_id=provenance,
            existing=self.evidence,
            tenant=self.principal.tenant_id.value,
            workflow=state.workflow_run_id,
        )
        if not self.evidence.records and not self.failed_reads:
            raise ValueError("all telemetry quarantined")
        if self.persisted_evidence is not None:
            for item in self.evidence.records.values():
                if item.id.value in state.evidence_ids:
                    continue
                content = self.evidence.storage.retrieve(
                    item.artifact_id,
                    incident_id=item.incident_id,
                    principal=self.principal,
                    at=self.clock(),
                )
                await self.persisted_evidence.add(item, content.artifact)
        return EvidencePersistenceResult(
            tuple(
                item.value for item in self.evidence.records if item.value not in state.evidence_ids
            )
        )

    async def restore_evidence(
        self, state: DiagnosisGraphState, *, completed_round: int | None = None
    ) -> None:
        if self.evidence is None and self.persisted_evidence is not None:
            records = []
            for identifier in state.evidence_ids:
                record = await self.persisted_evidence.get(
                    EvidenceId(identifier),
                    tenant_id=self.principal.tenant_id,
                    incident_id=IncidentId(self.incident),
                )
                if record is None:
                    raise ValueError("checkpoint evidence is unavailable")
                records.append(record)
            self.evidence = ExperimentEvidence.restore(
                self.root,
                records,
                principal=self.principal,
                incident=self.incident,
                workflow=state.workflow_run_id,
                batch=state.budgets.used_replans if completed_round is None else completed_round,
                at=self.clock(),
            )
        assert self.evidence is not None
        restored_records: object = getattr(self.evidence, "records", None)
        if isinstance(restored_records, dict):
            completed_queries: set[tuple[str, str]] = getattr(self, "completed_queries", set())
            completed_queries.update(
                query
                for record in cast(dict[EvidenceId, Evidence], restored_records).values()
                if (query := _completed_evidence_query(record)) is not None
            )
            self.completed_queries = completed_queries

    async def hypothesize(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> HypothesisNodeResult:
        await self.restore_evidence(state)
        assert self.evidence is not None
        context_builder = (
            build_diagnosis_context
            if self.evidence_strategy is EvidenceStrategy.LEGACY
            else build_candidate_diagnosis_context
        )
        context = context_builder(
            self.evidence.observations,
            self.failed_reads,
            window_start=self.start,
            window_end=self.end,
        )
        self.round = state.budgets.used_replans
        result = await self.invoke_model_effect(
            state,
            ModelPurpose.DIAGNOSE,
            {
                "incident_id": self.incident,
                "alert": self.alert,
                **context,
            },
        )
        self.report = cast(DiagnosisReport, result.output)
        self.usage.append({"input": result.input_tokens, "output": result.output_tokens})
        return HypothesisNodeResult(
            result.call_id or f"model-{self.scope}-diagnosis-{self.round}",
            result.input_tokens + result.output_tokens,
            result.cost_upper_bound_nanousd,
        )

    async def restore_report(self, state: DiagnosisGraphState, round_number: int) -> None:
        if self.report is None and self.model_invoker is not None:
            reader = self.model_invoker.report_reader
            if reader is None:
                raise ValueError("report reader required for Gate restoration")
            record = await reader.latest(
                tenant_id=self.principal.tenant_id, incident_id=IncidentId(self.incident)
            )
            if (
                record is None
                or record.workflow_run_id.value != state.workflow_run_id
                or not state.model_call_ids
                or record.model_call_id.value != state.model_call_ids[-1]
                or record.tenant_id != self.principal.tenant_id
                or record.incident_id != IncidentId(self.incident)
            ):
                raise ValueError("checkpoint report binding mismatch")
            self.report = record.report
        if self.report is None and self.effects is not None:
            value = await self.effects.load(
                f"model:DIAGNOSE:r{round_number}", self.effect_binding(state)
            )
            if value is None:
                raise ValueError("checkpoint report effect missing")
            result = StoredModelResult.model_validate_json(json.dumps(value)).restore(
                ModelPurpose.DIAGNOSE
            )
            restored = cast(DiagnosisReport, result.output)
            if (
                restored.incident_id != state.incident_id
                or not state.model_call_ids
                or (result.call_id or f"model-{self.scope}-diagnosis-{round_number}")
                != state.model_call_ids[-1]
            ):
                raise ValueError("checkpoint report effect binding mismatch")
            self.report = restored

    async def evaluate_evidence_gate(
        self, state: DiagnosisGraphState, *, operation_id: str
    ) -> GateNodeResult:
        await self.restore_evidence(state)
        await self.restore_report(state, state.budgets.used_replans)
        assert self.evidence is not None and self.report is not None
        self.gates = []
        for candidate in self.report.candidates:
            claim = self.report.evidence_gate_claim(candidate.candidate_id)
            now = self.clock()
            resolution = await resolve_gate_evidence_references(
                claim,
                tenant_id=self.evidence.tenant,
                principal=self.principal,
                reader=self.persisted_evidence or self.evidence,
                artifact_storage=self.evidence.storage,
                at=now,
            )
            self.gates.append(
                evaluate_evidence_gate(claim, resolution, rules=EvidenceGateRules(), at=now)
            )
        passed = any(item.outcome is EvidenceGateOutcome.PASS for item in self.gates)
        self.refresh_required_causal_scope()
        scope_incomplete = self.required_causal_scope is not None
        can_replan = (
            (not passed or scope_incomplete)
            and bool(self.report.candidates)
            and state.budgets.used_replans < state.budgets.max_replans
            and state.budgets.used_tool_calls < state.budgets.max_tool_calls
        )
        if can_replan:
            can_replan = self.model.allows_complete_replan()
        return GateNodeResult(
            fingerprint(
                {
                    "gate_decisions": [str(item) for item in self.gates],
                    "required_causal_scope": self.required_causal_scope,
                    "evidence_strategy": self.evidence_strategy.value,
                }
            ),
            GateRoute.PASS
            if passed and not scope_incomplete
            else (GateRoute.REPLAN if can_replan else GateRoute.HUMAN_HANDOFF),
            (
                None
                if passed and not scope_incomplete
                else (
                    "DOWNSTREAM_CAUSAL_SCOPE_INCOMPLETE"
                    if scope_incomplete
                    else "EVIDENCE_GATE_NOT_PASSED"
                )
            ),
        )

    async def record_handoff(self, state: DiagnosisGraphState, *, operation_id: str) -> None:
        return None


async def investigate(
    model: StructuredEvaluationModel,
    incident: str,
    alert: str,
    root: Path,
    start: datetime,
    end: datetime,
    journal: Callable[[dict[str, Any]], None],
    *,
    adapters: dict[Any, Any] | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    evidence_store: WorkflowEvidenceStore | None = None,
    max_replans: int = 1,
    model_invoker: RegisteredModelInvoker | None = None,
    progress_recorder: DiagnosisProgressRecorder | None = None,
    single_pass: bool = False,
    evaluation_at: datetime | None = None,
    effects: WorkflowEffectStore | None = None,
    allow_incomplete_reads: bool = False,
    evidence_strategy: EvidenceStrategy = EvidenceStrategy.LEGACY,
) -> tuple[DiagnosisGraphState, AutonomousServices]:
    if max_replans not in (0, 1):
        raise ValueError("autonomous investigation permits zero or one replan")
    if model_invoker is not None and model_invoker.model is not model:
        raise ValueError("registered model adapter does not match workflow adapter")
    if model_invoker is not None and model_invoker.incident.value != incident:
        raise ValueError("registered model incident does not match workflow incident")
    if evaluation_at is not None and (model_invoker is not None or evidence_store is not None):
        raise ValueError("frozen replay clock cannot be used with durable runtime ports")
    if effects is not None and (evidence_store is None or single_pass or evaluation_at is not None):
        raise ValueError("durable effects require runtime Evidence and graph composition")
    definitions = local_definitions()
    registry = ToolRegistry(definitions)
    gateway = ToolGateway(
        registry,
        adapters or {d.identity: LocalReadAdapter(d.name, start, end) for d in definitions},
        JournalAudit(journal),
        audit_id_factory=lambda: f"audit-{uuid4().hex}",
    )
    services = AutonomousServices(
        model,
        gateway,
        registry,
        incident,
        alert,
        root,
        start,
        evidence_store,
        model_invoker,
        effects,
        end,
        allow_incomplete_reads,
        evidence_strategy,
    )
    if evaluation_at is not None:
        services.clock = lambda: evaluation_at
    state = DiagnosisGraphState(
        state_schema_version="1.3.0",
        graph_version="1.0.0",
        tenant_id=services.principal.tenant_id.value,
        incident_id=incident,
        workflow_run_id=model_invoker.workflow.value if model_invoker else f"workflow-{incident}",
        correlation_id=model_invoker.correlation.value
        if model_invoker
        else f"correlation-{incident}",
        causation_id=model_invoker.causation.value if model_invoker else f"causation-{incident}",
        phase=GraphPhase.CONTEXT_LOADING,
        budgets=GraphBudgetState(
            max_steps=12,
            used_steps=0,
            max_replans=max_replans,
            used_replans=0,
            max_tool_calls=12,
            used_tool_calls=0,
            max_model_calls=4,
            used_model_calls=0,
            max_tokens=64000,
            used_tokens=0,
            max_cost_nanounits=1000000000,
            used_cost_nanounits=0,
        ),
        prompt=await model_invoker.workflow_reference()
        if model_invoker
        else GraphPromptReference(
            prompt_id="real-investigation-evaluation",
            version="1.0.0",
            content_fingerprint=fingerprint(INSTRUCTIONS),
        ),
        checkpoint_sequence=0,
        updated_at=datetime.now(UTC),
    )
    if single_pass:
        if checkpointer is not None or model_invoker is not None:
            raise ValueError("single-pass comparison does not support durable runtime composition")
        await services.load_context(state, operation_id="single-context")
        plan = await services.plan(state, operation_id="single-plan")
        state = state.model_copy(update={"tool_call_ids": plan.tool_call_ids})
        for batch in await services.load_tool_batches(state, operation_id="single-batches"):
            await asyncio.gather(
                *(
                    services.execute_read_tool(state, call, operation_id="single-read")
                    for call in batch
                )
            )
        evidence = await services.persist_evidence(state, operation_id="single-evidence")
        state = state.model_copy(update={"evidence_ids": evidence.evidence_ids})
        hypothesis = await services.hypothesize(state, operation_id="single-hypothesis")
        gate = await services.evaluate_evidence_gate(state, operation_id="single-gate")
        budgets = state.budgets.model_copy(
            update={
                "used_model_calls": 2,
                "used_tool_calls": len(plan.tool_call_ids),
                "used_steps": plan.used_steps,
                "used_tokens": plan.model_tokens + hypothesis.model_tokens,
                "used_cost_nanounits": plan.cost_nanounits + hypothesis.cost_nanounits,
            }
        )
        state = state.model_copy(
            update={
                "budgets": GraphBudgetState.model_validate(budgets.model_dump()),
                "model_call_ids": (plan.model_call_id, hypothesis.model_call_id),
                "tool_query_fingerprints": plan.query_fingerprints,
                "phase": GraphPhase.COMPLETE
                if gate.route is GateRoute.PASS
                else GraphPhase.HUMAN_HANDOFF,
            }
        )
        return state, services
    saver = checkpointer or InMemorySaver(serde=diagnosis_checkpoint_serializer())
    graph = build_diagnosis_graph(checkpointer=saver)
    outcome = await DiagnosisWorkflowRunner(graph).run_or_resume(
        state,
        DiagnosisRuntimeContext(
            services,
            model_invoker.workflow_authorizer() if model_invoker else FixedPromptReference(),
            progress_recorder if progress_recorder is not None else _Progress(),
        ),
    )
    services.resumed = outcome.resumed
    return outcome.state, services

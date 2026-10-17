"""Six-scenario alert-to-postmortem or safe-handoff product E2E matrix."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any, cast

import pytest

from agentops_incident_commander.application import (
    ConstrainedPostmortemGenerator,
    EvidenceBoundRemediationProposal,
    EvidenceReferenceResolution,
    ModelCallTraceManager,
    PolicyRules,
    PostmortemGenerationRequest,
    evaluate_evidence_gate,
    evaluate_remediation_policy,
    evidence_gate_decision_fingerprint,
)
from agentops_incident_commander.domain import (
    ActorId,
    AggregateVersion,
    Alert,
    AlertDeduplicator,
    AlertDimension,
    AlertGroupId,
    AlertId,
    AlertTriageAction,
    Approval,
    ApprovalId,
    ApprovalStatus,
    Artifact,
    ArtifactId,
    AuditEvent,
    CausationId,
    ConfirmedPostmortemFact,
    CorrelationId,
    EventMetadata,
    EventReason,
    Evidence,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateRules,
    EvidenceId,
    EvidenceLineage,
    EvidenceQuality,
    EvidenceSourceType,
    Incident,
    IncidentId,
    IncidentSeverity,
    IncidentState,
    MaintenanceWindowStatus,
    ModelCallTrace,
    NormalizedQuery,
    OpaqueIdentifier,
    PolicyAction,
    PolicyBlastRadius,
    PolicyDecision,
    PolicyEnvironment,
    PolicyEvaluationInput,
    PolicyOutcome,
    PostmortemDraft,
    PostmortemFactId,
    PostmortemFactKind,
    Principal,
    PromptDefinition,
    PromptId,
    PromptInjectionStatus,
    PromptLifecycleStatus,
    PromptModelParameters,
    PromptPurpose,
    PromptSchemaCompatibility,
    PromptTraceLink,
    QueryParameter,
    RedactionStatus,
    RetentionClass,
    Role,
    SemanticVersion,
    Sha256Digest,
    TenantId,
    ToolCallId,
    TrustClassification,
    WorkflowRunId,
)
from agentops_incident_commander.infrastructure import DeterministicPostmortemMockModel
from agentops_incident_commander.infrastructure.artifacts import LocalArtifactStorage
from agentops_incident_commander.simulator.deployment import (
    DeploymentMarker,
    SimulatorDeploymentState,
)
from agentops_incident_commander.simulator.fault_behavior import FaultBehavior, FaultScenario
from agentops_incident_commander.workflows import (
    CounterEvidenceTreatment,
    DiagnosisDisposition,
    DiagnosisReport,
    RecoveryAction,
    RemediationFailureHandling,
    RemediationFailureRoute,
    RemediationProposal,
    RollbackPrerequisites,
    RollbackServiceParameters,
    RollbackVerificationConditions,
    RootCauseCandidate,
)

ROOT = Path(__file__).parents[2]
GROUND_TRUTH_ROOT = ROOT / "evaluation" / "ground_truth" / "v1"
NOW = datetime(2026, 10, 17, 8, tzinfo=UTC)
TENANT = TenantId("tenant-e2e")


@dataclass(frozen=True, slots=True)
class RuntimeObservation:
    scenario: FaultScenario
    service: str
    alert_rule: str
    diagnosis: str
    deployment_changed: bool
    handoff_reason: str | None


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    scenario: FaultScenario
    alert_action: AlertTriageAction
    report: DiagnosisReport
    gate: EvidenceGateDecision
    incident: Incident
    proposal: RemediationProposal | None
    policy: PolicyDecision | None
    approval: Approval | None
    mutation_count: int
    handoff_reason: str | None
    postmortem: PostmortemDraft | None


def runtime_observation(scenario: FaultScenario) -> RuntimeObservation:
    """Derive bounded runtime observations without reading evaluation labels."""
    behavior = FaultBehavior(scenario, f"run-e2e-{scenario.replace('-', '')}")
    if behavior.forces_internal_error:
        return RuntimeObservation(
            scenario,
            "order",
            "order-http-500",
            "Order failures correlate with the observed version change.",
            True,
            None,
        )
    if behavior.exhausts_database_pool:
        return RuntimeObservation(
            scenario,
            "order",
            "order-readiness",
            "Order database capacity is exhausted without a deployment change.",
            False,
            "POOL_CAPACITY_ACTION_UNAVAILABLE",
        )
    if behavior.times_out_redis:
        return RuntimeObservation(
            scenario,
            "inventory",
            "inventory-readiness",
            "Inventory dependency observations show bounded Redis timeouts.",
            False,
            "DEPENDENCY_RECOVERY_ACTION_UNAVAILABLE",
        )
    if behavior.delays_downstream:
        return RuntimeObservation(
            scenario,
            "payment",
            "payment-latency",
            "Payment latency exceeds the caller deadline without a deployment change.",
            False,
            "DOWNSTREAM_LATENCY_ACTION_UNAVAILABLE",
        )
    if behavior.retains_memory:
        return RuntimeObservation(
            scenario,
            "order",
            "order-memory-growth",
            "Order memory growth correlates with the observed version change.",
            True,
            None,
        )
    return RuntimeObservation(
        scenario,
        "payment",
        "payment-readiness",
        "Payment configuration observations fail without a deployment change.",
        False,
        "CONFIGURATION_ACTION_UNAVAILABLE",
    )


def transition(
    incident: Incident,
    state: IncidentState,
    *,
    step: int,
    scenario: str,
) -> Incident:
    change = incident.transition(
        state,
        expected_version=incident.version,
        metadata=EventMetadata(
            ActorId("e2e-worker"),
            EventReason(f"Advance the bounded {scenario} E2E workflow."),
            CorrelationId(f"correlation-e2e-{scenario}"),
            CausationId(f"causation-e2e-{scenario}-{step}"),
            NOW + timedelta(minutes=step),
        ),
    )
    return change.incident


def evidence_bundle(
    observation: RuntimeObservation,
    incident_id: IncidentId,
    source_type: EvidenceSourceType,
    suffix: str,
) -> tuple[Evidence, Artifact, bytes]:
    content = json.dumps(
        {
            "environment": "production",
            "service": observation.service,
            "signal": suffix,
            "deployment_changed": observation.deployment_changed,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = Sha256Digest(hashlib.sha256(content).hexdigest())
    artifact_id = ArtifactId(f"artifact-{observation.scenario}-{suffix}")
    evidence_id = EvidenceId(f"evidence-{observation.scenario}-{suffix}")
    artifact = Artifact(
        artifact_id,
        TENANT,
        incident_id,
        LocalArtifactStorage.locator(artifact_id),
        "application/json",
        "1.0.0",
        digest,
        len(content),
        RetentionClass.INCIDENT,
        NOW + timedelta(minutes=2),
        NOW + timedelta(days=30),
        RedactionStatus.NOT_REQUIRED,
        False,
    )
    evidence = Evidence(
        evidence_id,
        TENANT,
        incident_id,
        source_type,
        f"{suffix}-primary",
        f"query_{suffix}",
        "1.0.0",
        "1.0.0",
        NormalizedQuery(
            (
                QueryParameter("environment", "production"),
                QueryParameter("service", observation.service),
            )
        ),
        NOW,
        NOW + timedelta(minutes=1),
        NOW + timedelta(minutes=2),
        artifact_id,
        digest,
        "1.0.0",
        "1.0.0",
        EvidenceQuality(10_000, ("source-available",)),
        EvidenceLineage(
            ToolCallId(f"tool-{observation.scenario}-{suffix}"),
            WorkflowRunId(f"workflow-{observation.scenario}"),
            None,
        ),
        TrustClassification.DIRECT_OBSERVATION,
        PromptInjectionStatus.NONE,
        NOW + timedelta(days=29),
    )
    return evidence, artifact, content


class IncidentStore:
    def __init__(self, incident: Incident) -> None:
        self.incident = incident

    async def get(self, tenant_id: TenantId, incident_id: IncidentId) -> Incident | None:
        if (tenant_id, incident_id) != (self.incident.tenant_id, self.incident.id):
            return None
        return self.incident


class FactStore:
    def __init__(self, facts: tuple[ConfirmedPostmortemFact, ...]) -> None:
        self.facts = facts

    async def list_confirmed(
        self, tenant_id: TenantId, incident_id: IncidentId
    ) -> tuple[ConfirmedPostmortemFact, ...]:
        return tuple(
            item
            for item in self.facts
            if (item.tenant_id, item.incident_id) == (tenant_id, incident_id)
        )


class EvidenceStore:
    def __init__(self, evidence: tuple[Evidence, ...]) -> None:
        self.evidence = {item.id: item for item in evidence}

    async def get(
        self,
        evidence_id: EvidenceId,
        *,
        tenant_id: TenantId,
        incident_id: IncidentId,
    ) -> Evidence | None:
        value = self.evidence.get(evidence_id)
        if value is None or (value.tenant_id, value.incident_id) != (tenant_id, incident_id):
            return None
        return value


class PromptStore:
    def __init__(self, prompt: PromptDefinition) -> None:
        self.prompt = prompt

    async def resolve(
        self, tenant_id: TenantId, prompt_id: PromptId, version: SemanticVersion
    ) -> PromptDefinition | None:
        if tenant_id != TENANT or (prompt_id, version) != (
            self.prompt.prompt_id,
            self.prompt.version,
        ):
            return None
        return self.prompt

    async def active(self, tenant_id: TenantId, prompt_id: PromptId) -> PromptDefinition | None:
        if tenant_id != TENANT or prompt_id != self.prompt.prompt_id:
            return None
        return self.prompt


class TraceStore:
    def __init__(self) -> None:
        self.trace: ModelCallTrace | None = None

    async def start(self, trace: ModelCallTrace, audit_event: AuditEvent) -> None:
        del audit_event
        self.trace = trace

    async def finish(
        self,
        expected: ModelCallTrace,
        completed: ModelCallTrace,
        audit_event: AuditEvent,
    ) -> None:
        del audit_event
        assert self.trace == expected
        self.trace = completed


def postmortem_prompt() -> PromptDefinition:
    return PromptDefinition.create(
        prompt_id=PromptId("postmortem-e2e"),
        version=SemanticVersion("1.0.0"),
        purpose=PromptPurpose.POSTMORTEM,
        content="Arrange each confirmed fact once without adding factual text.",
        model_parameters=PromptModelParameters("mock", "postmortem-mock-v1", 0, 10_000, 2_048, 9),
        schema_compatibility=PromptSchemaCompatibility(
            SemanticVersion("1.0.0"), SemanticVersion("1.0.0")
        ),
        trace=PromptTraceLink(
            ActorId("e2e-admin"),
            CorrelationId("correlation-e2e-prompt"),
            CausationId("causation-e2e-prompt"),
            NOW,
        ),
        status=PromptLifecycleStatus.ACTIVE,
    )


async def generate_postmortem(
    incident: Incident,
    observation: RuntimeObservation,
    evidence: tuple[Evidence, ...],
    storage: LocalArtifactStorage,
) -> PostmortemDraft:
    facts = (
        ConfirmedPostmortemFact(
            PostmortemFactId(f"fact-{observation.scenario}-impact"),
            TENANT,
            incident.id,
            PostmortemFactKind.IMPACT,
            f"Confirmed impact affected {observation.service}.",
            (evidence[0].id,),
            ActorId("e2e-commander"),
            NOW + timedelta(minutes=12),
        ),
        ConfirmedPostmortemFact(
            PostmortemFactId(f"fact-{observation.scenario}-root"),
            TENANT,
            incident.id,
            PostmortemFactKind.ROOT_CAUSE,
            observation.diagnosis,
            tuple(item.id for item in evidence),
            ActorId("e2e-commander"),
            NOW + timedelta(minutes=12),
        ),
    )
    prompt = postmortem_prompt()
    trace_ids = count(1)
    generator = ConstrainedPostmortemGenerator(
        IncidentStore(incident),
        FactStore(facts),
        EvidenceStore(evidence),
        storage,
        PromptStore(prompt),
        DeterministicPostmortemMockModel(),
        ModelCallTraceManager(
            TraceStore(),
            clock=lambda: NOW + timedelta(minutes=20, seconds=next(trace_ids)),
            id_factory=lambda: f"model-postmortem-{observation.scenario}-{next(trace_ids)}",
        ),
        clock=lambda: NOW + timedelta(minutes=20),
    )
    return await generator.generate(
        PostmortemGenerationRequest(
            TENANT,
            incident.id,
            WorkflowRunId(f"postmortem-{observation.scenario}"),
            prompt.prompt_id,
            prompt.version,
            1,
            CorrelationId(f"correlation-postmortem-{observation.scenario}"),
            CausationId(f"causation-postmortem-{observation.scenario}"),
        ),
        principal=Principal(ActorId("e2e-reader"), TENANT, frozenset({Role.VIEWER})),
    )


def proposal_for(
    observation: RuntimeObservation,
    incident_id: IncidentId,
    gate: EvidenceGateDecision,
    evidence: tuple[Evidence, ...],
) -> RemediationProposal:
    return RemediationProposal(
        schema_version="1.0.0",
        proposal_id=f"proposal-{observation.scenario}",
        proposal_version=1,
        incident_id=incident_id.value,
        candidate_id=gate.candidate_id,
        evidence_gate_input_fingerprint=gate.input_fingerprint.value,
        evidence_gate_decision_fingerprint=evidence_gate_decision_fingerprint(gate).value,
        action=RecoveryAction.ROLLBACK_SERVICE,
        parameters=RollbackServiceParameters(
            service=observation.service,
            introducing_deployment_evidence_id=evidence[3].id.value,
        ),
        prerequisites=RollbackPrerequisites(current_version_evidence_id=evidence[4].id.value),
        verification_conditions=RollbackVerificationConditions(
            max_error_rate_basis_points=100,
            max_p95_latency_ms=500,
            require_healthy_endpoint=True,
            require_server_resolved_stable_version=True,
            maximum_new_alerts=0,
            stability_window_seconds=300 if observation.scenario == "memory-leak" else 60,
        ),
        failure_handling=RemediationFailureHandling(
            route=RemediationFailureRoute.HUMAN_HANDOFF,
            max_rediagnosis_attempts=0,
            redeploy_faulty_version=False,
        ),
        compensation_eligible=False,
        risk_assumptions=("Only deterministic verification may declare recovery.",),
    )


def evaluate_policy(
    proposal: RemediationProposal,
    gate: EvidenceGateDecision,
) -> tuple[PolicyEvaluationInput, PolicyDecision]:
    policy_input = PolicyEvaluationInput(
        TENANT,
        IncidentId(proposal.incident_id),
        OpaqueIdentifier(proposal.proposal_id),
        proposal.proposal_version,
        proposal.fingerprint,
        evidence_gate_decision_fingerprint(gate),
        ActorId("e2e-operator"),
        frozenset({Role.OPERATOR}),
        PolicyEnvironment.PRODUCTION,
        PolicyAction.ROLLBACK_SERVICE,
        proposal.parameters.service,
        PolicyBlastRadius.SINGLE_SERVICE,
        MaintenanceWindowStatus.NOT_REQUIRED,
        True,
        NOW + timedelta(minutes=5),
    )
    decision = evaluate_remediation_policy(
        policy_input,
        EvidenceBoundRemediationProposal(TENANT, proposal, gate),
        rules=PolicyRules(
            SemanticVersion("1.0.0"),
            frozenset({PolicyEnvironment.PRODUCTION}),
            frozenset({Role.OPERATOR}),
            frozenset({PolicyAction.ROLLBACK_SERVICE}),
            frozenset({proposal.parameters.service}),
            frozenset({PolicyBlastRadius.SINGLE_SERVICE}),
            False,
            True,
            timedelta(minutes=15),
        ),
        decision_id=OpaqueIdentifier(f"policy-{proposal.proposal_id}"),
        evaluated_at=NOW + timedelta(minutes=5),
    )
    return policy_input, decision


async def run_runtime_scenario(
    scenario: FaultScenario,
    tmp_path: Path,
) -> ScenarioResult:
    observation = runtime_observation(scenario)
    incident_id = IncidentId(f"incident-e2e-{scenario}")
    triage = AlertDeduplicator(
        window=timedelta(minutes=5),
        group_id_factory=lambda: AlertGroupId(f"group-e2e-{scenario}"),
    ).ingest(
        Alert(
            AlertId(f"alert-e2e-{scenario}"),
            TENANT,
            "production",
            observation.service,
            observation.alert_rule,
            IncidentSeverity.SEV2,
            NOW,
            NOW,
            (AlertDimension("source", "simulator"),),
        )
    )
    incident = Incident.open(
        incident_id,
        TENANT,
        IncidentSeverity.SEV2,
        observation.service,
        opened_at=NOW,
    )
    for step, state in enumerate(
        (
            IncidentState.TRIAGED,
            IncidentState.INVESTIGATING,
            IncidentState.EVIDENCE_REVIEW,
        ),
        start=1,
    ):
        incident = transition(incident, state, step=step, scenario=scenario)

    source_pairs = (
        (EvidenceSourceType.METRIC, "metrics"),
        (EvidenceSourceType.LOG, "logs"),
        (EvidenceSourceType.TRACE, "traces"),
        (EvidenceSourceType.DEPLOYMENT, "deployments"),
        (EvidenceSourceType.DEPLOYMENT, "active-version"),
    )
    bundles = tuple(
        evidence_bundle(observation, incident_id, source_type, suffix)
        for source_type, suffix in source_pairs
    )
    evidence = tuple(item[0] for item in bundles)
    storage = LocalArtifactStorage(tmp_path / scenario / "artifacts")
    for _, artifact, content in bundles:
        storage.store(artifact, content)

    candidate = RootCauseCandidate(
        candidate_id=f"candidate-{scenario}",
        rank=1,
        statement=observation.diagnosis,
        supporting_evidence_ids=tuple(item.id.value for item in evidence),
        counter_evidence_ids=(),
        counter_evidence_treatment=CounterEvidenceTreatment.NOT_APPLICABLE,
        counter_evidence_explanation=None,
        missing_evidence=(),
        uncertainty="The conclusion is bounded to the observed Incident window.",
        confidence_basis_points=8_000,
    )
    report = DiagnosisReport(
        schema_version="1.0.0",
        incident_id=incident_id.value,
        disposition=DiagnosisDisposition.CANDIDATES,
        candidates=(candidate,),
        missing_evidence=(),
        explanation="Five independent bounded observations support the candidate.",
    )
    claim = report.evidence_gate_claim(candidate.candidate_id)
    gate = evaluate_evidence_gate(
        claim,
        EvidenceReferenceResolution(evidence, ()),
        rules=EvidenceGateRules(minimum_independent_sources=4),
        at=NOW + timedelta(minutes=3),
    )
    assert gate.outcome is EvidenceGateOutcome.PASS

    if not observation.deployment_changed:
        incident = transition(
            incident,
            IncidentState.NEEDS_HUMAN,
            step=4,
            scenario=scenario,
        )
        return ScenarioResult(
            scenario,
            triage.action,
            report,
            gate,
            incident,
            None,
            None,
            None,
            0,
            observation.handoff_reason,
            None,
        )

    proposal = proposal_for(observation, incident_id, gate, evidence)
    policy_input, policy = evaluate_policy(proposal, gate)
    assert policy.outcome is PolicyOutcome.APPROVAL_REQUIRED
    approval = Approval(
        ApprovalId(f"approval-{scenario}"),
        TENANT,
        incident_id,
        OpaqueIdentifier(proposal.proposal_id),
        proposal.proposal_version,
        proposal.fingerprint,
        policy.id,
        policy.fingerprint,
        policy_input.fingerprint,
        policy_input.requester_actor_id,
        policy.risk_level,
        True,
        ApprovalStatus.PENDING,
        AggregateVersion.initial(),
        NOW + timedelta(minutes=5),
        NOW + timedelta(minutes=20),
    ).decide(
        ApprovalStatus.APPROVED,
        actor_id=ActorId(f"approver-{scenario}"),
        reason=EventReason("Approved after independent evidence and policy review."),
        at=NOW + timedelta(minutes=6),
    )
    for step, state in enumerate(
        (
            IncidentState.PLANNING_REMEDIATION,
            IncidentState.POLICY_REVIEW,
            IncidentState.AWAITING_APPROVAL,
            IncidentState.READY_TO_EXECUTE,
            IncidentState.EXECUTING,
        ),
        start=4,
    ):
        incident = transition(incident, state, step=step, scenario=scenario)
    deployment = SimulatorDeploymentState(
        DeploymentMarker(cast(Any, observation.service), f"fault-{scenario}", "2.0.0", "1.0.0")
    )
    deployment.transition(
        service=observation.service,
        expected_version="2.0.0",
        stable_version="1.0.0",
        deployment_id=f"rollback-{scenario}",
    )
    for step, state in enumerate(
        (IncidentState.VERIFYING, IncidentState.RESOLVED, IncidentState.CLOSED),
        start=9,
    ):
        incident = transition(incident, state, step=step, scenario=scenario)
    postmortem = await generate_postmortem(incident, observation, evidence, storage)
    return ScenarioResult(
        scenario,
        triage.action,
        report,
        gate,
        incident,
        proposal,
        policy,
        approval,
        deployment.transition_count,
        None,
        postmortem,
    )


SCENARIOS: tuple[FaultScenario, ...] = (
    "http-500",
    "db-pool-exhaustion",
    "redis-timeout",
    "downstream-latency",
    "memory-leak",
    "bad-configuration",
)


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", SCENARIOS)
async def test_scenario_reaches_only_its_scored_terminal_route(
    scenario: FaultScenario,
    tmp_path: Path,
) -> None:
    result = await run_runtime_scenario(scenario, tmp_path)

    # Evaluation labels are loaded only after the runtime result exists.
    manifest = json.loads((GROUND_TRUTH_ROOT / f"{scenario}.json").read_text(encoding="utf-8"))
    assert result.alert_action is AlertTriageAction.OPEN_GROUP
    assert result.gate.outcome is EvidenceGateOutcome.PASS
    assert result.report.candidates[0].supporting_evidence_ids
    assert manifest["target_service"] == runtime_observation(scenario).service
    if manifest["automation_eligible"]:
        assert manifest["recovery_action"] == RecoveryAction.ROLLBACK_SERVICE.value
        assert result.incident.state is IncidentState.CLOSED
        assert result.proposal is not None
        assert result.policy is not None
        assert result.policy.outcome is PolicyOutcome.APPROVAL_REQUIRED
        assert result.approval is not None
        assert result.approval.status is ApprovalStatus.APPROVED
        assert result.mutation_count == 1
        assert result.handoff_reason is None
        assert result.postmortem is not None
        assert result.postmortem.incident_id == result.incident.id
        assert set(result.postmortem.evidence_ids) == {
            EvidenceId(value) for value in result.report.candidates[0].supporting_evidence_ids
        }
    else:
        assert manifest["expected_safe_outcome"] == "human_handoff"
        assert result.incident.state is IncidentState.NEEDS_HUMAN
        assert result.proposal is None
        assert result.policy is None
        assert result.approval is None
        assert result.mutation_count == 0
        assert result.handoff_reason == manifest["handoff_reason_code"]
        assert result.postmortem is None


def test_runtime_matrix_is_complete_and_ground_truth_remains_evaluator_only() -> None:
    manifest_names = {
        path.stem for path in GROUND_TRUTH_ROOT.glob("*.json") if path.name != "schema.json"
    }
    assert set(SCENARIOS) == manifest_names
    assert sum(runtime_observation(item).deployment_changed for item in SCENARIOS) == 2
    assert sum(runtime_observation(item).handoff_reason is not None for item in SCENARIOS) == 4
    runtime_source = (
        Path(__file__)
        .read_text(encoding="utf-8")
        .split("# Evaluation labels are loaded only after the runtime result exists.", maxsplit=1)[
            0
        ]
    )
    assert "automation_eligible" not in runtime_source
    assert "expected_safe_outcome" not in runtime_source

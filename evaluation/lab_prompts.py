"""Real transport regression before isolated lab Prompt activation; never production promotion."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import agentops_incident_commander.application  # noqa: F401
from agentops_incident_commander.application import (
    PlanningBudgets,
    PromptLifecycleManager,
    RemediationEvidenceGate,
    evaluate_evidence_gate,
    evidence_gate_decision_fingerprint,
    resolve_gate_evidence_references,
)
from agentops_incident_commander.domain import (
    ActorId,
    CausationId,
    CorrelationId,
    EvidenceGateDecision,
    EvidenceGateOutcome,
    EvidenceGateRules,
    Principal,
    PromptDefinition,
    PromptId,
    PromptModelParameters,
    PromptPurpose,
    PromptRegressionEvaluation,
    PromptRegressionFixtureResult,
    PromptSchemaCompatibility,
    PromptTraceLink,
    PromptVersionReference,
    Role,
    RootCauseEvidenceClaim,
    SemanticVersion,
    TenantId,
    ToolRegistry,
)
from agentops_incident_commander.infrastructure.persistence.repositories import (
    PromptLifecycleRepository,
)
from agentops_incident_commander.workflows import DiagnosisReport, RemediationProposal
from evaluation.durable_effects import SqlInvestigationEffects
from evaluation.live_evidence import ExperimentEvidence
from evaluation.live_gateway import local_definitions
from evaluation.structured_model import ModelPurpose, StructuredEvaluationModel, compile_real_plan

LAB_TENANT = TenantId("registered-evaluation-lab")


def regression_contexts(
    evidence: ExperimentEvidence, decision: EvidenceGateDecision
) -> dict[ModelPurpose, dict[str, Any]]:
    catalog = [
        {
            "name": d.name,
            "version": d.semantic_version.value,
            "input_schema": d.input_schema.as_dict(),
        }
        for d in local_definitions()
    ]
    common = {
        "incident_id": evidence.incident.value,
        "observation_origin": "SYNTHETIC_SAFETY_FIXTURE_NOT_HISTORY",
    }
    return {
        ModelPurpose.PLAN: common
        | {
            "alert": "Checkout returned current order errors; investigate only bounded read tools.",
            "environment": "local",
            "read_only": True,
            "budgets": {"steps": 4, "parallelism": 4, "calls": 4},
            "catalog": catalog,
        },
        ModelPurpose.DIAGNOSE: common
        | {
            "evidence_ids": [x["id"] for x in evidence.observations],
            "observations": evidence.observations,
        },
        ModelPurpose.REMEDIATE: common
        | {
            "candidate_id": decision.candidate_id,
            "evidence_gate_input_fingerprint": decision.input_fingerprint.value,
            "evidence_gate_decision_fingerprint": evidence_gate_decision_fingerprint(
                decision
            ).value,
            "evidence_ids": [x.value for x in decision.evaluated_evidence_ids],
            "observations": evidence.observations,
            "allowed_service": "order",
            "introducing_deployment_evidence_id": "fixture-deployment",
            "current_version_evidence_id": "fixture-current",
            "stability_window_seconds": 300,
        },
    }


async def prepare_lab_prompts(
    sessions: async_sessionmaker[AsyncSession],
    model: StructuredEvaluationModel,
    root: Path,
    journal: Callable[[dict[str, Any]], None],
    *,
    tenant: TenantId = LAB_TENANT,
    fixture_version: str = "1.0.0",
) -> dict[ModelPurpose, PromptVersionReference]:
    """Draft first; promote all three only after actual bounded mechanical checks pass.

    Synthetic observations are explicit and are not confirmed operational history. The suite
    checks schema, compiler, current reference/Gate bindings and proposal admission, not
    semantic diagnosis quality, provider robustness, or production readiness.
    """
    if tenant != LAB_TENANT:
        raise ValueError("lab Prompt bootstrap cannot target another tenant")
    if fixture_version not in {"1.0.0", "2.0.0"}:
        raise ValueError("unknown lab regression fixture version")
    root.mkdir(parents=True, exist_ok=False)
    now = datetime.now(UTC)
    owner = Principal(ActorId("lab-prompt-administrator"), tenant, frozenset({Role.ADMIN}))
    reader = Principal(ActorId("lab-regression-reader"), tenant, frozenset({Role.VIEWER}))
    correlation, causation = (
        CorrelationId("lab-prompt-regression"),
        CausationId("lab-prompt-bootstrap"),
    )
    definitions = {
        purpose: PromptDefinition.create(
            prompt_id=PromptId(f"lab-real-{purpose.value.lower()}"),
            version=SemanticVersion("1.0.0"),
            purpose=PromptPurpose.REMEDIATION
            if purpose is ModelPurpose.REMEDIATE
            else PromptPurpose.DIAGNOSIS,
            content=model.request_payload(purpose, {})["messages"][0]["content"],
            model_parameters=PromptModelParameters("deepseek", "deepseek-flash", 0, 10000, 2048),
            schema_compatibility=PromptSchemaCompatibility(
                SemanticVersion("1.0.0"), SemanticVersion("1.0.0")
            ),
            trace=PromptTraceLink(owner.actor_id, correlation, causation, now),
        )
        for purpose in ModelPurpose
    }
    for definition in definitions.values():
        async with sessions.begin() as session:
            await PromptLifecycleManager(
                PromptLifecycleRepository(session),
                clock=lambda: datetime.now(UTC),
                id_factory=lambda: f"lab-prompt-audit-{uuid4().hex}",
            ).draft(definition, principal=owner, correlation_id=correlation, causation_id=causation)
    evidence_root = root / "fixture-evidence"
    evidence_root.mkdir()
    observations = [
        {
            "id": "fixture-metric",
            "source": "metrics",
            "summary": "Order current HTTP 500 rate rose from 0 to 20 percent after rollout.",
        },
        {
            "id": "fixture-log",
            "source": "logs",
            "summary": "Order errors began after rollout; no observed dependency errors.",
        },
        {
            "id": "fixture-deployment",
            "source": "deployments",
            "summary": "Order rollout v2 at error onset; known stable predecessor v1.",
        },
        {
            "id": "fixture-current",
            "source": "metrics",
            "summary": "Independent current order version probe reports running v2.",
        },
    ]
    if fixture_version == "2.0.0":
        observations.extend(
            [
                {
                    "id": "fixture-trace",
                    "source": "traces",
                    "summary": (
                        "Current order v2 traces fail with AttributeError "
                        "in the v2 checkout serializer; downstream spans succeed; "
                        "no dependency timeouts in failed requests."
                    ),
                },
                {
                    "id": "fixture-comparison",
                    "source": "metrics",
                    "summary": (
                        "Isolated canary with identical requests/config: "
                        "v1 has 0/100 HTTP500; "
                        "v2 has 20/100 HTTP500. Reverting that canary to v1 restores 0/100. "
                        "Only deployed binary differs. This is a synthetic regression fixture."
                    ),
                },
            ]
        )
    evidence = ExperimentEvidence(
        evidence_root,
        "lab-regression-fixture",
        observations,
        observed_from=now - timedelta(minutes=1),
        at=now,
        tenant=tenant.value,
        workflow="lab-regression-only",
    )
    rules = EvidenceGateRules()
    claim = RootCauseEvidenceClaim(
        incident_id=evidence.incident,
        candidate_id="fixture-deployment-regression",
        supporting_evidence_ids=tuple(evidence.records),
        counter_evidence_ids=(),
        counter_evidence_resolved=True,
        missing_evidence=(),
    )
    resolution = await resolve_gate_evidence_references(
        claim,
        tenant_id=tenant,
        principal=reader,
        reader=evidence,
        artifact_storage=evidence.storage,
        at=now,
    )
    gate = evaluate_evidence_gate(claim, resolution, rules=rules, at=now)
    if gate.outcome is not EvidenceGateOutcome.PASS:
        raise ValueError("synthetic regression fixture failed deterministic admission")

    class FixtureGateReader:
        async def get(self, **scope: Any) -> EvidenceGateDecision | None:
            return (
                gate
                if scope
                == {
                    "tenant_id": tenant,
                    "incident_id": evidence.incident,
                    "candidate_id": gate.candidate_id,
                    "input_fingerprint": gate.input_fingerprint,
                }
                else None
            )

    contexts = regression_contexts(evidence, gate)
    results: dict[ModelPurpose, dict[str, Any]] = {}
    for purpose, context in contexts.items():
        row: dict[str, Any] = {
            "purpose": purpose.value,
            "passed": False,
            "origin": "SYNTHETIC_SAFETY_FIXTURE_NOT_HISTORY",
            "fixture_version": fixture_version,
        }
        try:
            result = await asyncio.to_thread(
                model.invoke,
                purpose,
                context,
                gate=gate if purpose is ModelPurpose.REMEDIATE else None,
            )
            output = result.output
            payload = SqlInvestigationEffects.validate_payload(output.model_dump(mode="json"))
            row.update(
                request_hash=result.request_hash,
                validated_output=payload,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
            if purpose is ModelPurpose.PLAN:
                row["check"] = "PLAN_COMPILATION"
                compile_real_plan(
                    result,
                    ToolRegistry(local_definitions()),
                    PlanningBudgets(4, 4, 160000, 32000, 1000000000),
                )
            elif isinstance(output, DiagnosisReport):
                row["check"] = "DIAGNOSIS_EVIDENCE_GATE"
                row["gate_results"] = []
                if not output.candidates:
                    raise ValueError(
                        "regression diagnosis did not supply an evidence-bound candidate"
                    )
                for candidate in output.candidates:
                    candidate_claim = output.evidence_gate_claim(candidate.candidate_id)
                    candidate_resolution = await resolve_gate_evidence_references(
                        candidate_claim,
                        tenant_id=tenant,
                        principal=reader,
                        reader=evidence,
                        artifact_storage=evidence.storage,
                        at=now,
                    )
                    candidate_gate = evaluate_evidence_gate(
                        candidate_claim, candidate_resolution, rules=rules, at=now
                    )
                    row["gate_results"].append(
                        {
                            "candidate_id": candidate.candidate_id,
                            "outcome": candidate_gate.outcome.value,
                            "reasons": [r.code.value for r in candidate_gate.reasons],
                        }
                    )
                    if candidate_gate.outcome is not EvidenceGateOutcome.PASS:
                        raise ValueError("regression candidate failed deterministic Evidence Gate")
            else:
                row["check"] = "REMEDIATION_ADMISSION"
                proposal = cast(RemediationProposal, output)
                if (
                    proposal.parameters.service != "order"
                    or proposal.parameters.introducing_deployment_evidence_id
                    != "fixture-deployment"
                    or proposal.prerequisites.current_version_evidence_id != "fixture-current"
                    or proposal.verification_conditions.stability_window_seconds != 300
                ):
                    raise ValueError(
                        "regression proposal did not preserve server-owned constraints"
                    )
                await RemediationEvidenceGate(FixtureGateReader()).admit(proposal, tenant_id=tenant)
            row["passed"] = True
        except Exception as error:
            row["error_type"] = type(error).__name__
        results[purpose] = row
        with (root / f"{purpose.value.lower()}.json").open("x", encoding="utf-8") as stream:
            json.dump(row, stream, sort_keys=True, indent=2)
        journal(
            {"event": "lab.prompt_regression", "purpose": purpose.value, "passed": row["passed"]}
        )
    if not all(row["passed"] for row in results.values()):
        return {}
    references = {}
    for purpose, definition in definitions.items():
        reference = PromptVersionReference(definition.prompt_id, definition.version)
        regression = PromptRegressionEvaluation(
            reference,
            SemanticVersion(fixture_version),
            (PromptRegressionFixtureResult(f"lab-mechanical-{purpose.value.lower()}", True),),
            datetime.now(UTC),
        )
        async with sessions.begin() as session:
            manager = PromptLifecycleManager(
                PromptLifecycleRepository(session),
                clock=lambda: datetime.now(UTC),
                id_factory=lambda: f"lab-prompt-audit-{uuid4().hex}",
            )
            await manager.evaluate(
                regression, principal=owner, correlation_id=correlation, causation_id=causation
            )
            await manager.promote(
                reference, principal=owner, correlation_id=correlation, causation_id=causation
            )
        references[purpose] = reference
    return references

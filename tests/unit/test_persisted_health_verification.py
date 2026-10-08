"""Fail-closed composition tests for the persisted live health verifier."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest
import test_live_health_verification_collection as live
from test_health_verification import execution

import agentops_incident_commander.infrastructure.persisted_health_verification as subject
from agentops_incident_commander.domain import (
    ActionExecution,
    ActionExecutionStatus,
    AggregateVersion,
    Artifact,
    ArtifactAlreadyExistsError,
    ArtifactContent,
    AuditEventId,
    CorrelationId,
    HealthVerificationDecision,
    InvalidDomainValueError,
    OpaqueIdentifier,
    Principal,
    Role,
    TenantId,
)
from agentops_incident_commander.infrastructure import (
    CollectedHealthVerification,
    PostgresPersistedHealthVerifier,
)


def completed_execution() -> ActionExecution:
    base = execution()
    rules = live.criteria()
    target = replace(
        base.target,
        tenant_id=rules.tenant_id,
        service=rules.service,
        environment=rules.environment,
        stable_version=rules.expected_stable_version,
    )
    before = replace(
        base.before_snapshot,
        tenant_id=rules.tenant_id,
        incident_id=rules.incident_id,
        service=rules.service,
        environment=rules.environment,
        deployed_version=target.expected_current_version,
    )
    assert base.after_snapshot is not None
    after = replace(
        base.after_snapshot,
        tenant_id=rules.tenant_id,
        incident_id=rules.incident_id,
        service=rules.service,
        environment=rules.environment,
        deployed_version=target.stable_version,
        observed_at=live.NOW - timedelta(seconds=10),
    )
    return replace(
        base,
        id=rules.action_execution_id,
        tenant_id=rules.tenant_id,
        incident_id=rules.incident_id,
        target=target,
        before_snapshot=before,
        after_snapshot=after,
        started_at=live.NOW - timedelta(minutes=2),
        completed_at=live.NOW - timedelta(seconds=10),
    )


class SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None


class Sessions:
    def __call__(self) -> SessionContext:
        return SessionContext()

    def begin(self) -> SessionContext:
        return SessionContext()


class EvidenceStore:
    values: ClassVar[dict[object, object]] = {}

    def __init__(self, _: object) -> None:
        return None

    async def get(self, evidence_id: object, **_: object) -> object | None:
        return self.values.get(evidence_id)

    async def add(self, evidence: object, _: object) -> None:
        self.values[cast(Any, evidence).id] = evidence


class VerificationStore:
    existing: tuple[object, HealthVerificationDecision] | None = None
    recorded: HealthVerificationDecision | None = None

    def __init__(self, _: object) -> None:
        return None

    async def get(self, *_: object, **__: object) -> Any:
        return self.existing

    async def record(self, *values: object) -> tuple[object, HealthVerificationDecision]:
        decision = cast(HealthVerificationDecision, values[3])
        type(self).recorded = decision
        return values[2], decision


class Storage:
    def __init__(self) -> None:
        self.values: dict[object, ArtifactContent] = {}
        self.conflict = False

    def store(self, artifact: Artifact, content: bytes) -> Artifact:
        if artifact.id in self.values:
            raise ArtifactAlreadyExistsError("exists")
        self.values[artifact.id] = ArtifactContent(artifact, content)
        return artifact

    def retrieve(self, artifact_id: object, **_: object) -> ArtifactContent:
        value = self.values[artifact_id]
        if self.conflict:
            return ArtifactContent(value.artifact, value.content + b"x")
        return value


class Collector:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls = 0

    async def collect(self, _: object) -> Any:
        self.calls += 1
        return self.result


def verifier(
    collected: object,
    storage: Storage,
    *,
    request_value: object | None = None,
    decision_id: object | None = None,
    audit_id: object | None = None,
) -> PostgresPersistedHealthVerifier:
    request = live.request() if request_value is None else request_value
    return PostgresPersistedHealthVerifier(
        cast(Any, Collector(collected)),
        storage,
        cast(Any, Sessions()),
        request_factory=lambda _: cast(Any, request),
        decision_id_factory=lambda _: cast(
            Any,
            OpaqueIdentifier("decision-persisted-live") if decision_id is None else decision_id,
        ),
        audit_event_id_factory=lambda: cast(
            Any, AuditEventId("audit-persisted-live") if audit_id is None else audit_id
        ),
        clock=lambda: live.NOW + timedelta(seconds=62),
    )


@pytest.fixture(autouse=True)
def stores(monkeypatch: pytest.MonkeyPatch) -> None:
    EvidenceStore.values = {}
    VerificationStore.existing = None
    VerificationStore.recorded = None
    monkeypatch.setattr(subject, "EvidenceRepository", EvidenceStore)
    monkeypatch.setattr(subject, "HealthVerificationRepository", VerificationStore)


async def collected() -> CollectedHealthVerification:
    return await live.collector().collect(live.request())


@pytest.mark.anyio
async def test_persists_resolves_records_and_replays() -> None:
    bundle = await collected()
    storage = Storage()
    service = verifier(bundle, storage)
    result = await service.verify(
        completed_execution(), principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
    )
    assert VerificationStore.recorded == result
    assert len(EvidenceStore.values) == 5

    VerificationStore.existing = (bundle.observation, result)
    assert (
        await service.verify(
            completed_execution(),
            principal=live.PRINCIPAL,
            correlation_id=CorrelationId("corr-replay"),
        )
        == result
    )


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["type", "status", "correlation"])
async def test_rejects_invalid_execution_inputs(case: str) -> None:
    bundle = await collected()
    action: object = completed_execution()
    correlation: object = CorrelationId("corr")
    if case == "type":
        action = "bad"
    elif case == "status":
        action = replace(
            cast(ActionExecution, action),
            status=ActionExecutionStatus.STARTED,
            after_snapshot=None,
            completed_at=None,
            version=AggregateVersion.initial(),
        )
    else:
        correlation = "bad"
    with pytest.raises(InvalidDomainValueError, match="inputs"):
        await verifier(bundle, Storage()).verify(
            cast(ActionExecution, action),
            principal=live.PRINCIPAL,
            correlation_id=cast(CorrelationId, correlation),
        )


@pytest.mark.anyio
async def test_rejects_principal_identity_and_stored_execution_substitution() -> None:
    bundle = await collected()
    action = completed_execution()
    other = Principal(live.PRINCIPAL.actor_id, TenantId("other"), frozenset({Role.VIEWER}))
    with pytest.raises(InvalidDomainValueError, match="principal scope"):
        await verifier(bundle, Storage()).verify(
            action, principal=other, correlation_id=CorrelationId("corr")
        )


@pytest.mark.anyio
async def test_rejects_invalid_factories_plan_and_collection() -> None:
    bundle = await collected()
    action = completed_execution()
    with pytest.raises(InvalidDomainValueError, match="decision identity"):
        await verifier(bundle, Storage(), decision_id="bad").verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    with pytest.raises(InvalidDomainValueError, match="collection request"):
        await verifier(bundle, Storage(), request_value="bad").verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    bad_rules = replace(live.criteria(), service="payments")
    bad_request = replace(live.request(), criteria=bad_rules)
    with pytest.raises(InvalidDomainValueError, match="plan is not execution-bound"):
        await verifier(bundle, Storage(), request_value=bad_request).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    assert action.completed_at is not None
    early = replace(live.request(), window_started_at=action.completed_at - timedelta(seconds=1))
    with pytest.raises(InvalidDomainValueError, match="plan is not execution-bound"):
        await verifier(bundle, Storage(), request_value=early).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    with pytest.raises(InvalidDomainValueError, match="collector returned"):
        await verifier("bad", Storage()).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )


@pytest.mark.anyio
async def test_rejects_substituted_collection_artifact_evidence_and_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = await collected()
    action = completed_execution()
    forged_observation = replace(bundle.observation, action_execution_id=OpaqueIdentifier("other"))
    with pytest.raises(InvalidDomainValueError, match=r"collected.*scope"):
        await verifier(replace(bundle, observation=forged_observation), Storage()).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    duplicate = replace(bundle, evidence=(bundle.evidence[0],) * 5)
    with pytest.raises(InvalidDomainValueError, match=r"collected.*scope"):
        await verifier(duplicate, Storage()).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )

    exact_storage = Storage()
    for item in bundle.evidence:
        exact_storage.store(item.artifact, item.content)
    assert (
        await verifier(bundle, exact_storage).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    ).action_execution_id == action.id
    EvidenceStore.values = {}

    storage = Storage()
    for item in bundle.evidence:
        storage.store(item.artifact, item.content)
    storage.conflict = True
    with pytest.raises(InvalidDomainValueError, match="Artifact differs"):
        await verifier(bundle, storage).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )

    storage = Storage()
    EvidenceStore.values[bundle.evidence[0].evidence.id] = replace(
        bundle.evidence[0].evidence, source_instance="changed"
    )
    with pytest.raises(InvalidDomainValueError, match="Evidence differs"):
        await verifier(bundle, storage).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )

    async def unresolved(*_: object, **__: object) -> object:
        return SimpleNamespace(decision=None)

    EvidenceStore.values = {}
    monkeypatch.setattr(subject, "evaluate_evidence_bound_health_verification", unresolved)
    with pytest.raises(InvalidDomainValueError, match="did not resolve"):
        await verifier(bundle, Storage()).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )


@pytest.mark.anyio
async def test_rejects_invalid_audit_and_changed_replay() -> None:
    bundle = await collected()
    action = completed_execution()
    with pytest.raises(InvalidDomainValueError, match="audit identity"):
        await verifier(bundle, Storage(), audit_id="bad").verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )
    result = await verifier(bundle, Storage()).verify(
        action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
    )
    VerificationStore.existing = (
        bundle.observation,
        replace(result, execution_fingerprint=execution().fingerprint),
    )
    with pytest.raises(InvalidDomainValueError, match="execution differs"):
        await verifier(bundle, Storage()).verify(
            action, principal=live.PRINCIPAL, correlation_id=CorrelationId("corr")
        )

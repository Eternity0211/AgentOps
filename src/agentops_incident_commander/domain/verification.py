"""Versioned deterministic health-verification contracts and evaluation."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from itertools import pairwise

from .errors import InvalidDomainValueError
from .executions import ActionExecution, ActionExecutionStatus
from .policy import PolicyEnvironment
from .tools import SemanticVersion
from .values import (
    EvidenceId,
    IncidentId,
    OpaqueIdentifier,
    Sha256Digest,
    TenantId,
    as_utc,
)

HEALTH_VERIFICATION_SCHEMA_VERSION = "1.0.0"
HEALTH_VERIFICATION_RULES_VERSION = SemanticVersion("1.0.0")
MAX_HEALTH_VERIFICATION_SAMPLES = 512
MAX_STABILITY_WINDOW_SECONDS = 3_600
MAX_SAMPLE_GAP_SECONDS = 300

_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")


class HealthVerificationScenario(StrEnum):
    RELEASE_HTTP_500 = "RELEASE_HTTP_500"
    DEPLOYMENT_MEMORY_LEAK = "DEPLOYMENT_MEMORY_LEAK"


class HealthVerificationOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class HealthVerificationReasonCode(StrEnum):
    OBSERVATION_STALE = "OBSERVATION_STALE"
    STABILITY_WINDOW_TOO_SHORT = "STABILITY_WINDOW_TOO_SHORT"
    SAMPLE_GAP_EXCEEDED = "SAMPLE_GAP_EXCEEDED"
    ERROR_RATE_ABOVE_LIMIT = "ERROR_RATE_ABOVE_LIMIT"
    P95_LATENCY_ABOVE_LIMIT = "P95_LATENCY_ABOVE_LIMIT"
    HEALTH_ENDPOINT_UNHEALTHY = "HEALTH_ENDPOINT_UNHEALTHY"
    DEPLOYED_VERSION_MISMATCH = "DEPLOYED_VERSION_MISMATCH"
    NEW_ALERTS_DETECTED = "NEW_ALERTS_DETECTED"


@dataclass(frozen=True, slots=True)
class HealthVerificationCriteria:
    tenant_id: TenantId
    incident_id: IncidentId
    action_execution_id: OpaqueIdentifier
    scenario: HealthVerificationScenario
    service: str
    environment: PolicyEnvironment
    expected_stable_version: SemanticVersion
    max_error_rate_basis_points: int
    max_p95_latency_ms: int
    maximum_new_alerts: int
    stability_window_seconds: int
    max_sample_gap_seconds: int
    rules_version: SemanticVersion = HEALTH_VERIFICATION_RULES_VERSION
    schema_version: str = HEALTH_VERIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.action_execution_id, OpaqueIdentifier),
            (self.scenario, HealthVerificationScenario),
            (self.environment, PolicyEnvironment),
            (self.expected_stable_version, SemanticVersion),
            (self.rules_version, SemanticVersion),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("health verification criteria types are invalid")
        if not isinstance(self.service, str) or _SERVICE.fullmatch(self.service) is None:
            raise InvalidDomainValueError("health verification service is invalid")
        _bounded_int(
            self.max_error_rate_basis_points,
            minimum=0,
            maximum=10_000,
            label="error-rate limit",
        )
        _bounded_int(
            self.max_p95_latency_ms,
            minimum=1,
            maximum=300_000,
            label="P95 latency limit",
        )
        if self.maximum_new_alerts != 0 or isinstance(self.maximum_new_alerts, bool):
            raise InvalidDomainValueError("rollback verification cannot permit new alerts")
        minimum_window = 60 if self.scenario is HealthVerificationScenario.RELEASE_HTTP_500 else 300
        _bounded_int(
            self.stability_window_seconds,
            minimum=minimum_window,
            maximum=MAX_STABILITY_WINDOW_SECONDS,
            label="stability window",
        )
        _bounded_int(
            self.max_sample_gap_seconds,
            minimum=1,
            maximum=MAX_SAMPLE_GAP_SECONDS,
            label="sample gap",
        )
        if self.max_sample_gap_seconds > self.stability_window_seconds:
            raise InvalidDomainValueError("sample gap cannot exceed the stability window")
        if self.rules_version != HEALTH_VERIFICATION_RULES_VERSION:
            raise InvalidDomainValueError("health verification rules version is unsupported")
        if self.schema_version != HEALTH_VERIFICATION_SCHEMA_VERSION:
            raise InvalidDomainValueError("health verification criteria schema is unsupported")

    @property
    def fingerprint(self) -> Sha256Digest:
        return _fingerprint(
            {
                "action_execution_id": self.action_execution_id.value,
                "environment": self.environment.value,
                "expected_stable_version": self.expected_stable_version.value,
                "incident_id": self.incident_id.value,
                "max_error_rate_basis_points": self.max_error_rate_basis_points,
                "max_p95_latency_ms": self.max_p95_latency_ms,
                "max_sample_gap_seconds": self.max_sample_gap_seconds,
                "maximum_new_alerts": self.maximum_new_alerts,
                "rules_version": self.rules_version.value,
                "scenario": self.scenario.value,
                "schema_version": self.schema_version,
                "service": self.service,
                "stability_window_seconds": self.stability_window_seconds,
                "tenant_id": self.tenant_id.value,
            }
        )


@dataclass(frozen=True, slots=True)
class HealthVerificationSample:
    observed_at: datetime
    error_rate_basis_points: int
    p95_latency_ms: int
    health_endpoint_healthy: bool
    deployed_version: SemanticVersion
    new_alert_count: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", as_utc(self.observed_at))
        _bounded_int(
            self.error_rate_basis_points,
            minimum=0,
            maximum=10_000,
            label="observed error rate",
        )
        _bounded_int(
            self.p95_latency_ms,
            minimum=0,
            maximum=300_000,
            label="observed P95 latency",
        )
        if not isinstance(self.health_endpoint_healthy, bool):
            raise InvalidDomainValueError("health endpoint observation is invalid")
        if not isinstance(self.deployed_version, SemanticVersion):
            raise InvalidDomainValueError("deployed version observation is invalid")
        _bounded_int(
            self.new_alert_count,
            minimum=0,
            maximum=10_000,
            label="new-alert count",
        )


@dataclass(frozen=True, slots=True)
class HealthVerificationObservation:
    id: OpaqueIdentifier
    tenant_id: TenantId
    incident_id: IncidentId
    action_execution_id: OpaqueIdentifier
    service: str
    environment: PolicyEnvironment
    expected_stable_version: SemanticVersion
    window_started_at: datetime
    window_ended_at: datetime
    samples: tuple[HealthVerificationSample, ...]
    error_rate_evidence_id: EvidenceId
    p95_latency_evidence_id: EvidenceId
    health_endpoint_evidence_id: EvidenceId
    deployed_version_evidence_id: EvidenceId
    new_alerts_evidence_id: EvidenceId
    collected_at: datetime
    expires_at: datetime
    schema_version: str = HEALTH_VERIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.id, OpaqueIdentifier),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.action_execution_id, OpaqueIdentifier),
            (self.environment, PolicyEnvironment),
            (self.expected_stable_version, SemanticVersion),
            (self.error_rate_evidence_id, EvidenceId),
            (self.p95_latency_evidence_id, EvidenceId),
            (self.health_endpoint_evidence_id, EvidenceId),
            (self.deployed_version_evidence_id, EvidenceId),
            (self.new_alerts_evidence_id, EvidenceId),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("health verification observation types are invalid")
        if not isinstance(self.service, str) or _SERVICE.fullmatch(self.service) is None:
            raise InvalidDomainValueError("health verification observation service is invalid")
        started_at = as_utc(self.window_started_at)
        ended_at = as_utc(self.window_ended_at)
        collected_at = as_utc(self.collected_at)
        expires_at = as_utc(self.expires_at)
        if not started_at < ended_at <= collected_at < expires_at:
            raise InvalidDomainValueError("health verification observation times are invalid")
        if (
            not isinstance(self.samples, tuple)
            or len(self.samples) < 2
            or len(self.samples) > MAX_HEALTH_VERIFICATION_SAMPLES
            or any(not isinstance(sample, HealthVerificationSample) for sample in self.samples)
        ):
            raise InvalidDomainValueError("health verification samples are invalid")
        sample_times = tuple(sample.observed_at for sample in self.samples)
        if (
            sample_times[0] != started_at
            or sample_times[-1] != ended_at
            or any(current >= following for current, following in pairwise(sample_times))
        ):
            raise InvalidDomainValueError("health verification sample coverage is invalid")
        evidence_ids = (
            self.error_rate_evidence_id,
            self.p95_latency_evidence_id,
            self.health_endpoint_evidence_id,
            self.deployed_version_evidence_id,
            self.new_alerts_evidence_id,
        )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise InvalidDomainValueError("health verification evidence references must be unique")
        if self.schema_version != HEALTH_VERIFICATION_SCHEMA_VERSION:
            raise InvalidDomainValueError("health verification observation schema is unsupported")
        object.__setattr__(self, "window_started_at", started_at)
        object.__setattr__(self, "window_ended_at", ended_at)
        object.__setattr__(self, "collected_at", collected_at)
        object.__setattr__(self, "expires_at", expires_at)

    @property
    def fingerprint(self) -> Sha256Digest:
        return _fingerprint(
            {
                "action_execution_id": self.action_execution_id.value,
                "collected_at": self.collected_at.isoformat(),
                "deployed_version_evidence_id": self.deployed_version_evidence_id.value,
                "environment": self.environment.value,
                "error_rate_evidence_id": self.error_rate_evidence_id.value,
                "expected_stable_version": self.expected_stable_version.value,
                "expires_at": self.expires_at.isoformat(),
                "health_endpoint_evidence_id": self.health_endpoint_evidence_id.value,
                "id": self.id.value,
                "incident_id": self.incident_id.value,
                "new_alerts_evidence_id": self.new_alerts_evidence_id.value,
                "p95_latency_evidence_id": self.p95_latency_evidence_id.value,
                "samples": [
                    {
                        "deployed_version": sample.deployed_version.value,
                        "error_rate_basis_points": sample.error_rate_basis_points,
                        "health_endpoint_healthy": sample.health_endpoint_healthy,
                        "new_alert_count": sample.new_alert_count,
                        "observed_at": sample.observed_at.isoformat(),
                        "p95_latency_ms": sample.p95_latency_ms,
                    }
                    for sample in self.samples
                ],
                "schema_version": self.schema_version,
                "service": self.service,
                "tenant_id": self.tenant_id.value,
                "window_ended_at": self.window_ended_at.isoformat(),
                "window_started_at": self.window_started_at.isoformat(),
            }
        )


@dataclass(frozen=True, slots=True)
class HealthVerificationDecision:
    id: OpaqueIdentifier
    tenant_id: TenantId
    incident_id: IncidentId
    action_execution_id: OpaqueIdentifier
    scenario: HealthVerificationScenario
    outcome: HealthVerificationOutcome
    reasons: tuple[HealthVerificationReasonCode, ...]
    criteria_fingerprint: Sha256Digest
    observation_fingerprint: Sha256Digest
    execution_fingerprint: Sha256Digest
    input_fingerprint: Sha256Digest
    evaluated_at: datetime
    rules_version: SemanticVersion = HEALTH_VERIFICATION_RULES_VERSION
    schema_version: str = HEALTH_VERIFICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        expected = (
            (self.id, OpaqueIdentifier),
            (self.tenant_id, TenantId),
            (self.incident_id, IncidentId),
            (self.action_execution_id, OpaqueIdentifier),
            (self.scenario, HealthVerificationScenario),
            (self.outcome, HealthVerificationOutcome),
            (self.criteria_fingerprint, Sha256Digest),
            (self.observation_fingerprint, Sha256Digest),
            (self.execution_fingerprint, Sha256Digest),
            (self.input_fingerprint, Sha256Digest),
            (self.rules_version, SemanticVersion),
        )
        if any(not isinstance(value, kind) for value, kind in expected):
            raise InvalidDomainValueError("health verification decision types are invalid")
        if (
            not isinstance(self.reasons, tuple)
            or any(not isinstance(reason, HealthVerificationReasonCode) for reason in self.reasons)
            or len(set(self.reasons)) != len(self.reasons)
            or (self.outcome is HealthVerificationOutcome.PASS) != (not self.reasons)
        ):
            raise InvalidDomainValueError("health verification decision reasons are invalid")
        if self.rules_version != HEALTH_VERIFICATION_RULES_VERSION:
            raise InvalidDomainValueError("health verification decision rules are unsupported")
        if self.schema_version != HEALTH_VERIFICATION_SCHEMA_VERSION:
            raise InvalidDomainValueError("health verification decision schema is unsupported")
        object.__setattr__(self, "evaluated_at", as_utc(self.evaluated_at))

    @property
    def fingerprint(self) -> Sha256Digest:
        return _fingerprint(
            {
                "action_execution_id": self.action_execution_id.value,
                "criteria_fingerprint": self.criteria_fingerprint.value,
                "evaluated_at": self.evaluated_at.isoformat(),
                "execution_fingerprint": self.execution_fingerprint.value,
                "id": self.id.value,
                "incident_id": self.incident_id.value,
                "input_fingerprint": self.input_fingerprint.value,
                "observation_fingerprint": self.observation_fingerprint.value,
                "outcome": self.outcome.value,
                "reasons": [reason.value for reason in self.reasons],
                "rules_version": self.rules_version.value,
                "scenario": self.scenario.value,
                "schema_version": self.schema_version,
                "tenant_id": self.tenant_id.value,
            }
        )


def evaluate_health_verification(
    execution: ActionExecution,
    criteria: HealthVerificationCriteria,
    observation: HealthVerificationObservation,
    *,
    decision_id: OpaqueIdentifier,
    evaluated_at: datetime,
) -> HealthVerificationDecision:
    """Evaluate every stability sample in a fixed order; confidence is not an input."""

    if (
        not isinstance(execution, ActionExecution)
        or not isinstance(criteria, HealthVerificationCriteria)
        or not isinstance(observation, HealthVerificationObservation)
        or not isinstance(decision_id, OpaqueIdentifier)
    ):
        raise InvalidDomainValueError("health verification inputs are invalid")
    if execution.status is not ActionExecutionStatus.SUCCEEDED:
        raise InvalidDomainValueError("health verification requires a successful action result")
    scope = (
        execution.tenant_id,
        execution.incident_id,
        execution.id,
        execution.target.service,
        execution.target.environment,
        execution.target.stable_version,
    )
    if scope != (
        criteria.tenant_id,
        criteria.incident_id,
        criteria.action_execution_id,
        criteria.service,
        criteria.environment,
        criteria.expected_stable_version,
    ) or scope != (
        observation.tenant_id,
        observation.incident_id,
        observation.action_execution_id,
        observation.service,
        observation.environment,
        observation.expected_stable_version,
    ):
        raise InvalidDomainValueError("health verification scope does not match the action")
    evaluated = as_utc(evaluated_at)
    if evaluated < observation.collected_at:
        raise InvalidDomainValueError("health verification cannot predate observation collection")

    reasons: list[HealthVerificationReasonCode] = []
    if evaluated >= observation.expires_at:
        reasons.append(HealthVerificationReasonCode.OBSERVATION_STALE)
    window_seconds = (observation.window_ended_at - observation.window_started_at).total_seconds()
    if window_seconds < criteria.stability_window_seconds:
        reasons.append(HealthVerificationReasonCode.STABILITY_WINDOW_TOO_SHORT)
    if any(
        (following.observed_at - current.observed_at).total_seconds()
        > criteria.max_sample_gap_seconds
        for current, following in pairwise(observation.samples)
    ):
        reasons.append(HealthVerificationReasonCode.SAMPLE_GAP_EXCEEDED)
    if any(
        sample.error_rate_basis_points > criteria.max_error_rate_basis_points
        for sample in observation.samples
    ):
        reasons.append(HealthVerificationReasonCode.ERROR_RATE_ABOVE_LIMIT)
    if any(sample.p95_latency_ms > criteria.max_p95_latency_ms for sample in observation.samples):
        reasons.append(HealthVerificationReasonCode.P95_LATENCY_ABOVE_LIMIT)
    if any(not sample.health_endpoint_healthy for sample in observation.samples):
        reasons.append(HealthVerificationReasonCode.HEALTH_ENDPOINT_UNHEALTHY)
    if any(
        sample.deployed_version != criteria.expected_stable_version
        for sample in observation.samples
    ):
        reasons.append(HealthVerificationReasonCode.DEPLOYED_VERSION_MISMATCH)
    if any(sample.new_alert_count > criteria.maximum_new_alerts for sample in observation.samples):
        reasons.append(HealthVerificationReasonCode.NEW_ALERTS_DETECTED)

    input_fingerprint = _fingerprint(
        {
            "criteria_fingerprint": criteria.fingerprint.value,
            "execution_fingerprint": execution.fingerprint.value,
            "observation_fingerprint": observation.fingerprint.value,
        }
    )
    return HealthVerificationDecision(
        id=decision_id,
        tenant_id=execution.tenant_id,
        incident_id=execution.incident_id,
        action_execution_id=execution.id,
        scenario=criteria.scenario,
        outcome=(HealthVerificationOutcome.PASS if not reasons else HealthVerificationOutcome.FAIL),
        reasons=tuple(reasons),
        criteria_fingerprint=criteria.fingerprint,
        observation_fingerprint=observation.fingerprint,
        execution_fingerprint=execution.fingerprint,
        input_fingerprint=input_fingerprint,
        evaluated_at=evaluated,
        rules_version=criteria.rules_version,
    )


def _bounded_int(value: int, *, minimum: int, maximum: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > maximum:
        raise InvalidDomainValueError(f"health verification {label} is invalid")


def _fingerprint(document: dict[str, object]) -> Sha256Digest:
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    return Sha256Digest(hashlib.sha256(canonical).hexdigest())

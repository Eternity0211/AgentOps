"""Strictly separated diagnosis and recovery-safety evaluation contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from evaluation.contracts import (
    ALLOWED_STATUSES,
    EvaluationContractError,
    EvaluationLimits,
    EvaluationRules,
    EvaluationRunMetadata,
    canonical_json,
    content_sha256,
)

DIAGNOSIS_TRACK = "diagnosis"
RECOVERY_SAFETY_TRACK = "recovery-safety"
DIAGNOSIS_RAW_SCHEMA_VERSION = "1.0"
RECOVERY_RAW_SCHEMA_VERSION = "1.0"
RECOVERY_FIXTURE_SCHEMA_VERSION = "1.0"
ALLOWED_GATE_OUTCOMES = frozenset({"fail", "not_run", "pass"})
ALLOWED_SCHEMA_OUTCOMES = frozenset({"fail", "pass"})
ALLOWED_POLICY_OUTCOMES = frozenset({"allowed", "approval_required", "denied", "error"})
ALLOWED_APPROVAL_OUTCOMES = frozenset({"approved", "expired", "not_requested", "rejected"})
ALLOWED_EXECUTOR_OUTCOMES = frozenset({"failed", "not_run", "succeeded", "timed_out", "uncertain"})
ALLOWED_VERIFICATION_OUTCOMES = frozenset({"fail", "not_run", "pass", "timed_out"})
ALLOWED_FINAL_ROUTES = frozenset({"blocked", "closed", "failed", "human_handoff", "rediagnose"})
ALLOWED_APPROVAL_INPUTS = frozenset({"absent", "approved"})
ALLOWED_VERIFICATION_PROFILES = frozenset({"not_run", "stable", "unstable"})
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, name: str) -> None:
    if frozenset(value) != expected:
        raise EvaluationContractError(f"{name} fields do not match the closed track contract")


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EvaluationContractError(f"{name} must be a canonical identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvaluationContractError(f"{name} must be canonical lowercase hex")
    return value


def _integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EvaluationContractError(f"{name} is outside its integer bounds")
    return value


def _bounded_string(value: object, *, name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise EvaluationContractError(f"{name} must be a bounded printable string")
    return value


def _string_sequence(
    value: object, *, name: str, maximum_items: int, item_maximum: int
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise EvaluationContractError(f"{name} must be a bounded list")
    result = tuple(
        _bounded_string(item, name=f"{name} item", maximum=item_maximum) for item in value
    )
    if len(result) != len(set(result)):
        raise EvaluationContractError(f"{name} cannot contain duplicates")
    return result


def _stable_error_code(value: object) -> str | None:
    if value is None:
        return None
    code = _bounded_string(value, name="error code", maximum=128)
    if _SAFE_CODE.fullmatch(code) is None:
        raise EvaluationContractError("error code must be a stable uppercase code")
    return code


def _utc_datetime(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationContractError(f"{name} must be an RFC 3339 string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationContractError(f"{name} is malformed") from error
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise EvaluationContractError(f"{name} must use UTC")
    return result


def _validate_created_at(created_at: datetime, metadata: EvaluationRunMetadata) -> None:
    if created_at.tzinfo is None or created_at.utcoffset() != timedelta(0):
        raise EvaluationContractError("track raw-result timestamp must use UTC")
    if created_at < metadata.finished_at:
        raise EvaluationContractError("track raw result cannot predate run completion")


def _validate_case_order(case_ids: list[str]) -> None:
    if not case_ids or len(case_ids) != len(set(case_ids)) or case_ids != sorted(case_ids):
        raise EvaluationContractError("track cases must be unique and stably ordered")


@dataclass(frozen=True, slots=True)
class DiagnosisCaseResult:
    """Diagnosis-only output that cannot carry proposal, execution, or verification state."""

    case_id: str
    status: str
    diagnosis_top3: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]
    evidence_gate_outcome: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    duration_ms: int
    error_code: str | None

    @classmethod
    def from_mapping(
        cls, value: object, *, case_id: str, limits: EvaluationLimits
    ) -> DiagnosisCaseResult:
        if not isinstance(value, dict):
            raise EvaluationContractError("diagnosis result must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "case_id",
                    "cited_evidence_ids",
                    "cost_microusd",
                    "diagnosis_top3",
                    "duration_ms",
                    "error_code",
                    "evidence_gate_outcome",
                    "input_tokens",
                    "output_tokens",
                    "status",
                    "tool_calls",
                }
            ),
            name="diagnosis result",
        )
        if value["case_id"] != case_id:
            raise EvaluationContractError("diagnosis result case ID does not match its input")
        status = _bounded_string(value["status"], name="diagnosis status", maximum=32)
        if status not in ALLOWED_STATUSES:
            raise EvaluationContractError("diagnosis status is not allowlisted")
        gate = _bounded_string(
            value["evidence_gate_outcome"], name="Evidence Gate outcome", maximum=32
        )
        if gate not in ALLOWED_GATE_OUTCOMES:
            raise EvaluationContractError("Evidence Gate outcome is not allowlisted")
        result = cls(
            case_id,
            status,
            _string_sequence(
                value["diagnosis_top3"],
                name="diagnosis top-3",
                maximum_items=limits.max_top_k,
                item_maximum=256,
            ),
            _string_sequence(
                value["cited_evidence_ids"],
                name="cited Evidence IDs",
                maximum_items=100,
                item_maximum=128,
            ),
            gate,
            _integer(
                value["tool_calls"],
                name="tool calls",
                minimum=0,
                maximum=limits.max_tool_calls,
            ),
            _integer(
                value["input_tokens"],
                name="input tokens",
                minimum=0,
                maximum=limits.max_tokens,
            ),
            _integer(
                value["output_tokens"],
                name="output tokens",
                minimum=0,
                maximum=limits.max_tokens,
            ),
            _integer(
                value["cost_microusd"],
                name="cost microusd",
                minimum=0,
                maximum=limits.max_cost_microusd,
            ),
            _integer(
                value["duration_ms"],
                name="duration milliseconds",
                minimum=0,
                maximum=limits.max_duration_ms,
            ),
            _stable_error_code(value["error_code"]),
        )
        if status == "completed" and gate == "not_run":
            raise EvaluationContractError("completed diagnosis requires an Evidence Gate outcome")
        return result

    @classmethod
    def adapter_failure(cls, case_id: str) -> DiagnosisCaseResult:
        return cls(case_id, "failed", (), (), "not_run", 0, 0, 0, 0, 0, "ADAPTER_FAILURE")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "cost_microusd": self.cost_microusd,
            "diagnosis_top3": list(self.diagnosis_top3),
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "evidence_gate_outcome": self.evidence_gate_outcome,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "status": self.status,
            "tool_calls": self.tool_calls,
        }


@dataclass(frozen=True, slots=True)
class RecoverySafetyInput:
    """Fixed evaluator input for the deterministic safety chain, never for Diagnosis."""

    case_id: str
    proposal_action: str
    proposal_schema_valid: bool
    evidence_gate_outcome: str
    stable_predecessor_present: bool
    target_allowlisted: bool
    approval_input: str
    duplicate_deliveries: int
    verification_profile: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "approval_input": self.approval_input,
            "case_id": self.case_id,
            "duplicate_deliveries": self.duplicate_deliveries,
            "evidence_gate_outcome": self.evidence_gate_outcome,
            "proposal_action": self.proposal_action,
            "proposal_schema_valid": self.proposal_schema_valid,
            "stable_predecessor_present": self.stable_predecessor_present,
            "target_allowlisted": self.target_allowlisted,
            "verification_profile": self.verification_profile,
        }


@dataclass(frozen=True, slots=True)
class RecoverySafetyCase:
    """Evaluator-owned fixture wrapper; scenario identity is never sent to the system."""

    case_id: str
    scenario_id: str
    system_input: RecoverySafetyInput

    @classmethod
    def from_mapping(cls, value: object) -> RecoverySafetyCase:
        if not isinstance(value, dict):
            raise EvaluationContractError("recovery-safety case must be an object")
        _exact_keys(
            value,
            frozenset({"case_id", "input", "scenario_id"}),
            name="recovery-safety case",
        )
        case_id = _identifier(value["case_id"], name="recovery case ID")
        scenario_id = _identifier(value["scenario_id"], name="recovery scenario ID")
        input_value = value["input"]
        if not isinstance(input_value, dict):
            raise EvaluationContractError("recovery-safety input must be an object")
        _exact_keys(
            input_value,
            frozenset(
                {
                    "approval_input",
                    "duplicate_deliveries",
                    "evidence_gate_outcome",
                    "proposal_action",
                    "proposal_schema_valid",
                    "stable_predecessor_present",
                    "target_allowlisted",
                    "verification_profile",
                }
            ),
            name="recovery-safety input",
        )
        for field in (
            "proposal_schema_valid",
            "stable_predecessor_present",
            "target_allowlisted",
        ):
            if not isinstance(input_value[field], bool):
                raise EvaluationContractError(f"{field.replace('_', ' ')} must be boolean")
        gate = _bounded_string(
            input_value["evidence_gate_outcome"],
            name="recovery Evidence Gate outcome",
            maximum=32,
        )
        if gate not in {"fail", "pass"}:
            raise EvaluationContractError("recovery Evidence Gate outcome is not allowlisted")
        approval = _bounded_string(input_value["approval_input"], name="approval input", maximum=32)
        if approval not in ALLOWED_APPROVAL_INPUTS:
            raise EvaluationContractError("approval input is not allowlisted")
        verification = _bounded_string(
            input_value["verification_profile"],
            name="verification profile",
            maximum=32,
        )
        if verification not in ALLOWED_VERIFICATION_PROFILES:
            raise EvaluationContractError("verification profile is not allowlisted")
        action = _identifier(input_value["proposal_action"], name="proposal action")
        if action != "rollback_service":
            raise EvaluationContractError("recovery fixture action must be rollback_service")
        return cls(
            case_id,
            scenario_id,
            RecoverySafetyInput(
                case_id,
                action,
                input_value["proposal_schema_valid"],
                gate,
                input_value["stable_predecessor_present"],
                input_value["target_allowlisted"],
                approval,
                _integer(
                    input_value["duplicate_deliveries"],
                    name="duplicate deliveries",
                    minimum=1,
                    maximum=100,
                ),
                verification,
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        value = self.system_input.to_mapping()
        value.pop("case_id")
        return {"case_id": self.case_id, "input": value, "scenario_id": self.scenario_id}


@dataclass(frozen=True, slots=True)
class RecoverySafetyFixtureSet:
    """Versioned fixed inputs used independently of every diagnosis result."""

    fixture_version: str
    cases: tuple[RecoverySafetyCase, ...]
    document_json: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> RecoverySafetyFixtureSet:
        _exact_keys(
            value,
            frozenset({"cases", "fixture_version", "schema_version"}),
            name="recovery-safety fixture set",
        )
        if value["schema_version"] != RECOVERY_FIXTURE_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported recovery-safety fixture schema")
        cases_value = value["cases"]
        if not isinstance(cases_value, list) or not cases_value:
            raise EvaluationContractError("recovery-safety fixtures require cases")
        cases = tuple(RecoverySafetyCase.from_mapping(item) for item in cases_value)
        _validate_case_order([case.case_id for case in cases])
        return cls(
            _identifier(value["fixture_version"], name="recovery fixture version"),
            cases,
            canonical_json(value),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    @property
    def document(self) -> dict[str, Any]:
        value = json.loads(self.document_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor guarantees this
            raise EvaluationContractError("canonical recovery fixtures are not an object")
        return value


@dataclass(frozen=True, slots=True)
class RecoverySafetyCaseResult:
    """Recovery-only output with no diagnosis rank or candidate Evidence fields."""

    case_id: str
    status: str
    schema_validation_outcome: str
    policy_outcome: str
    approval_outcome: str
    executor_outcome: str
    executed_actions: int
    duplicate_executions: int
    verification_outcome: str
    final_route: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    duration_ms: int
    error_code: str | None

    @classmethod
    def from_mapping(
        cls, value: object, *, case_id: str, limits: EvaluationLimits
    ) -> RecoverySafetyCaseResult:
        if not isinstance(value, dict):
            raise EvaluationContractError("recovery-safety result must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "approval_outcome",
                    "case_id",
                    "cost_microusd",
                    "duplicate_executions",
                    "duration_ms",
                    "error_code",
                    "executed_actions",
                    "executor_outcome",
                    "final_route",
                    "input_tokens",
                    "output_tokens",
                    "policy_outcome",
                    "schema_validation_outcome",
                    "status",
                    "tool_calls",
                    "verification_outcome",
                }
            ),
            name="recovery-safety result",
        )
        if value["case_id"] != case_id:
            raise EvaluationContractError("recovery result case ID does not match its input")
        enums: tuple[tuple[str, frozenset[str], str], ...] = (
            ("schema_validation_outcome", ALLOWED_SCHEMA_OUTCOMES, "schema outcome"),
            ("policy_outcome", ALLOWED_POLICY_OUTCOMES, "policy outcome"),
            ("approval_outcome", ALLOWED_APPROVAL_OUTCOMES, "approval outcome"),
            ("executor_outcome", ALLOWED_EXECUTOR_OUTCOMES, "executor outcome"),
            ("verification_outcome", ALLOWED_VERIFICATION_OUTCOMES, "verification outcome"),
            ("final_route", ALLOWED_FINAL_ROUTES, "final route"),
        )
        parsed: dict[str, str] = {}
        for field, allowed, label in enums:
            parsed[field] = _bounded_string(value[field], name=label, maximum=32)
            if parsed[field] not in allowed:
                raise EvaluationContractError(f"{label} is not allowlisted")
        status = _bounded_string(value["status"], name="recovery status", maximum=32)
        if status not in ALLOWED_STATUSES:
            raise EvaluationContractError("recovery status is not allowlisted")
        return cls(
            case_id,
            status,
            parsed["schema_validation_outcome"],
            parsed["policy_outcome"],
            parsed["approval_outcome"],
            parsed["executor_outcome"],
            _integer(value["executed_actions"], name="executed actions", minimum=0, maximum=1000),
            _integer(
                value["duplicate_executions"],
                name="duplicate executions",
                minimum=0,
                maximum=1000,
            ),
            parsed["verification_outcome"],
            parsed["final_route"],
            _integer(
                value["tool_calls"],
                name="tool calls",
                minimum=0,
                maximum=limits.max_tool_calls,
            ),
            _integer(
                value["input_tokens"],
                name="input tokens",
                minimum=0,
                maximum=limits.max_tokens,
            ),
            _integer(
                value["output_tokens"],
                name="output tokens",
                minimum=0,
                maximum=limits.max_tokens,
            ),
            _integer(
                value["cost_microusd"],
                name="cost microusd",
                minimum=0,
                maximum=limits.max_cost_microusd,
            ),
            _integer(
                value["duration_ms"],
                name="duration milliseconds",
                minimum=0,
                maximum=limits.max_duration_ms,
            ),
            _stable_error_code(value["error_code"]),
        )

    @classmethod
    def adapter_failure(cls, case_id: str) -> RecoverySafetyCaseResult:
        return cls(
            case_id,
            "failed",
            "fail",
            "error",
            "not_requested",
            "not_run",
            0,
            0,
            "not_run",
            "failed",
            0,
            0,
            0,
            0,
            0,
            "ADAPTER_FAILURE",
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "approval_outcome": self.approval_outcome,
            "case_id": self.case_id,
            "cost_microusd": self.cost_microusd,
            "duplicate_executions": self.duplicate_executions,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "executed_actions": self.executed_actions,
            "executor_outcome": self.executor_outcome,
            "final_route": self.final_route,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "policy_outcome": self.policy_outcome,
            "schema_validation_outcome": self.schema_validation_outcome,
            "status": self.status,
            "tool_calls": self.tool_calls,
            "verification_outcome": self.verification_outcome,
        }


@dataclass(frozen=True, slots=True)
class TrackBinding:
    """Shared exact rules/fairness bindings on both track artifacts."""

    rules_version: str
    rules_sha256: str
    fairness_policy_version: str
    fairness_policy_sha256: str
    fairness_plan_version: str
    fairness_plan_sha256: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.rules_version, "rules version"),
            (self.fairness_policy_version, "fairness policy version"),
            (self.fairness_plan_version, "fairness plan version"),
        ):
            _identifier(value, name=name)
        for value, name in (
            (self.rules_sha256, "rules SHA-256"),
            (self.fairness_policy_sha256, "fairness policy SHA-256"),
            (self.fairness_plan_sha256, "fairness plan SHA-256"),
        ):
            _sha256(value, name=name)

    def to_mapping(self) -> dict[str, str]:
        return {
            "fairness_plan_sha256": self.fairness_plan_sha256,
            "fairness_plan_version": self.fairness_plan_version,
            "fairness_policy_sha256": self.fairness_policy_sha256,
            "fairness_policy_version": self.fairness_policy_version,
            "rules_sha256": self.rules_sha256,
            "rules_version": self.rules_version,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, rules: EvaluationRules) -> TrackBinding:
        _exact_keys(
            value,
            frozenset(
                {
                    "fairness_plan_sha256",
                    "fairness_plan_version",
                    "fairness_policy_sha256",
                    "fairness_policy_version",
                    "rules_sha256",
                    "rules_version",
                }
            ),
            name="track binding",
        )
        if (
            value["rules_version"] != rules.rules_version
            or value["rules_sha256"] != rules.fingerprint
        ):
            raise EvaluationContractError("track raw result is not bound to the supplied rules")
        return cls(
            value["rules_version"],
            value["rules_sha256"],
            value["fairness_policy_version"],
            value["fairness_policy_sha256"],
            value["fairness_plan_version"],
            value["fairness_plan_sha256"],
        )


@dataclass(frozen=True, slots=True)
class DiagnosisRawResult:
    """Raw diagnosis artifact with no recovery-safety outcome surface."""

    metadata: EvaluationRunMetadata
    dataset_version: str
    dataset_sha256: str
    binding: TrackBinding
    created_at: datetime
    cases: tuple[DiagnosisCaseResult, ...]

    def __post_init__(self) -> None:
        _identifier(self.dataset_version, name="diagnosis dataset version")
        _sha256(self.dataset_sha256, name="diagnosis dataset SHA-256")
        _validate_created_at(self.created_at, self.metadata)
        _validate_case_order([case.case_id for case in self.cases])

    def to_mapping(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_mapping(),
            "cases": [case.to_mapping() for case in self.cases],
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "dataset_sha256": self.dataset_sha256,
            "dataset_version": self.dataset_version,
            "metadata": self.metadata.to_mapping(),
            "schema_version": DIAGNOSIS_RAW_SCHEMA_VERSION,
            "track": DIAGNOSIS_TRACK,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, rules: EvaluationRules
    ) -> DiagnosisRawResult:
        _exact_keys(
            value,
            frozenset(
                {
                    "binding",
                    "cases",
                    "created_at",
                    "dataset_sha256",
                    "dataset_version",
                    "metadata",
                    "schema_version",
                    "track",
                }
            ),
            name="diagnosis raw result",
        )
        if (
            value["schema_version"] != DIAGNOSIS_RAW_SCHEMA_VERSION
            or value["track"] != DIAGNOSIS_TRACK
        ):
            raise EvaluationContractError("unsupported diagnosis raw-result contract")
        binding_value = value["binding"]
        if not isinstance(binding_value, dict):
            raise EvaluationContractError("diagnosis track binding must be an object")
        cases_value = value["cases"]
        if not isinstance(cases_value, list):
            raise EvaluationContractError("diagnosis raw cases must be a list")
        cases: list[DiagnosisCaseResult] = []
        for item in cases_value:
            if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
                raise EvaluationContractError("diagnosis raw case is malformed")
            cases.append(
                DiagnosisCaseResult.from_mapping(item, case_id=item["case_id"], limits=rules.limits)
            )
        return cls(
            EvaluationRunMetadata.from_mapping(value["metadata"]),
            value["dataset_version"],
            value["dataset_sha256"],
            TrackBinding.from_mapping(binding_value, rules=rules),
            _utc_datetime(value["created_at"], name="diagnosis raw timestamp"),
            tuple(cases),
        )

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.to_mapping())


@dataclass(frozen=True, slots=True)
class RecoverySafetyRawResult:
    """Raw recovery artifact independent of Diagnosis output and dataset labels."""

    metadata: EvaluationRunMetadata
    fixture_version: str
    fixture_sha256: str
    binding: TrackBinding
    created_at: datetime
    cases: tuple[RecoverySafetyCaseResult, ...]

    def __post_init__(self) -> None:
        _identifier(self.fixture_version, name="recovery fixture version")
        _sha256(self.fixture_sha256, name="recovery fixture SHA-256")
        _validate_created_at(self.created_at, self.metadata)
        _validate_case_order([case.case_id for case in self.cases])

    def to_mapping(self) -> dict[str, Any]:
        return {
            "binding": self.binding.to_mapping(),
            "cases": [case.to_mapping() for case in self.cases],
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "fixture_sha256": self.fixture_sha256,
            "fixture_version": self.fixture_version,
            "metadata": self.metadata.to_mapping(),
            "schema_version": RECOVERY_RAW_SCHEMA_VERSION,
            "track": RECOVERY_SAFETY_TRACK,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, rules: EvaluationRules
    ) -> RecoverySafetyRawResult:
        _exact_keys(
            value,
            frozenset(
                {
                    "binding",
                    "cases",
                    "created_at",
                    "fixture_sha256",
                    "fixture_version",
                    "metadata",
                    "schema_version",
                    "track",
                }
            ),
            name="recovery-safety raw result",
        )
        if (
            value["schema_version"] != RECOVERY_RAW_SCHEMA_VERSION
            or value["track"] != RECOVERY_SAFETY_TRACK
        ):
            raise EvaluationContractError("unsupported recovery-safety raw-result contract")
        binding_value = value["binding"]
        if not isinstance(binding_value, dict):
            raise EvaluationContractError("recovery track binding must be an object")
        cases_value = value["cases"]
        if not isinstance(cases_value, list):
            raise EvaluationContractError("recovery raw cases must be a list")
        cases: list[RecoverySafetyCaseResult] = []
        for item in cases_value:
            if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
                raise EvaluationContractError("recovery raw case is malformed")
            cases.append(
                RecoverySafetyCaseResult.from_mapping(
                    item, case_id=item["case_id"], limits=rules.limits
                )
            )
        return cls(
            EvaluationRunMetadata.from_mapping(value["metadata"]),
            value["fixture_version"],
            value["fixture_sha256"],
            TrackBinding.from_mapping(binding_value, rules=rules),
            _utc_datetime(value["created_at"], name="recovery raw timestamp"),
            tuple(cases),
        )

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.to_mapping())


TrackRawResult = DiagnosisRawResult | RecoverySafetyRawResult


def raw_track(value: Mapping[str, Any]) -> str:
    """Return a validated track discriminator without accepting ambiguous documents."""
    track = value.get("track")
    if not isinstance(track, str) or track not in {
        DIAGNOSIS_TRACK,
        RECOVERY_SAFETY_TRACK,
    }:
        raise EvaluationContractError("raw result has an unknown evaluation track")
    return track


def utc_now() -> datetime:
    """Clock default kept here so both track runners use the same UTC rule."""
    return datetime.now(UTC)

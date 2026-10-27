"""Strict versioned contracts for the isolated evaluation harness."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
HARNESS_VERSION = "1.0.0"
ALLOWED_STATUSES = frozenset({"completed", "failed", "handoff", "refused"})
ALLOWED_VERIFICATION_OUTCOMES = frozenset({"fail", "not_run", "pass"})
ALLOWED_SIGNAL_SOURCES = frozenset({"deployments", "logs", "metrics", "topology", "traces"})
REQUIRED_FORBIDDEN_OBSERVATION_FIELDS = frozenset(
    {
        "automation_eligible",
        "cause",
        "evaluator_cleanup",
        "expected_safe_outcome",
        "future_tool_requirement",
        "handoff_reason_code",
        "recovery_action",
    }
)
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SAFE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class EvaluationContractError(ValueError):
    """Raised when evaluation-only input violates a versioned contract."""


def canonical_json(value: Mapping[str, Any]) -> str:
    """Return the one canonical JSON representation used for persisted hashes."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise EvaluationContractError("evaluation document is not canonical JSON") from error


def content_sha256(value: Mapping[str, Any]) -> str:
    """Hash a canonical evaluation document."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json_object(path: Path, *, maximum_bytes: int = 1_048_576) -> dict[str, Any]:
    """Load one bounded UTF-8 JSON object without reflecting its content in errors."""
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise EvaluationContractError(f"evaluation file unavailable: {path.name}") from error
    if not payload or len(payload) > maximum_bytes:
        raise EvaluationContractError(f"invalid evaluation file size: {path.name}")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvaluationContractError(f"invalid evaluation JSON: {path.name}") from error
    if not isinstance(value, dict):
        raise EvaluationContractError(f"evaluation JSON must be an object: {path.name}")
    return value


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, name: str) -> None:
    keys = frozenset(value)
    if keys != expected:
        raise EvaluationContractError(f"{name} fields do not match the versioned contract")


def _bounded_string(value: object, *, name: str, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise EvaluationContractError(f"{name} must be a bounded non-empty string")
    if any(ord(character) < 32 for character in value):
        raise EvaluationContractError(f"{name} cannot contain control characters")
    return value


def _identifier(value: object, *, name: str) -> str:
    result = _bounded_string(value, name=name, maximum=128)
    if _SAFE_ID.fullmatch(result) is None:
        raise EvaluationContractError(f"{name} must be a safe identifier")
    return result


def _integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        raise EvaluationContractError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return value


def _parse_utc_datetime(value: object, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise EvaluationContractError(f"{name} must be an RFC 3339 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationContractError(f"{name} is malformed") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset() != timedelta(0):
        raise EvaluationContractError(f"{name} must use UTC")
    return parsed


def _string_sequence(
    value: object,
    *,
    name: str,
    maximum_items: int,
    item_maximum: int = 512,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise EvaluationContractError(f"{name} must be a bounded list")
    result = tuple(
        _bounded_string(item, name=f"{name} item", maximum=item_maximum) for item in value
    )
    if len(result) != len(set(result)):
        raise EvaluationContractError(f"{name} cannot contain duplicates")
    return result


@dataclass(frozen=True, slots=True)
class ObservationSignal:
    """One bounded, label-free observation exposed to a candidate baseline."""

    source: str
    summary: str

    @classmethod
    def from_mapping(cls, value: object) -> ObservationSignal:
        if not isinstance(value, dict):
            raise EvaluationContractError("observation signal must be an object")
        _exact_keys(value, frozenset({"source", "summary"}), name="observation signal")
        source = _bounded_string(value["source"], name="signal source", maximum=32)
        if source not in ALLOWED_SIGNAL_SOURCES:
            raise EvaluationContractError("signal source is not allowlisted")
        return cls(source, _bounded_string(value["summary"], name="signal summary", maximum=1000))

    def to_mapping(self) -> dict[str, Any]:
        return {"source": self.source, "summary": self.summary}


@dataclass(frozen=True, slots=True)
class EvaluationObservation:
    """The complete Ground-Truth-free input for one evaluation case."""

    alert_summary: str
    time_window_minutes: int
    signals: tuple[ObservationSignal, ...]
    available_tools: tuple[str, ...]

    @classmethod
    def from_mapping(
        cls, value: object, *, forbidden_fields: frozenset[str]
    ) -> EvaluationObservation:
        if not isinstance(value, dict):
            raise EvaluationContractError("case observation must be an object")
        _reject_forbidden_keys(value, forbidden_fields)
        _exact_keys(
            value,
            frozenset({"alert_summary", "available_tools", "signals", "time_window_minutes"}),
            name="case observation",
        )
        signals_value = value["signals"]
        if not isinstance(signals_value, list) or not 1 <= len(signals_value) <= 20:
            raise EvaluationContractError("observation signals must contain 1 to 20 items")
        signals = tuple(ObservationSignal.from_mapping(item) for item in signals_value)
        if len({item.source for item in signals}) != len(signals):
            raise EvaluationContractError("observation signal sources must be unique")
        return cls(
            _bounded_string(value["alert_summary"], name="alert summary", maximum=1000),
            _integer(
                value["time_window_minutes"],
                name="time window minutes",
                minimum=1,
                maximum=1440,
            ),
            signals,
            _string_sequence(
                value["available_tools"],
                name="available tools",
                maximum_items=20,
                item_maximum=64,
            ),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "alert_summary": self.alert_summary,
            "available_tools": list(self.available_tools),
            "signals": [signal.to_mapping() for signal in self.signals],
            "time_window_minutes": self.time_window_minutes,
        }


def _reject_forbidden_keys(value: object, forbidden_fields: frozenset[str]) -> None:
    if isinstance(value, dict):
        if forbidden_fields.intersection(value):
            raise EvaluationContractError("observation contains an evaluator-only field")
        for nested in value.values():
            _reject_forbidden_keys(nested, forbidden_fields)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_keys(nested, forbidden_fields)


@dataclass(frozen=True, slots=True)
class EvaluationCase:
    """One versioned, label-free evaluation case."""

    case_id: str
    scenario_id: str
    split: str
    observation: EvaluationObservation

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "observation": self.observation.to_mapping(),
            "scenario_id": self.scenario_id,
            "split": self.split,
        }


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    """Versioned collection of label-free candidate inputs."""

    dataset_version: str
    cases: tuple[EvaluationCase, ...]
    document_json: str

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, forbidden_fields: frozenset[str]
    ) -> EvaluationDataset:
        _exact_keys(
            value, frozenset({"cases", "dataset_version", "schema_version"}), name="dataset"
        )
        if value["schema_version"] != SCHEMA_VERSION:
            raise EvaluationContractError("unsupported evaluation dataset schema version")
        dataset_version = _identifier(value["dataset_version"], name="dataset version")
        cases_value = value["cases"]
        if not isinstance(cases_value, list) or not cases_value:
            raise EvaluationContractError("evaluation dataset must contain cases")
        cases: list[EvaluationCase] = []
        for item in cases_value:
            if not isinstance(item, dict):
                raise EvaluationContractError("evaluation case must be an object")
            _exact_keys(
                item,
                frozenset({"case_id", "observation", "scenario_id", "split"}),
                name="evaluation case",
            )
            split = _bounded_string(item["split"], name="dataset split", maximum=32)
            if split not in {"evaluation", "regression"}:
                raise EvaluationContractError("dataset split is not allowlisted")
            cases.append(
                EvaluationCase(
                    _identifier(item["case_id"], name="case ID"),
                    _identifier(item["scenario_id"], name="scenario ID"),
                    split,
                    EvaluationObservation.from_mapping(
                        item["observation"], forbidden_fields=forbidden_fields
                    ),
                )
            )
        case_ids = [case.case_id for case in cases]
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationContractError("evaluation case IDs must be unique")
        if case_ids != sorted(case_ids):
            raise EvaluationContractError("evaluation cases must use stable case-ID order")
        return cls(dataset_version, tuple(cases), canonical_json(value))

    @property
    def document(self) -> dict[str, Any]:
        """Return a detached copy of the canonical source document."""
        value = json.loads(self.document_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor makes this unreachable
            raise EvaluationContractError("canonical dataset document is not an object")
        return value

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvaluationLimits:
    """Resource and result bounds enforced before raw-result persistence."""

    max_cases: int
    max_observation_bytes: int
    max_top_k: int
    max_tool_calls: int
    max_tokens: int
    max_cost_microusd: int
    max_duration_ms: int


@dataclass(frozen=True, slots=True)
class EvaluationRules:
    """Versioned validation rules owned by the evaluator."""

    rules_version: str
    dataset_version: str
    limits: EvaluationLimits
    forbidden_observation_fields: frozenset[str]
    document_json: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> EvaluationRules:
        _exact_keys(
            value,
            frozenset(
                {
                    "allowed_statuses",
                    "dataset_version",
                    "forbidden_observation_fields",
                    "harness_version",
                    "limits",
                    "rules_version",
                    "schema_version",
                }
            ),
            name="evaluation rules",
        )
        if value["schema_version"] != SCHEMA_VERSION:
            raise EvaluationContractError("unsupported evaluation rules schema version")
        if value["harness_version"] != HARNESS_VERSION:
            raise EvaluationContractError("evaluation rules require a different harness version")
        statuses = _string_sequence(
            value["allowed_statuses"], name="allowed statuses", maximum_items=10, item_maximum=32
        )
        if frozenset(statuses) != ALLOWED_STATUSES:
            raise EvaluationContractError("allowed statuses cannot weaken the harness contract")
        forbidden = frozenset(
            _string_sequence(
                value["forbidden_observation_fields"],
                name="forbidden observation fields",
                maximum_items=50,
                item_maximum=64,
            )
        )
        if not REQUIRED_FORBIDDEN_OBSERVATION_FIELDS.issubset(forbidden):
            raise EvaluationContractError("evaluation rules omit required Ground Truth exclusions")
        limits_value = value["limits"]
        if not isinstance(limits_value, dict):
            raise EvaluationContractError("evaluation limits must be an object")
        _exact_keys(
            limits_value,
            frozenset(
                {
                    "max_cases",
                    "max_cost_microusd",
                    "max_duration_ms",
                    "max_observation_bytes",
                    "max_tokens",
                    "max_tool_calls",
                    "max_top_k",
                }
            ),
            name="evaluation limits",
        )
        limits = EvaluationLimits(
            _integer(limits_value["max_cases"], name="max cases", minimum=1, maximum=10_000),
            _integer(
                limits_value["max_observation_bytes"],
                name="max observation bytes",
                minimum=128,
                maximum=1_048_576,
            ),
            _integer(limits_value["max_top_k"], name="max top-k", minimum=1, maximum=10),
            _integer(
                limits_value["max_tool_calls"], name="max tool calls", minimum=1, maximum=10_000
            ),
            _integer(limits_value["max_tokens"], name="max tokens", minimum=1, maximum=10_000_000),
            _integer(
                limits_value["max_cost_microusd"],
                name="max cost microusd",
                minimum=0,
                maximum=10_000_000_000,
            ),
            _integer(
                limits_value["max_duration_ms"],
                name="max duration milliseconds",
                minimum=1,
                maximum=86_400_000,
            ),
        )
        return cls(
            _identifier(value["rules_version"], name="rules version"),
            _identifier(value["dataset_version"], name="rules dataset version"),
            limits,
            forbidden,
            canonical_json(value),
        )

    @property
    def document(self) -> dict[str, Any]:
        """Return a detached copy of the canonical source document."""
        value = json.loads(self.document_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor makes this unreachable
            raise EvaluationContractError("canonical rules document is not an object")
        return value

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateCaseResult:
    """Strict candidate output persisted before evaluator-only scoring."""

    case_id: str
    status: str
    diagnosis_top3: tuple[str, ...]
    cited_evidence_ids: tuple[str, ...]
    proposed_action: str | None
    executed_actions: int
    verification_outcome: str
    tool_calls: int
    input_tokens: int
    output_tokens: int
    cost_microusd: int
    duration_ms: int
    error_code: str | None

    @classmethod
    def from_mapping(
        cls, value: object, *, case_id: str, limits: EvaluationLimits
    ) -> CandidateCaseResult:
        if not isinstance(value, dict):
            raise EvaluationContractError("candidate result must be an object")
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
                    "executed_actions",
                    "input_tokens",
                    "output_tokens",
                    "proposed_action",
                    "status",
                    "tool_calls",
                    "verification_outcome",
                }
            ),
            name="candidate result",
        )
        if value["case_id"] != case_id:
            raise EvaluationContractError("candidate result case ID does not match its input")
        status = _bounded_string(value["status"], name="candidate status", maximum=32)
        if status not in ALLOWED_STATUSES:
            raise EvaluationContractError("candidate status is not allowlisted")
        verification = _bounded_string(
            value["verification_outcome"], name="verification outcome", maximum=32
        )
        if verification not in ALLOWED_VERIFICATION_OUTCOMES:
            raise EvaluationContractError("verification outcome is not allowlisted")
        proposed = value["proposed_action"]
        if proposed is not None:
            proposed = _identifier(proposed, name="proposed action")
        error_code = value["error_code"]
        if error_code is not None:
            error_code = _bounded_string(error_code, name="error code", maximum=128)
            if _SAFE_CODE.fullmatch(error_code) is None:
                raise EvaluationContractError("error code must be a stable uppercase code")
        return cls(
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
            proposed,
            _integer(value["executed_actions"], name="executed actions", minimum=0, maximum=1000),
            verification,
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
            error_code,
        )

    @classmethod
    def adapter_failure(cls, case_id: str) -> CandidateCaseResult:
        return cls(
            case_id,
            "failed",
            (),
            (),
            None,
            0,
            "not_run",
            0,
            0,
            0,
            0,
            0,
            "ADAPTER_FAILURE",
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "cost_microusd": self.cost_microusd,
            "diagnosis_top3": list(self.diagnosis_top3),
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "executed_actions": self.executed_actions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "proposed_action": self.proposed_action,
            "status": self.status,
            "tool_calls": self.tool_calls,
            "verification_outcome": self.verification_outcome,
        }


@dataclass(frozen=True, slots=True)
class EvaluationRunMetadata:
    """Reproduction metadata required on every raw evaluation run."""

    run_id: str
    baseline_id: str
    baseline_version: str
    code_revision: str
    scenario_version: str
    ground_truth_manifest_set_sha256: str
    model_id: str
    model_settings_sha256: str
    prompt_version: str
    policy_version: str
    tool_schema_versions: tuple[tuple[str, str], ...]
    python_version: str
    platform: str
    hardware_summary: str
    concurrency: int
    seed: int
    started_at: datetime
    finished_at: datetime

    def __post_init__(self) -> None:
        for name in ("run_id", "baseline_id", "baseline_version", "code_revision"):
            _identifier(getattr(self, name), name=name.replace("_", " "))
        for name in (
            "scenario_version",
            "model_id",
            "prompt_version",
            "policy_version",
            "python_version",
            "platform",
            "hardware_summary",
        ):
            _bounded_string(getattr(self, name), name=name.replace("_", " "), maximum=256)
        for value, name in (
            (self.ground_truth_manifest_set_sha256, "Ground Truth manifest-set SHA-256"),
            (self.model_settings_sha256, "model settings SHA-256"),
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise EvaluationContractError(f"{name} must be canonical lowercase hex")
        if not self.tool_schema_versions or len(self.tool_schema_versions) > 50:
            raise EvaluationContractError("tool schema versions must be a bounded non-empty set")
        names: list[str] = []
        for name, version in self.tool_schema_versions:
            names.append(_identifier(name, name="tool name"))
            _bounded_string(version, name="tool schema version", maximum=64)
        if len(names) != len(set(names)) or names != sorted(names):
            raise EvaluationContractError("tool schema versions must be unique and stably ordered")
        _integer(self.concurrency, name="concurrency", minimum=1, maximum=1024)
        _integer(self.seed, name="seed", minimum=0, maximum=2_147_483_647)
        for timestamp, name in (
            (self.started_at, "run start"),
            (self.finished_at, "run finish"),
        ):
            if (
                timestamp.tzinfo is None
                or timestamp.utcoffset() is None
                or timestamp.utcoffset() != timedelta(0)
            ):
                raise EvaluationContractError(f"{name} must use UTC")
        if self.finished_at < self.started_at:
            raise EvaluationContractError("run finish cannot precede run start")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "baseline_id": self.baseline_id,
            "baseline_version": self.baseline_version,
            "code_revision": self.code_revision,
            "concurrency": self.concurrency,
            "finished_at": self.finished_at.isoformat().replace("+00:00", "Z"),
            "ground_truth_manifest_set_sha256": self.ground_truth_manifest_set_sha256,
            "hardware_summary": self.hardware_summary,
            "model_id": self.model_id,
            "model_settings_sha256": self.model_settings_sha256,
            "platform": self.platform,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "python_version": self.python_version,
            "run_id": self.run_id,
            "scenario_version": self.scenario_version,
            "seed": self.seed,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "tool_schema_versions": dict(self.tool_schema_versions),
        }

    @classmethod
    def from_mapping(cls, value: object) -> EvaluationRunMetadata:
        if not isinstance(value, dict):
            raise EvaluationContractError("raw result metadata must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "baseline_id",
                    "baseline_version",
                    "code_revision",
                    "concurrency",
                    "finished_at",
                    "ground_truth_manifest_set_sha256",
                    "hardware_summary",
                    "model_id",
                    "model_settings_sha256",
                    "platform",
                    "policy_version",
                    "prompt_version",
                    "python_version",
                    "run_id",
                    "scenario_version",
                    "seed",
                    "started_at",
                    "tool_schema_versions",
                }
            ),
            name="raw result metadata",
        )
        tools = value["tool_schema_versions"]
        if not isinstance(tools, dict):
            raise EvaluationContractError("tool schema versions must be an object")
        started_at = _parse_utc_datetime(value["started_at"], name="run start")
        finished_at = _parse_utc_datetime(value["finished_at"], name="run finish")
        return cls(
            value["run_id"],
            value["baseline_id"],
            value["baseline_version"],
            value["code_revision"],
            value["scenario_version"],
            value["ground_truth_manifest_set_sha256"],
            value["model_id"],
            value["model_settings_sha256"],
            value["prompt_version"],
            value["policy_version"],
            tuple(sorted(tools.items())),
            value["python_version"],
            value["platform"],
            value["hardware_summary"],
            value["concurrency"],
            value["seed"],
            started_at,
            finished_at,
        )


@dataclass(frozen=True, slots=True)
class RawEvaluationResult:
    """Version/hash-bound raw result emitted before scoring or reporting."""

    metadata: EvaluationRunMetadata
    dataset_version: str
    dataset_sha256: str
    rules_version: str
    rules_sha256: str
    created_at: datetime
    cases: tuple[CandidateCaseResult, ...]

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise EvaluationContractError("raw result timestamp must be timezone-aware")
        if self.created_at.utcoffset() != UTC.utcoffset(self.created_at):
            raise EvaluationContractError("raw result timestamp must use UTC")
        if self.created_at < self.metadata.finished_at:
            raise EvaluationContractError("raw result cannot predate run completion")
        for value, name in (
            (self.dataset_version, "dataset version"),
            (self.rules_version, "rules version"),
        ):
            _identifier(value, name=name)
        for value, name in (
            (self.dataset_sha256, "dataset SHA-256"),
            (self.rules_sha256, "rules SHA-256"),
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise EvaluationContractError(f"{name} must be canonical lowercase hex")
        case_ids = [case.case_id for case in self.cases]
        if not case_ids or len(case_ids) != len(set(case_ids)) or case_ids != sorted(case_ids):
            raise EvaluationContractError("raw result cases must be unique and stably ordered")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "cases": [case.to_mapping() for case in self.cases],
            "created_at": self.created_at.isoformat().replace("+00:00", "Z"),
            "dataset_sha256": self.dataset_sha256,
            "dataset_version": self.dataset_version,
            "harness_version": HARNESS_VERSION,
            "metadata": self.metadata.to_mapping(),
            "rules_sha256": self.rules_sha256,
            "rules_version": self.rules_version,
            "schema_version": SCHEMA_VERSION,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], *, rules: EvaluationRules
    ) -> RawEvaluationResult:
        _exact_keys(
            value,
            frozenset(
                {
                    "cases",
                    "created_at",
                    "dataset_sha256",
                    "dataset_version",
                    "harness_version",
                    "metadata",
                    "rules_sha256",
                    "rules_version",
                    "schema_version",
                }
            ),
            name="raw evaluation result",
        )
        if value["schema_version"] != SCHEMA_VERSION:
            raise EvaluationContractError("unsupported raw-result schema version")
        if value["harness_version"] != HARNESS_VERSION:
            raise EvaluationContractError("raw result uses a different harness version")
        if (
            value["rules_version"] != rules.rules_version
            or value["rules_sha256"] != rules.fingerprint
        ):
            raise EvaluationContractError("raw result is not bound to the supplied rules")
        created = value["created_at"]
        if not isinstance(created, str):
            raise EvaluationContractError("raw result timestamp must be a string")
        try:
            created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError as error:
            raise EvaluationContractError("raw result timestamp is malformed") from error
        cases_value = value["cases"]
        if not isinstance(cases_value, list):
            raise EvaluationContractError("raw result cases must be a list")
        cases: list[CandidateCaseResult] = []
        for item in cases_value:
            if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
                raise EvaluationContractError("raw result case is malformed")
            cases.append(
                CandidateCaseResult.from_mapping(
                    item,
                    case_id=item["case_id"],
                    limits=rules.limits,
                )
            )
        return cls(
            EvaluationRunMetadata.from_mapping(value["metadata"]),
            value["dataset_version"],
            value["dataset_sha256"],
            value["rules_version"],
            value["rules_sha256"],
            created_at,
            tuple(cases),
        )

    @property
    def fingerprint(self) -> str:
        return content_sha256(self.to_mapping())


def ensure_dataset_rules_compatible(dataset: EvaluationDataset, rules: EvaluationRules) -> None:
    """Reject cross-version or over-limit suite composition."""
    if dataset.dataset_version != rules.dataset_version:
        raise EvaluationContractError("dataset and rules versions do not match")
    if len(dataset.cases) > rules.limits.max_cases:
        raise EvaluationContractError("dataset exceeds the configured case limit")
    for case in dataset.cases:
        size = len(canonical_json(case.observation.to_mapping()).encode("utf-8"))
        if size > rules.limits.max_observation_bytes:
            raise EvaluationContractError("case observation exceeds the configured byte limit")

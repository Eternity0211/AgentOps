"""Versioned baseline-fairness contracts for evaluation runs."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from evaluation.contracts import (
    EvaluationContractError,
    EvaluationDataset,
    EvaluationRules,
    EvaluationRunMetadata,
    canonical_json,
)


class ResourceUsage(Protocol):
    """Minimum resource surface accepted by the shared aggregate-budget gate."""

    @property
    def tool_calls(self) -> int: ...

    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...

    @property
    def cost_microusd(self) -> int: ...

    @property
    def duration_ms(self) -> int: ...


FAIRNESS_SCHEMA_VERSION = "1.0"
REQUIRED_BASELINE_KINDS = (
    "controlled-langgraph",
    "controlled-langgraph-memory",
    "rules",
    "single-agent",
)
REQUIRED_COMPARISON_SPECS = (
    ("controlled-langgraph", "controlled-langgraph-memory", "historical-memory"),
    ("rules", "single-agent", "diagnostic-strategy"),
    ("single-agent", "controlled-langgraph", "orchestration"),
)
REQUIRED_SHARED_DIMENSIONS = (
    "dataset",
    "observations",
    "safety-chain",
    "split",
    "tool-schemas",
)
REQUIRED_MODEL_SHARED_DIMENSIONS = (
    "aggregate-budget",
    "model-id",
    "model-settings",
)
REQUIRED_RULES_EXEMPTIONS = (
    "max-context-tokens",
    "max-cost-microusd",
    "max-model-tokens",
)
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], *, name: str) -> None:
    if frozenset(value) != expected:
        raise EvaluationContractError(f"{name} fields do not match the closed contract")


def _identifier(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise EvaluationContractError(f"{name} must be a canonical identifier")
    return value


def _sha256(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise EvaluationContractError(f"{name} must be canonical lowercase hex")
    return value


def _bounded_integer(value: object, *, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EvaluationContractError(f"{name} is outside its integer bounds")
    return value


def _string_tuple(value: object, *, name: str, maximum_items: int = 32) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= maximum_items:
        raise EvaluationContractError(f"{name} must be a bounded non-empty list")
    result = tuple(_identifier(item, name=name) for item in value)
    if len(result) != len(set(result)) or result != tuple(sorted(result)):
        raise EvaluationContractError(f"{name} must be unique and stably ordered")
    return result


@dataclass(frozen=True, slots=True)
class FairnessPolicy:
    """Non-weakenable policy defining the permitted baseline comparison design."""

    policy_version: str
    document_json: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> FairnessPolicy:
        _exact_keys(
            value,
            frozenset(
                {
                    "model_shared_dimensions",
                    "policy_version",
                    "required_baseline_kinds",
                    "required_comparisons",
                    "rules_budget_exemptions",
                    "schema_version",
                    "shared_dimensions",
                }
            ),
            name="fairness policy",
        )
        if value["schema_version"] != FAIRNESS_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported fairness-policy schema version")
        if _string_tuple(value["required_baseline_kinds"], name="baseline kinds") != (
            REQUIRED_BASELINE_KINDS
        ):
            raise EvaluationContractError("fairness policy cannot change required baselines")
        if _string_tuple(value["shared_dimensions"], name="shared dimensions") != (
            REQUIRED_SHARED_DIMENSIONS
        ):
            raise EvaluationContractError("fairness policy cannot weaken shared dimensions")
        if (
            _string_tuple(value["model_shared_dimensions"], name="model shared dimensions")
            != REQUIRED_MODEL_SHARED_DIMENSIONS
        ):
            raise EvaluationContractError("fairness policy cannot weaken model controls")
        if (
            _string_tuple(value["rules_budget_exemptions"], name="rules budget exemptions")
            != REQUIRED_RULES_EXEMPTIONS
        ):
            raise EvaluationContractError("fairness policy has invalid rules exemptions")
        comparisons_value = value["required_comparisons"]
        if not isinstance(comparisons_value, list):
            raise EvaluationContractError("required comparisons must be a list")
        comparisons: list[tuple[str, str, str]] = []
        for item in comparisons_value:
            if not isinstance(item, dict):
                raise EvaluationContractError("required comparison must be an object")
            _exact_keys(
                item,
                frozenset({"independent_variable", "left_kind", "right_kind"}),
                name="required comparison",
            )
            comparisons.append(
                (
                    _identifier(item["left_kind"], name="left baseline kind"),
                    _identifier(item["right_kind"], name="right baseline kind"),
                    _identifier(item["independent_variable"], name="independent variable"),
                )
            )
        if tuple(sorted(comparisons)) != REQUIRED_COMPARISON_SPECS:
            raise EvaluationContractError("fairness policy cannot change required comparisons")
        return cls(
            _identifier(value["policy_version"], name="fairness policy version"),
            canonical_json(value),
        )

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class AggregateBudget:
    """Run-wide resource ceiling passed unchanged to a candidate adapter."""

    max_context_tokens: int
    max_model_tokens: int
    max_tool_calls: int
    max_retries: int
    max_duration_ms: int
    max_cost_microusd: int

    @classmethod
    def from_mapping(cls, value: object) -> AggregateBudget:
        if not isinstance(value, dict):
            raise EvaluationContractError("aggregate budget must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "max_context_tokens",
                    "max_cost_microusd",
                    "max_duration_ms",
                    "max_model_tokens",
                    "max_retries",
                    "max_tool_calls",
                }
            ),
            name="aggregate budget",
        )
        return cls(
            _bounded_integer(
                value["max_context_tokens"],
                name="maximum context tokens",
                minimum=0,
                maximum=10_000_000,
            ),
            _bounded_integer(
                value["max_model_tokens"],
                name="maximum model tokens",
                minimum=0,
                maximum=10_000_000,
            ),
            _bounded_integer(
                value["max_tool_calls"],
                name="maximum tool calls",
                minimum=1,
                maximum=1_000_000,
            ),
            _bounded_integer(
                value["max_retries"], name="maximum retries", minimum=0, maximum=10_000
            ),
            _bounded_integer(
                value["max_duration_ms"],
                name="maximum duration milliseconds",
                minimum=1,
                maximum=604_800_000,
            ),
            _bounded_integer(
                value["max_cost_microusd"],
                name="maximum cost microusd",
                minimum=0,
                maximum=1_000_000_000_000,
            ),
        )

    def to_mapping(self) -> dict[str, int]:
        return {
            "max_context_tokens": self.max_context_tokens,
            "max_cost_microusd": self.max_cost_microusd,
            "max_duration_ms": self.max_duration_ms,
            "max_model_tokens": self.max_model_tokens,
            "max_retries": self.max_retries,
            "max_tool_calls": self.max_tool_calls,
        }


@dataclass(frozen=True, slots=True)
class SafetyChainBinding:
    """Exact deterministic recovery-chain versions shared by every baseline."""

    schema_validation_version: str
    evidence_schema_version: str
    evidence_gate_version: str
    policy_version: str
    approval_version: str
    executor_version: str
    verifier_version: str

    @classmethod
    def from_mapping(cls, value: object) -> SafetyChainBinding:
        if not isinstance(value, dict):
            raise EvaluationContractError("safety-chain binding must be an object")
        fields = (
            "approval_version",
            "evidence_gate_version",
            "evidence_schema_version",
            "executor_version",
            "policy_version",
            "schema_validation_version",
            "verifier_version",
        )
        _exact_keys(value, frozenset(fields), name="safety-chain binding")
        parsed = {
            field: _identifier(value[field], name=field.replace("_", " ")) for field in fields
        }
        return cls(
            parsed["schema_validation_version"],
            parsed["evidence_schema_version"],
            parsed["evidence_gate_version"],
            parsed["policy_version"],
            parsed["approval_version"],
            parsed["executor_version"],
            parsed["verifier_version"],
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "approval_version": self.approval_version,
            "evidence_gate_version": self.evidence_gate_version,
            "evidence_schema_version": self.evidence_schema_version,
            "executor_version": self.executor_version,
            "policy_version": self.policy_version,
            "schema_validation_version": self.schema_validation_version,
            "verifier_version": self.verifier_version,
        }


@dataclass(frozen=True, slots=True)
class BaselineProfile:
    """Exact candidate configuration declared before any comparison run."""

    baseline_id: str
    baseline_version: str
    kind: str
    orchestration: str
    memory_access: bool
    model_id: str | None
    model_settings_sha256: str | None
    prompt_version: str
    budget: AggregateBudget

    @classmethod
    def from_mapping(cls, value: object) -> BaselineProfile:
        if not isinstance(value, dict):
            raise EvaluationContractError("baseline profile must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "aggregate_budget",
                    "baseline_id",
                    "baseline_version",
                    "kind",
                    "memory_access",
                    "model_id",
                    "model_settings_sha256",
                    "orchestration",
                    "prompt_version",
                }
            ),
            name="baseline profile",
        )
        model_id = value["model_id"]
        if model_id is not None:
            model_id = _identifier(model_id, name="model ID")
        settings = value["model_settings_sha256"]
        if settings is not None:
            settings = _sha256(settings, name="model settings SHA-256")
        if not isinstance(value["memory_access"], bool):
            raise EvaluationContractError("memory access must be boolean")
        return cls(
            _identifier(value["baseline_id"], name="baseline ID"),
            _identifier(value["baseline_version"], name="baseline version"),
            _identifier(value["kind"], name="baseline kind"),
            _identifier(value["orchestration"], name="orchestration"),
            value["memory_access"],
            model_id,
            settings,
            _identifier(value["prompt_version"], name="prompt version"),
            AggregateBudget.from_mapping(value["aggregate_budget"]),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "aggregate_budget": self.budget.to_mapping(),
            "baseline_id": self.baseline_id,
            "baseline_version": self.baseline_version,
            "kind": self.kind,
            "memory_access": self.memory_access,
            "model_id": self.model_id,
            "model_settings_sha256": self.model_settings_sha256,
            "orchestration": self.orchestration,
            "prompt_version": self.prompt_version,
        }


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """One pair with exactly one declared independent variable."""

    comparison_id: str
    left_baseline_id: str
    right_baseline_id: str
    independent_variable: str
    interface_prompt_change: str | None

    @classmethod
    def from_mapping(cls, value: object) -> BaselineComparison:
        if not isinstance(value, dict):
            raise EvaluationContractError("baseline comparison must be an object")
        _exact_keys(
            value,
            frozenset(
                {
                    "comparison_id",
                    "independent_variable",
                    "interface_prompt_change",
                    "left_baseline_id",
                    "right_baseline_id",
                }
            ),
            name="baseline comparison",
        )
        prompt_change = value["interface_prompt_change"]
        if prompt_change is not None:
            prompt_change = _identifier(prompt_change, name="interface prompt change")
        return cls(
            _identifier(value["comparison_id"], name="comparison ID"),
            _identifier(value["left_baseline_id"], name="left baseline ID"),
            _identifier(value["right_baseline_id"], name="right baseline ID"),
            _identifier(value["independent_variable"], name="independent variable"),
            prompt_change,
        )


@dataclass(frozen=True, slots=True)
class CandidateExecutionConfig:
    """Immutable, label-free configuration supplied to a candidate adapter."""

    profile: BaselineProfile
    tool_schema_versions: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class FairnessPlan:
    """Concrete, hash-bound comparison plan declared before baseline execution."""

    plan_version: str
    fairness_policy_version: str
    fairness_policy_sha256: str
    dataset_version: str
    dataset_sha256: str
    rules_version: str
    rules_sha256: str
    split: str
    tool_schema_versions: tuple[tuple[str, str], ...]
    safety_chain: SafetyChainBinding
    baselines: tuple[BaselineProfile, ...]
    comparisons: tuple[BaselineComparison, ...]
    document_json: str

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        policy: FairnessPolicy,
        dataset: EvaluationDataset,
        rules: EvaluationRules,
    ) -> FairnessPlan:
        _exact_keys(
            value,
            frozenset(
                {
                    "baselines",
                    "comparisons",
                    "dataset_sha256",
                    "dataset_version",
                    "fairness_policy_sha256",
                    "fairness_policy_version",
                    "plan_version",
                    "rules_sha256",
                    "rules_version",
                    "safety_chain",
                    "schema_version",
                    "split",
                    "tool_schema_versions",
                }
            ),
            name="fairness plan",
        )
        if value["schema_version"] != FAIRNESS_SCHEMA_VERSION:
            raise EvaluationContractError("unsupported fairness-plan schema version")
        if (
            value["fairness_policy_version"] != policy.policy_version
            or value["fairness_policy_sha256"] != policy.fingerprint
        ):
            raise EvaluationContractError("fairness plan is not bound to the supplied policy")
        if (
            value["dataset_version"] != dataset.dataset_version
            or value["dataset_sha256"] != dataset.fingerprint
        ):
            raise EvaluationContractError("fairness plan is not bound to the supplied dataset")
        if (
            value["rules_version"] != rules.rules_version
            or value["rules_sha256"] != rules.fingerprint
        ):
            raise EvaluationContractError("fairness plan is not bound to the supplied rules")
        split = _identifier(value["split"], name="dataset split")
        if {case.split for case in dataset.cases} != {split}:
            raise EvaluationContractError(
                "fairness plan must use the complete shared dataset split"
            )
        tools_value = value["tool_schema_versions"]
        if not isinstance(tools_value, dict) or not tools_value:
            raise EvaluationContractError("tool schema versions must be a non-empty object")
        tools = tuple(
            sorted(
                (
                    _identifier(name, name="tool name"),
                    _identifier(version, name="tool schema version"),
                )
                for name, version in tools_value.items()
            )
        )
        if len(tools) != len(tools_value):
            raise EvaluationContractError("tool schema versions must be unique")
        expected_tools = frozenset(name for name, _ in tools)
        if any(
            frozenset(case.observation.available_tools) != expected_tools for case in dataset.cases
        ):
            raise EvaluationContractError(
                "fairness plan tool schemas differ from case observations"
            )
        baselines_value = value["baselines"]
        if not isinstance(baselines_value, list):
            raise EvaluationContractError("fairness-plan baselines must be a list")
        baselines = tuple(BaselineProfile.from_mapping(item) for item in baselines_value)
        comparisons_value = value["comparisons"]
        if not isinstance(comparisons_value, list):
            raise EvaluationContractError("fairness-plan comparisons must be a list")
        comparisons = tuple(BaselineComparison.from_mapping(item) for item in comparisons_value)
        plan = cls(
            _identifier(value["plan_version"], name="fairness plan version"),
            policy.policy_version,
            policy.fingerprint,
            dataset.dataset_version,
            dataset.fingerprint,
            rules.rules_version,
            rules.fingerprint,
            split,
            tools,
            SafetyChainBinding.from_mapping(value["safety_chain"]),
            baselines,
            comparisons,
            canonical_json(value),
        )
        plan._validate_design()
        return plan

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.document_json.encode("utf-8")).hexdigest()

    def _validate_design(self) -> None:
        baseline_ids = [item.baseline_id for item in self.baselines]
        kinds = [item.kind for item in self.baselines]
        if (
            len(baseline_ids) != len(set(baseline_ids))
            or baseline_ids != sorted(baseline_ids)
            or tuple(sorted(kinds)) != REQUIRED_BASELINE_KINDS
            or len(kinds) != len(set(kinds))
        ):
            raise EvaluationContractError(
                "fairness plan requires one stably ordered profile per baseline kind"
            )
        by_kind = {item.kind: item for item in self.baselines}
        expected_shape = {
            "controlled-langgraph": ("langgraph", False),
            "controlled-langgraph-memory": ("langgraph", True),
            "rules": ("deterministic", False),
            "single-agent": ("single-pass", False),
        }
        for kind, (orchestration, memory_access) in expected_shape.items():
            profile = by_kind[kind]
            if profile.orchestration != orchestration or profile.memory_access is not memory_access:
                raise EvaluationContractError(
                    "baseline changes an undeclared orchestration variable"
                )
        rules_profile = by_kind["rules"]
        if rules_profile.model_id is not None or rules_profile.model_settings_sha256 is not None:
            raise EvaluationContractError("rules baseline cannot declare a model")
        if any(
            value != 0
            for value in (
                rules_profile.budget.max_context_tokens,
                rules_profile.budget.max_model_tokens,
                rules_profile.budget.max_cost_microusd,
            )
        ):
            raise EvaluationContractError(
                "rules baseline may use only declared model-budget exemptions"
            )
        model_profiles = tuple(
            by_kind[kind]
            for kind in (
                "single-agent",
                "controlled-langgraph",
                "controlled-langgraph-memory",
            )
        )
        if any(
            item.model_id is None or item.model_settings_sha256 is None for item in model_profiles
        ):
            raise EvaluationContractError("model baselines require model and settings bindings")
        first = model_profiles[0]
        if any(
            (item.model_id, item.model_settings_sha256, item.budget)
            != (first.model_id, first.model_settings_sha256, first.budget)
            for item in model_profiles[1:]
        ):
            raise EvaluationContractError("model baselines must share model, settings, and budget")
        if any(
            value <= 0
            for value in (
                first.budget.max_context_tokens,
                first.budget.max_model_tokens,
            )
        ):
            raise EvaluationContractError("model baselines require positive model budgets")
        if (
            rules_profile.budget.max_tool_calls != first.budget.max_tool_calls
            or rules_profile.budget.max_retries != first.budget.max_retries
            or rules_profile.budget.max_duration_ms != first.budget.max_duration_ms
        ):
            raise EvaluationContractError(
                "rules baseline must share applicable aggregate query and duration budgets"
            )
        comparison_ids = [item.comparison_id for item in self.comparisons]
        if len(comparison_ids) != len(set(comparison_ids)) or comparison_ids != sorted(
            comparison_ids
        ):
            raise EvaluationContractError("comparisons must be unique and stably ordered")
        by_id = {item.baseline_id: item for item in self.baselines}
        actual_specs: list[tuple[str, str, str]] = []
        for comparison in self.comparisons:
            if (
                comparison.left_baseline_id not in by_id
                or comparison.right_baseline_id not in by_id
                or comparison.left_baseline_id == comparison.right_baseline_id
            ):
                raise EvaluationContractError("comparison references an invalid baseline pair")
            left = by_id[comparison.left_baseline_id]
            right = by_id[comparison.right_baseline_id]
            prompt_changed = left.prompt_version != right.prompt_version
            expected_prompt_change = (
                f"{comparison.independent_variable}-interface" if prompt_changed else None
            )
            if comparison.interface_prompt_change != expected_prompt_change:
                raise EvaluationContractError(
                    "prompt variation must be explicitly bound to the independent variable"
                )
            actual_specs.append(
                (
                    left.kind,
                    right.kind,
                    comparison.independent_variable,
                )
            )
        if tuple(sorted(actual_specs)) != REQUIRED_COMPARISON_SPECS:
            raise EvaluationContractError(
                "comparison pairs must declare exactly one permitted independent variable"
            )

    def execution_config(self, metadata: EvaluationRunMetadata) -> CandidateExecutionConfig:
        """Resolve and validate the exact predeclared profile for one run."""
        matches = tuple(
            profile
            for profile in self.baselines
            if profile.baseline_id == metadata.baseline_id
            and profile.baseline_version == metadata.baseline_version
        )
        if len(matches) != 1:
            raise EvaluationContractError("run metadata does not identify one fairness profile")
        profile = matches[0]
        if (
            metadata.model_id != profile.model_id
            or metadata.model_settings_sha256 != profile.model_settings_sha256
            or metadata.prompt_version != profile.prompt_version
            or metadata.policy_version != self.safety_chain.policy_version
            or metadata.tool_schema_versions != self.tool_schema_versions
        ):
            raise EvaluationContractError("run metadata differs from the fairness plan")
        return CandidateExecutionConfig(profile, self.tool_schema_versions)

    def enforce_aggregate_budget(
        self, profile: BaselineProfile, results: Sequence[ResourceUsage]
    ) -> None:
        """Fail closed when reported run totals exceed the predeclared ceiling."""
        total_tool_calls = sum(item.tool_calls for item in results)
        total_tokens = sum(item.input_tokens + item.output_tokens for item in results)
        total_cost = sum(item.cost_microusd for item in results)
        total_duration = sum(item.duration_ms for item in results)
        budget = profile.budget
        if total_tool_calls > budget.max_tool_calls:
            raise EvaluationContractError("candidate exceeded aggregate tool-call budget")
        if total_tokens > budget.max_model_tokens:
            raise EvaluationContractError("candidate exceeded aggregate model-token budget")
        if total_cost > budget.max_cost_microusd:
            raise EvaluationContractError("candidate exceeded aggregate cost budget")
        if total_duration > budget.max_duration_ms:
            raise EvaluationContractError("candidate exceeded aggregate duration budget")


def load_fairness_policy(value: Mapping[str, Any]) -> FairnessPolicy:
    """Load a policy mapping through the closed, non-weakenable contract."""
    return FairnessPolicy.from_mapping(value)


def fairness_document(plan: FairnessPlan) -> dict[str, Any]:
    """Return a detached plan document for safe persistence or inspection."""
    value = json.loads(plan.document_json)
    if not isinstance(value, dict):  # pragma: no cover - constructor makes this unreachable
        raise EvaluationContractError("canonical fairness plan is not an object")
    return value

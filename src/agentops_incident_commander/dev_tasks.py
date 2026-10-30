"""Cross-platform development task runner with a fixed command allowlist."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One bounded developer command executed without a shell."""

    label: str
    argv: tuple[str, ...]
    timeout_seconds: int


class TaskConfigurationError(ValueError):
    """Raised when a requested task is known but not currently available."""


QUALITY_COMMANDS = (
    CommandSpec("lock", ("uv", "lock", "--check"), 60),
    CommandSpec("format", ("uv", "run", "--frozen", "ruff", "format", "--check", "."), 60),
    CommandSpec("lint", ("uv", "run", "--frozen", "ruff", "check", "."), 60),
    CommandSpec(
        "architecture",
        ("uv", "run", "--frozen", "python", "scripts/check_architecture.py"),
        60,
    ),
    CommandSpec(
        "compose",
        ("uv", "run", "--frozen", "python", "scripts/check_compose.py"),
        60,
    ),
    CommandSpec(
        "types",
        ("uv", "run", "--frozen", "mypy", "src", "scripts", "evaluation", "tests"),
        120,
    ),
    CommandSpec("tests", ("uv", "run", "--frozen", "pytest"), 300),
    CommandSpec(
        "planning-docs",
        ("pwsh", "-NoProfile", "-File", "scripts/check_planning_docs.ps1"),
        60,
    ),
    CommandSpec("build", ("uv", "build", "--offline", "--no-sources"), 120),
)

UNIT_SAFETY_COVERAGE_TARGETS = (
    "agentops_incident_commander.domain",
    "agentops_incident_commander.application.evidence_gate",
    "agentops_incident_commander.application.policy_engine",
    "agentops_incident_commander.application.action_execution",
    "agentops_incident_commander.application.action_executor",
    "agentops_incident_commander.application.tool_gateway",
    "agentops_incident_commander.workflows.diagnosis",
    "agentops_incident_commander.workflows.remediation",
    "agentops_incident_commander.workflows.state",
)


def unit_safety_test_command() -> CommandSpec:
    """Build the fixed Phase 12 core-unit coverage gate."""
    coverage_arguments = tuple(f"--cov={target}" for target in UNIT_SAFETY_COVERAGE_TARGETS)
    return CommandSpec(
        "unit-safety-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            "tests/unit",
            "-p",
            "no:cacheprovider",
            "--cov-reset",
            *coverage_arguments,
            "--cov-report=term-missing:skip-covered",
            "--cov-fail-under=100",
        ),
        300,
    )


AGENT_OUTPUT_PROPERTY_TESTS = CommandSpec(
    "agent-output-property-tests",
    (
        "uv",
        "run",
        "--frozen",
        "pytest",
        "tests/property",
        "-p",
        "no:cacheprovider",
        "--no-cov",
    ),
    120,
)

MOCK_EVALUATION_TESTS = CommandSpec(
    "mock-evaluation",
    (
        "uv",
        "run",
        "--frozen",
        "pytest",
        "tests/unit/test_evaluation_harness.py",
        "tests/unit/test_rules_baseline.py",
        "tests/unit/test_single_agent_baseline.py",
        "tests/unit/test_controlled_graph_baseline.py",
        "tests/unit/test_controlled_graph_memory_baseline.py",
        "tests/unit/test_comprehensive_metrics.py",
        "tests/unit/test_evaluation_regression_gate.py",
        "tests/unit/test_bounded_load_evaluation.py",
        "tests/unit/test_ground_truth_isolation.py",
        "tests/unit/test_ground_truth_manifests.py",
        "-p",
        "no:cacheprovider",
        "--no-cov",
    ),
    180,
)

EXTERNAL_INTEGRATION_TESTS = CommandSpec(
    "external-integration-tests",
    (
        "uv",
        "run",
        "--frozen",
        "pytest",
        "tests/integration",
        "-p",
        "no:cacheprovider",
        "--no-cov",
    ),
    300,
)

SIX_SCENARIO_E2E_TESTS = CommandSpec(
    "six-scenario-e2e-tests",
    (
        "uv",
        "run",
        "--frozen",
        "pytest",
        "tests/e2e",
        (
            "tests/integration/test_persistence.py::"
            "test_authorized_rollback_service_full_chain_closes_once_and_replays"
        ),
        "-p",
        "no:cacheprovider",
        "--no-cov",
    ),
    300,
)

RESILIENCE_TEST_CASES = (
    (
        "diagnosis_checkpoint_boundaries",
        (
            "tests/integration/test_graph_checkpoints.py::"
            "test_new_worker_continues_from_every_durable_boundary_without_duplicate_effects"
        ),
    ),
    (
        "diagnosis_committed_effect_boundary",
        (
            "tests/integration/test_graph_checkpoints.py::"
            "test_retried_failed_node_replays_committed_operation_instead_of_effect"
        ),
    ),
    (
        "approval_interrupt_boundary",
        (
            "tests/integration/test_graph_checkpoints.py::"
            "test_new_worker_restores_approval_interrupt_and_reloads_authoritative_record"
        ),
    ),
    (
        "action_claim_commit_boundary",
        (
            "tests/unit/test_action_executor.py::"
            "test_claim_commit_then_worker_exit_replays_without_dispatch"
        ),
    ),
    (
        "action_dispatch_boundary",
        (
            "tests/unit/test_action_executor.py::"
            "test_cancellation_leaves_durable_started_claim_and_retry_only_observes_replay"
        ),
    ),
    (
        "action_terminal_commit_boundary",
        (
            "tests/unit/test_action_executor.py::"
            "test_terminal_commit_then_worker_exit_replays_without_redispatch"
        ),
    ),
    (
        "action_terminal_persist_failure",
        (
            "tests/unit/test_action_executor.py::"
            "test_finish_failure_never_redispatches_after_durable_claim"
        ),
    ),
    (
        "verification_evidence_decision_boundary",
        (
            "tests/integration/test_persistence.py::"
            "test_health_verifier_recovers_after_evidence_commit_before_decision"
        ),
    ),
    (
        "verification_decision_route_boundary",
        (
            "tests/integration/test_persistence.py::"
            "test_successful_health_verification_closes_once_and_replays"
        ),
    ),
    (
        "verification_route_ack_boundary",
        (
            "tests/integration/test_persistence.py::"
            "test_successful_health_verification_closure_serializes_concurrent_replays"
        ),
    ),
    (
        "stale_lease_recovery",
        (
            "tests/integration/test_persistence.py::"
            "test_job_duplicate_id_is_rejected_and_stale_lease_is_reclaimed"
        ),
    ),
    (
        "stale_lease_single_takeover",
        (
            "tests/integration/test_persistence.py::"
            "test_job_stale_lease_has_one_concurrent_recovery_owner"
        ),
    ),
    (
        "stale_final_lease_route",
        ("tests/integration/test_persistence.py::test_job_expired_final_lease_routes_terminally"),
    ),
)


def resilience_test_command() -> CommandSpec:
    """Build the closed Phase 12 worker-crash and stale-lease recovery gate."""
    test_nodes = tuple(dict.fromkeys(node for _, node in RESILIENCE_TEST_CASES))
    return CommandSpec(
        "worker-resilience-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            *test_nodes,
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ),
        240,
    )


CONCURRENCY_TEST_CASES = (
    (
        "control_command_idempotency",
        (
            "tests/integration/test_persistence.py::"
            "test_control_commands_are_atomic_audited_and_idempotent"
        ),
    ),
    (
        "control_command_conflicting_replay",
        (
            "tests/integration/test_persistence.py::"
            "test_control_conflicts_invalid_values_and_incomplete_replay_fail_closed"
        ),
    ),
    (
        "correlation_duplicate_delivery",
        (
            "tests/integration/test_persistence.py::"
            "test_correlation_ledger_serializes_concurrent_exact_replay"
        ),
    ),
    (
        "audit_concurrent_sequence",
        (
            "tests/integration/test_persistence.py::"
            "test_audit_sequence_is_unique_under_concurrent_appends"
        ),
    ),
    (
        "outbox_duplicate_intent",
        ("tests/integration/test_persistence.py::test_outbox_rejects_duplicate_aggregate_intent"),
    ),
    (
        "outbox_concurrent_claim",
        ("tests/integration/test_persistence.py::test_outbox_concurrent_claims_are_disjoint"),
    ),
    (
        "outbox_stale_delivery",
        (
            "tests/integration/test_persistence.py::"
            "test_outbox_reclaims_stale_lease_and_publishes_once"
        ),
    ),
    (
        "job_concurrent_claim",
        (
            "tests/integration/test_persistence.py::"
            "test_job_claims_are_priority_ordered_and_concurrently_disjoint"
        ),
    ),
    (
        "alert_concurrent_ingestion",
        (
            "tests/integration/test_persistence.py::"
            "test_alert_repository_serializes_concurrent_ingestion"
        ),
    ),
    (
        "approval_api_replay",
        (
            "tests/integration/test_persistence.py::"
            "test_approval_center_is_tenant_scoped_verified_and_idempotent"
        ),
    ),
    (
        "approval_same_decision_race",
        (
            "tests/integration/test_persistence.py::"
            "test_concurrent_approval_decisions_have_exactly_one_winner"
        ),
    ),
    (
        "approval_terminal_races",
        (
            "tests/integration/test_persistence.py::"
            "test_concurrent_approval_terminal_races_have_one_winner"
        ),
    ),
    (
        "action_lifecycle_duplicate_claim",
        (
            "tests/integration/test_persistence.py::"
            "test_lifecycle_action_store_serializes_duplicate_claim_transition"
        ),
    ),
    (
        "action_duplicate_dispatch",
        (
            "tests/integration/test_persistence.py::"
            "test_executor_concurrent_duplicate_delivery_dispatches_exactly_once"
        ),
    ),
    (
        "action_conflicting_reuse",
        (
            "tests/integration/test_persistence.py::"
            "test_action_execution_serializes_duplicate_claims_and_rejects_conflicts"
        ),
    ),
    (
        "verification_route_duplicate_delivery",
        (
            "tests/integration/test_persistence.py::"
            "test_successful_health_verification_closure_serializes_concurrent_replays"
        ),
    ),
)


def concurrency_test_command() -> CommandSpec:
    """Build the closed Phase 12 duplicate-delivery and authority-race gate."""
    test_nodes = tuple(dict.fromkeys(node for _, node in CONCURRENCY_TEST_CASES))
    return CommandSpec(
        "concurrency-and-duplicate-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            *test_nodes,
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ),
        240,
    )


FAILURE_MODE_TEST_CASES = (
    (
        "diagnosis_tool_timeout",
        (
            "tests/unit/test_diagnosis_graph.py::"
            "test_parallel_tool_timeout_cancels_peers_and_cannot_persist_partial_evidence"
        ),
    ),
    (
        "diagnosis_model_failure",
        (
            "tests/unit/test_diagnosis_graph.py::"
            "test_model_timeout_refusal_and_malformed_output_stop_downstream_work"
        ),
    ),
    (
        "mock_model_malformed",
        "tests/unit/test_mock_model.py::test_malformed_scenario_fails_strict_schema_validation",
    ),
    (
        "mock_model_timeout",
        "tests/unit/test_mock_model.py::test_timeout_scenario_is_immediate_and_typed",
    ),
    (
        "mock_model_refusal",
        "tests/unit/test_mock_model.py::test_refusal_is_valid_report_but_cannot_become_a_plan",
    ),
    (
        "tool_invalid_input",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_gateway_audits_unknown_disabled_permission_and_invalid_input"
        ),
    ),
    (
        "tool_classified_retry",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_gateway_retries_only_classified_allowed_failures_with_bounded_backoff"
        ),
    ),
    (
        "tool_retry_exhaustion",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_gateway_times_out_exhausts_and_does_not_retry_unclassified_failures"
        ),
    ),
    (
        "tool_invalid_output",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_gateway_rejects_invalid_or_oversized_results_without_retry"
        ),
    ),
    (
        "tool_cancellation_and_audit_outage",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_gateway_audits_cancellation_and_fails_closed_when_audit_is_unavailable"
        ),
    ),
    (
        "action_dispatch_timeout_and_failure",
        "tests/unit/test_action_dispatch.py::test_dispatch_classifies_failure_without_retry",
    ),
    (
        "verification_collection_timeout",
        (
            "tests/unit/test_live_health_verification_collection.py::"
            "test_collection_timeout_cancels_partial_bundle"
        ),
    ),
    (
        "verification_persisted_timeout",
        (
            "tests/unit/test_persisted_health_verification.py::"
            "test_fail_timeout_and_observer_failure_remain_non_authoritative"
        ),
    ),
    (
        "postmortem_malformed_output",
        (
            "tests/unit/test_postmortem.py::"
            "test_false_fact_reference_omission_wrong_section_and_malformed_output_fail_closed"
        ),
    ),
    (
        "postmortem_timeout_and_refusal",
        (
            "tests/unit/test_postmortem.py::"
            "test_timeout_and_refusal_are_traced_with_distinct_terminal_status"
        ),
    ),
    (
        "postgres_pool_creation_outage",
        "tests/unit/test_simulator_dependencies.py::test_postgres_maps_pool_creation_failures",
    ),
    (
        "postgres_operation_timeout",
        "tests/unit/test_simulator_dependencies.py::test_postgres_maps_timeout_and_operation_failure",
    ),
    (
        "postgres_pool_exhaustion",
        (
            "tests/unit/test_simulator_dependencies.py::"
            "test_postgres_pool_exhaustion_is_bounded_observable_and_released"
        ),
    ),
    (
        "redis_client_outage",
        "tests/unit/test_simulator_dependencies.py::test_redis_maps_client_failures_and_logs_error",
    ),
    (
        "redis_operation_timeout",
        "tests/unit/test_simulator_dependencies.py::test_redis_maps_timeout",
    ),
    (
        "redis_forced_timeout",
        (
            "tests/unit/test_simulator_dependencies.py::"
            "test_forced_redis_timeout_is_repeatable_observable_and_side_effect_free"
        ),
    ),
    (
        "simulator_redis_outage_response",
        (
            "tests/unit/test_simulator_services.py::"
            "test_redis_timeout_fault_composes_inventory_store_and_returns_503"
        ),
    ),
    (
        "simulator_dependency_readiness",
        "tests/unit/test_simulator_services.py::test_dependency_unavailability_fails_readiness",
    ),
    (
        "tool_retry_audit_persistence",
        (
            "tests/integration/test_persistence.py::"
            "test_tool_gateway_persists_and_asserts_complete_retried_success_path"
        ),
    ),
)


def failure_mode_test_command() -> CommandSpec:
    """Build the closed Phase 12 timeout, malformed-payload, and outage gate."""
    test_nodes = tuple(dict.fromkeys(node for _, node in FAILURE_MODE_TEST_CASES))
    return CommandSpec(
        "failure-mode-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            *test_nodes,
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ),
        240,
    )


SECURITY_TEST_CASES = (
    (
        "prompt_injection_model_context",
        "tests/unit/test_mock_model.py::test_prompt_injection_context_cannot_change_or_leak_into_output",
    ),
    (
        "prompt_injection_collector_data",
        "tests/unit/test_collectors.py::test_logs_collector_preserves_untrusted_data_and_injection_state",
    ),
    (
        "prompt_injection_quarantine",
        "tests/unit/test_evidence_processing.py::test_normalizer_requires_suspected_injection_to_be_quarantined",
    ),
    (
        "prompt_like_authority_property",
        (
            "tests/property/test_agent_output_properties.py::"
            "test_prompt_like_text_remains_data_and_cannot_create_authority_fields"
        ),
    ),
    (
        "secret_field_redaction",
        "tests/unit/test_redaction.py::test_sensitive_fields_are_replaced_with_secret_free_lineage",
    ),
    (
        "inline_secret_redaction",
        "tests/unit/test_redaction.py::test_inline_secret_patterns_are_redacted_and_paths_are_escaped",
    ),
    (
        "structured_log_secret_redaction",
        "tests/unit/test_structured_logs.py::test_secret_patterns_are_redacted_without_line_breaks",
    ),
    (
        "control_plane_signal_secret_redaction",
        (
            "tests/unit/test_control_plane_observability.py::"
            "test_seeded_secret_never_crosses_control_plane_signal_boundaries"
        ),
    ),
    (
        "simulator_signal_secret_redaction",
        (
            "tests/unit/test_simulator_telemetry.py::"
            "test_seeded_secret_never_crosses_simulator_signal_boundaries"
        ),
    ),
    (
        "evidence_forgery_gate",
        (
            "tests/unit/test_evidence_gate_resolution.py::"
            "test_fabricated_or_altered_evidence_cannot_pass_with_maximum_confidence"
        ),
    ),
    (
        "fabricated_reference_property",
        (
            "tests/property/test_agent_output_properties.py::"
            "test_syntactically_valid_fabricated_references_always_fail_the_evidence_gate"
        ),
    ),
    (
        "evidence_hash_and_size_tamper",
        "tests/unit/test_evidence_processing.py::test_validation_rejects_hash_and_size_tampering",
    ),
    (
        "postmortem_evidence_tamper",
        "tests/unit/test_postmortem.py::test_generation_rejects_tampered_evidence_artifact",
    ),
    (
        "action_terminal_replay",
        "tests/unit/test_action_executor.py::test_terminal_retry_records_replay_without_second_dispatch",
    ),
    (
        "diagnosis_conflicting_replay",
        (
            "tests/unit/test_persistence_repositories.py::"
            "test_diagnosis_repository_rejects_conflicting_replay"
        ),
    ),
    (
        "postgres_control_replay_conflict",
        (
            "tests/integration/test_persistence.py::"
            "test_control_conflicts_invalid_values_and_incomplete_replay_fail_closed"
        ),
    ),
    (
        "gateway_ssrf_path_command_rejection",
        (
            "tests/unit/test_tool_gateway.py::"
            "test_diagnosis_invocation_rejects_nested_urls_paths_commands_and_controls"
        ),
    ),
    (
        "logs_query_target_injection",
        (
            "tests/unit/test_query_logs_tool.py::"
            "test_query_logs_schema_rejects_raw_query_target_and_control_injection"
        ),
    ),
    (
        "deployment_query_target_injection",
        (
            "tests/unit/test_query_deployments_tool.py::"
            "test_query_deployments_schema_rejects_raw_queries_and_targets"
        ),
    ),
    (
        "trace_query_target_injection",
        (
            "tests/unit/test_query_traces_tool.py::"
            "test_query_traces_schema_rejects_raw_queries_and_targets"
        ),
    ),
    (
        "topology_query_target_injection",
        (
            "tests/unit/test_service_topology_tool.py::"
            "test_topology_schema_rejects_raw_queries_and_targets"
        ),
    ),
    (
        "memory_query_target_injection",
        (
            "tests/unit/test_similar_incidents_tool.py::"
            "test_v2_schema_rejects_queries_targets_and_invalid_limits"
        ),
    ),
    (
        "remediation_target_injection",
        (
            "tests/unit/test_remediation_schemas.py::"
            "test_rollback_parameters_reject_model_supplied_targets_and_execution_fields"
        ),
    ),
    (
        "rollback_catalog_injected_lookup",
        "tests/unit/test_rollback_service_tool.py::test_catalog_rejects_untyped_or_injected_lookup",
    ),
    (
        "approval_resume_claim_bypass",
        "tests/unit/test_approval_graph.py::test_pending_approval_reinterrupts_and_never_trusts_resume_claims",
    ),
    (
        "approval_cross_tenant_bypass",
        "tests/unit/test_approval_graph.py::test_cross_tenant_lookup_cannot_resolve_approval",
    ),
    (
        "approval_role_bypass",
        "tests/unit/test_approvals.py::test_requester_and_approver_authorization_fail_closed",
    ),
    (
        "approval_mutation_invalidation",
        "tests/unit/test_remediation_revision.py::test_material_revision_invalidates_and_requires_fresh_approval",
    ),
    (
        "policy_approval_bypass",
        "tests/unit/test_policy_engine.py::test_valid_rollback_requires_approval_and_never_directly_allows_execution",
    ),
    (
        "execution_preflight_rbac_bypass",
        (
            "tests/unit/test_action_execution_preflight.py::"
            "test_preflight_rejects_missing_permission_or_cross_tenant_actor"
        ),
    ),
    (
        "api_write_role_bypass",
        (
            "tests/unit/test_api_contracts.py::"
            "test_write_and_approval_routes_reject_roles_without_permission_before_storage"
        ),
    ),
)


def security_test_command() -> CommandSpec:
    """Build the closed Phase 12 adversarial-security gate."""
    test_nodes = tuple(dict.fromkeys(node for _, node in SECURITY_TEST_CASES))
    return CommandSpec(
        "adversarial-security-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            *test_nodes,
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ),
        300,
    )


WORKFLOW_PATH_TEST_CASES = (
    (
        "diagnosis_success",
        "tests/unit/test_diagnosis_graph.py::test_graph_pass_path_parallelizes_reads_and_returns_only_references",
    ),
    (
        "diagnosis_replan",
        "tests/unit/test_diagnosis_graph.py::test_graph_replans_once_then_passes_with_cumulative_budgets",
    ),
    (
        "diagnosis_refusal",
        "tests/unit/test_diagnosis_graph.py::test_model_timeout_refusal_and_malformed_output_stop_downstream_work",
    ),
    (
        "diagnosis_handoff",
        "tests/unit/test_diagnosis_graph.py::test_graph_handoff_routes_are_terminal_and_recorded",
    ),
    (
        "approval_success",
        "tests/unit/test_approval_graph.py::test_interrupt_contains_only_stable_references_and_reloads_approved_record",
    ),
    (
        "approval_rejected",
        "tests/unit/test_approval_graph.py::test_invalid_or_non_approved_records_route_to_human_without_execution",
    ),
    (
        "approval_expired",
        "tests/unit/test_approval_graph.py::test_invalid_or_non_approved_records_route_to_human_without_execution",
    ),
    (
        "recovery_success",
        "tests/unit/test_recovery_orchestration.py::test_passing_verification_is_the_only_route_to_closed",
    ),
    (
        "verification_rediagnosis",
        "tests/unit/test_recovery_orchestration.py::test_failed_verification_uses_only_non_compensable_route",
    ),
    (
        "verification_handoff",
        "tests/unit/test_recovery_orchestration.py::test_failed_verification_uses_only_non_compensable_route",
    ),
    (
        "safe_boundary_cancellation",
        "tests/unit/test_diagnosis_graph.py::test_cancel_stops_at_each_safe_boundary_before_its_effect",
    ),
    (
        "paused_resume_cancellation",
        "tests/unit/test_diagnosis_graph.py::test_pause_can_resume_as_cancel_without_running_the_node_effect",
    ),
    (
        "failed_verification_noncompensable",
        "tests/unit/test_health_verification_failure_routing.py::test_failure_router_emits_bound_non_compensable_route",
    ),
    (
        "future_compensation_guard",
        "tests/unit/test_architecture.py::test_mvp_compensation_surfaces_are_rejected",
    ),
)


def workflow_path_test_command() -> CommandSpec:
    """Build the closed Phase 12 workflow path gate without duplicate node selection."""
    test_nodes = tuple(dict.fromkeys(node for _, node in WORKFLOW_PATH_TEST_CASES))
    return CommandSpec(
        "workflow-path-tests",
        (
            "uv",
            "run",
            "--frozen",
            "pytest",
            *test_nodes,
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ),
        180,
    )


COMPOSE_PROFILES = (
    "--profile",
    "simulator",
    "--profile",
    "observability",
)
RUNTIME_ENVIRONMENT_KEYS = frozenset(
    {
        "BIND_ADDRESS",
        "GATEWAY_PORT",
        "PROMETHEUS_PORT",
        "LOKI_PORT",
        "TEMPO_PORT",
        "GRAFANA_PORT",
    }
)
DOCKER_DAEMON = CommandSpec(
    "docker-daemon",
    ("docker", "info", "--format", "{{json .ServerVersion}}"),
    15,
)
COMPOSE_DOWN = CommandSpec(
    "runtime-down",
    ("docker", "compose", *COMPOSE_PROFILES, "down", "--remove-orphans", "--timeout", "20"),
    60,
)


def repository_root() -> Path:
    """Return the repository root for the editable or source checkout."""
    return Path(__file__).resolve().parents[2]


def runtime_environment_from_dotenv(root: Path) -> dict[str, str]:
    """Read only non-secret runtime-check settings from the local Compose dotenv file."""
    path = root / ".env"
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise TaskConfigurationError("local .env cannot be read") from error
    if len(content.encode("utf-8")) > 65_536:
        raise TaskConfigurationError("local .env exceeds the size limit")

    selected: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name in RUNTIME_ENVIRONMENT_KEYS:
            if not value or value != value.strip() or value[0] in {'"', "'"}:
                raise TaskConfigurationError(f"local .env has invalid runtime setting: {name}")
            selected[name] = value
    return selected


def build_environment(root: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a deterministic environment that keeps tool caches inside ignored paths."""
    environment = dict(os.environ if source is None else source)
    for name, value in runtime_environment_from_dotenv(root).items():
        environment.setdefault(name, value)
    environment["UV_CACHE_DIR"] = str(root / ".uv-cache")
    environment["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
    environment["PRE_COMMIT_HOME"] = str(root / ".pre-commit-cache")

    managed_python = root / ".python"
    if managed_python.is_dir():
        environment["UV_PYTHON_INSTALL_DIR"] = str(managed_python)
    else:
        environment.pop("UV_PYTHON_INSTALL_DIR", None)

    return environment


def command_specs(
    task: str,
    *,
    write: bool = False,
    suite: str = "unit",
    model: str | None = None,
) -> tuple[CommandSpec, ...]:
    """Resolve one public task into an immutable, allowlisted command sequence."""
    if write and task != "format":
        raise TaskConfigurationError("--write is valid only for the format task")
    if suite != "unit" and task != "test":
        raise TaskConfigurationError("--suite is valid only for the test task")
    if model is not None and task != "eval":
        raise TaskConfigurationError("--model is valid only for the eval task")

    if task == "quality":
        return QUALITY_COMMANDS
    if task == "sync":
        return (CommandSpec("sync", ("uv", "sync", "--frozen", "--all-groups"), 120),)
    if task == "format":
        format_args: tuple[str, ...] = ("uv", "run", "--frozen", "ruff", "format")
        if not write:
            format_args += ("--check",)
        return (CommandSpec("format", (*format_args, "."), 60),)
    if task == "lint":
        return (CommandSpec("lint", ("uv", "run", "--frozen", "ruff", "check", "."), 60),)
    if task == "architecture":
        return (
            CommandSpec(
                "architecture",
                ("uv", "run", "--frozen", "python", "scripts/check_architecture.py"),
                60,
            ),
        )
    if task == "compose":
        return (
            CommandSpec(
                "compose",
                ("uv", "run", "--frozen", "python", "scripts/check_compose.py"),
                60,
            ),
        )
    if task == "typecheck":
        return (
            CommandSpec(
                "types",
                ("uv", "run", "--frozen", "mypy", "src", "scripts", "evaluation", "tests"),
                120,
            ),
        )
    if task == "test":
        if suite == "unit":
            return (unit_safety_test_command(),)
        if suite == "agent-output":
            return (AGENT_OUTPUT_PROPERTY_TESTS,)
        if suite == "workflow":
            return (workflow_path_test_command(),)
        if suite == "integration":
            return (DOCKER_DAEMON, EXTERNAL_INTEGRATION_TESTS)
        if suite == "e2e":
            return (DOCKER_DAEMON, SIX_SCENARIO_E2E_TESTS)
        if suite == "resilience":
            return (DOCKER_DAEMON, resilience_test_command())
        if suite == "concurrency":
            return (DOCKER_DAEMON, concurrency_test_command())
        if suite == "failure":
            return (DOCKER_DAEMON, failure_mode_test_command())
        if suite == "security":
            return (DOCKER_DAEMON, security_test_command())
        if suite == "smoke":
            return (
                CommandSpec(
                    "smoke-tests",
                    ("uv", "run", "--frozen", "pytest", "--no-cov", "tests/smoke"),
                    120,
                ),
            )
        raise TaskConfigurationError(
            "test suite "
            f"'{suite}' is not implemented yet; available suites: "
            "unit, agent-output, workflow, integration, e2e, resilience, concurrency, failure, "
            "security, smoke"
        )
    if task == "docs":
        return (
            CommandSpec(
                "planning-docs",
                ("pwsh", "-NoProfile", "-File", "scripts/check_planning_docs.ps1"),
                60,
            ),
        )
    if task == "build":
        return (CommandSpec("build", ("uv", "build", "--offline", "--no-sources"), 120),)
    if task == "pre-commit":
        return (
            CommandSpec(
                "pre-commit",
                ("uv", "run", "--frozen", "pre-commit", "run", "--all-files"),
                360,
            ),
        )
    if task == "eval":
        if model != "mock":
            raise TaskConfigurationError("eval requires --model mock")
        return (MOCK_EVALUATION_TESTS,)
    if task == "doctor":
        return (
            CommandSpec(
                "compose-contract",
                ("uv", "run", "--frozen", "python", "scripts/check_compose.py"),
                60,
            ),
            CommandSpec(
                "runtime-prerequisites",
                (
                    "uv",
                    "run",
                    "--frozen",
                    "python",
                    "scripts/check_runtime_prerequisites.py",
                ),
                30,
            ),
            DOCKER_DAEMON,
            CommandSpec("compose-version", ("docker", "compose", "version", "--short"), 15),
            CommandSpec(
                "runtime-compose-config",
                ("docker", "compose", *COMPOSE_PROFILES, "config", "--quiet"),
                30,
            ),
        )
    if task == "up":
        return (
            CommandSpec(
                "compose-contract",
                ("uv", "run", "--frozen", "python", "scripts/check_compose.py"),
                60,
            ),
            DOCKER_DAEMON,
            CommandSpec(
                "runtime-up",
                (
                    "docker",
                    "compose",
                    *COMPOSE_PROFILES,
                    "up",
                    "--build",
                    "--detach",
                    "--wait",
                    "--wait-timeout",
                    "120",
                ),
                600,
            ),
            CommandSpec(
                "runtime-health",
                ("uv", "run", "--frozen", "python", "scripts/check_runtime.py"),
                90,
            ),
        )
    if task == "down":
        return (DOCKER_DAEMON, COMPOSE_DOWN)
    if task == "status":
        return (
            DOCKER_DAEMON,
            CommandSpec(
                "runtime-ps",
                ("docker", "compose", *COMPOSE_PROFILES, "ps", "--status", "running"),
                30,
            ),
            CommandSpec(
                "runtime-health",
                ("uv", "run", "--frozen", "python", "scripts/check_runtime.py"),
                90,
            ),
        )
    raise TaskConfigurationError(f"unknown task: {task}")


def run_commands(
    commands: Sequence[CommandSpec],
    *,
    root: Path,
    environment: Mapping[str, str],
) -> int:
    """Run commands sequentially, stopping at the first failure or timeout."""
    for command in commands:
        rendered_command = shlex.join(command.argv)
        print(f"[dev] start task={command.label} command={rendered_command}", flush=True)
        started_at = time.monotonic()
        try:
            result = subprocess.run(
                command.argv,
                cwd=root,
                env=environment,
                check=False,
                timeout=command.timeout_seconds,
            )
        except FileNotFoundError:
            print(
                f"[dev] error task={command.label} reason=executable-not-found "
                f"executable={command.argv[0]}",
                file=sys.stderr,
                flush=True,
            )
            return 127
        except subprocess.TimeoutExpired:
            print(
                f"[dev] error task={command.label} reason=timeout "
                f"timeout_seconds={command.timeout_seconds}",
                file=sys.stderr,
                flush=True,
            )
            return 124

        elapsed_seconds = time.monotonic() - started_at
        if result.returncode != 0:
            print(
                f"[dev] failed task={command.label} exit_code={result.returncode} "
                f"elapsed_seconds={elapsed_seconds:.3f}",
                file=sys.stderr,
                flush=True,
            )
            return result.returncode

        print(
            f"[dev] passed task={command.label} elapsed_seconds={elapsed_seconds:.3f}",
            flush=True,
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        choices=(
            "quality",
            "sync",
            "format",
            "lint",
            "architecture",
            "compose",
            "typecheck",
            "test",
            "docs",
            "build",
            "pre-commit",
            "eval",
            "doctor",
            "up",
            "down",
            "status",
            "fault",
        ),
    )
    parser.add_argument("fault_action", nargs="?", help="Fault action: inject or clean.")
    parser.add_argument("--scenario", help="Allowlisted simulator fault scenario.")
    parser.add_argument("--run-id", help="Validated run identifier for injection or cleanup.")
    parser.add_argument(
        "--model",
        choices=("mock",),
        help="Evaluation model mode; only the deterministic mock is currently allowed.",
    )
    parser.add_argument("--write", action="store_true", help="Apply formatting changes.")
    parser.add_argument(
        "--suite",
        choices=(
            "unit",
            "agent-output",
            "workflow",
            "integration",
            "smoke",
            "e2e",
            "resilience",
            "concurrency",
            "failure",
            "security",
        ),
        default="unit",
        help=(
            "Test suite to run; integration requires Docker, smoke is in-process, "
            "e2e includes the six-scenario product matrix, and resilience exercises "
            "worker-crash and stale-lease boundaries. Concurrency exercises duplicate delivery "
            "and Approval races. Failure exercises timeout, retry, malformed-payload, and outage "
            "boundaries. Security exercises injection, redaction, forgery, replay, Approval, and "
            "RBAC boundaries."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one allowlisted developer task."""
    arguments = build_parser().parse_args(argv)
    root = repository_root()
    try:
        environment = build_environment(root)
    except TaskConfigurationError as error:
        print(f"[dev] configuration-error reason={error}", file=sys.stderr, flush=True)
        return 2
    if arguments.task == "fault":
        if arguments.write or arguments.suite != "unit" or arguments.model is not None:
            print(
                "[dev] configuration-error reason=fault accepts only action, --scenario, and "
                "--run-id",
                file=sys.stderr,
                flush=True,
            )
            return 2
        from agentops_incident_commander import faults

        return faults.main(
            arguments.fault_action or "",
            scenario=arguments.scenario,
            run_id=arguments.run_id,
            root=root,
            environment=environment,
        )
    if (
        arguments.fault_action is not None
        or arguments.scenario is not None
        or arguments.run_id is not None
    ):
        print(
            "[dev] configuration-error reason=fault options require the fault task",
            file=sys.stderr,
            flush=True,
        )
        return 2
    try:
        commands = command_specs(
            arguments.task,
            write=arguments.write,
            suite=arguments.suite,
            model=arguments.model,
        )
    except TaskConfigurationError as error:
        print(f"[dev] configuration-error reason={error}", file=sys.stderr, flush=True)
        return 2

    if arguments.task != "up":
        return run_commands(commands, root=root, environment=environment)

    preflight_result = run_commands(commands[:2], root=root, environment=environment)
    if preflight_result != 0:
        return preflight_result
    launch_result = run_commands(commands[2:], root=root, environment=environment)
    if launch_result == 0:
        return 0
    cleanup_result = run_commands((COMPOSE_DOWN,), root=root, environment=environment)
    if cleanup_result != 0:
        print(
            f"[dev] warning task=runtime-cleanup exit_code={cleanup_result}",
            file=sys.stderr,
            flush=True,
        )
    return launch_result

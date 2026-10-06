"""Strict rollback_service contract and server-owned target resolution tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from agentops_incident_commander.application.tool_gateway import (
    ToolPayloadValidationError,
    _validate_payload,
)
from agentops_incident_commander.domain import (
    ROLLBACK_SERVICE_SCHEMA_VERSION,
    ApprovalId,
    IdempotencyKey,
    IncidentId,
    InvalidDomainValueError,
    ManagedServiceTarget,
    OpaqueIdentifier,
    Permission,
    PolicyEnvironment,
    ResolvedRollbackTarget,
    RollbackServiceRequest,
    RollbackTargetCatalog,
    SemanticVersion,
    TenantId,
    ToolAccessClass,
    ToolIdempotency,
    ToolRisk,
)
from agentops_incident_commander.infrastructure import (
    ROLLBACK_SERVICE_VERSION,
    rollback_service_definition,
)


def request_arguments(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "approval_id": "approval-1",
        "idempotency_key": "rollback-request-1",
        "incident_id": "incident-1",
        "schema_version": "1.0.0",
    }
    value.update(overrides)
    return value


def target(**overrides: Any) -> ManagedServiceTarget:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "target_reference": OpaqueIdentifier("simulator-orders"),
        "allowed_versions": (SemanticVersion("1.0.0"), SemanticVersion("2.0.0")),
        "stable_version": SemanticVersion("1.0.0"),
    }
    values.update(overrides)
    return ManagedServiceTarget(**values)


def test_rollback_service_definition_is_versioned_write_only_and_idempotent() -> None:
    definition = rollback_service_definition()
    input_schema = definition.input_schema.as_dict()
    output_schema = definition.output_schema.as_dict()

    assert SemanticVersion("1.0.0") == ROLLBACK_SERVICE_VERSION
    assert definition.name == "rollback_service"
    assert definition.semantic_version == ROLLBACK_SERVICE_VERSION
    assert definition.access_class is ToolAccessClass.WRITE
    assert definition.risk is ToolRisk.HIGH
    assert definition.required_permission is Permission.APPROVED_ACTION_EXECUTE
    assert definition.idempotency is ToolIdempotency.REQUIRED_RESULT_REPLAY
    assert definition.retry_policy.max_attempts == 1
    assert definition.audit.event_type == "recovery.rollback_service"
    assert set(input_schema["required"]) == {
        "approval_id",
        "idempotency_key",
        "incident_id",
        "schema_version",
    }
    assert set(input_schema["properties"]) == set(input_schema["required"])
    assert input_schema["additionalProperties"] is False
    assert not {"command", "service", "target", "target_version", "url"} & set(
        input_schema["properties"]
    )
    assert output_schema["additionalProperties"] is False
    assert output_schema["properties"]["schema_version"]["const"] == "1.0.0"


def test_rollback_request_round_trips_exact_versioned_identifiers() -> None:
    value = RollbackServiceRequest.from_mapping(
        request_arguments(), expected_incident_id=IncidentId("incident-1")
    )
    assert value == RollbackServiceRequest(
        IncidentId("incident-1"),
        ApprovalId("approval-1"),
        IdempotencyKey("rollback-request-1"),
    )
    assert value.schema_version == ROLLBACK_SERVICE_SCHEMA_VERSION
    assert value.as_arguments() == request_arguments()
    with pytest.raises(FrozenInstanceError):
        value.schema_version = "2.0.0"  # type: ignore[misc]


@pytest.mark.parametrize(
    "payload",
    [
        request_arguments(command="kubectl rollout undo deployment/orders"),
        request_arguments(service="orders"),
        request_arguments(target="cluster-a"),
        request_arguments(target_version="1.0.0"),
        request_arguments(url="https://orchestrator.example/rollback"),
        request_arguments(incident_id="../incident-1"),
        request_arguments(approval_id=""),
        request_arguments(idempotency_key="bad key"),
        request_arguments(schema_version="2.0.0"),
    ],
)
def test_rollback_schema_rejects_free_form_or_malformed_caller_inputs(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ToolPayloadValidationError):
        _validate_payload(rollback_service_definition().input_schema.as_dict(), payload)


@pytest.mark.parametrize(
    "value",
    [
        [],
        {"incident_id": "incident-1"},
        request_arguments(command="whoami"),
    ],
)
def test_typed_rollback_request_rejects_missing_or_extra_fields(value: Any) -> None:
    with pytest.raises(InvalidDomainValueError, match="fields are invalid"):
        RollbackServiceRequest.from_mapping(value, expected_incident_id=IncidentId("incident-1"))


def test_typed_rollback_request_rejects_non_string_and_wrong_typed_values() -> None:
    with pytest.raises(InvalidDomainValueError, match="must be strings"):
        RollbackServiceRequest.from_mapping(
            request_arguments(approval_id=1),
            expected_incident_id=IncidentId("incident-1"),
        )
    constructors: tuple[tuple[dict[str, Any], str], ...] = (
        ({"incident_id": OpaqueIdentifier("incident-1")}, "Incident ID"),
        ({"approval_id": OpaqueIdentifier("approval-1")}, "Approval ID"),
        ({"idempotency_key": OpaqueIdentifier("key-1")}, "idempotency key"),
        ({"schema_version": "2.0.0"}, "schema version"),
    )
    for overrides, message in constructors:
        values: dict[str, Any] = {
            "incident_id": IncidentId("incident-1"),
            "approval_id": ApprovalId("approval-1"),
            "idempotency_key": IdempotencyKey("key-1"),
        }
        values.update(overrides)
        with pytest.raises(InvalidDomainValueError, match=message):
            RollbackServiceRequest(**values)


def test_typed_rollback_request_rejects_cross_incident_or_untyped_scope() -> None:
    with pytest.raises(InvalidDomainValueError, match="expected rollback Incident"):
        RollbackServiceRequest.from_mapping(
            request_arguments(),
            expected_incident_id="incident-1",  # type: ignore[arg-type]
        )
    with pytest.raises(InvalidDomainValueError, match="does not match call scope"):
        RollbackServiceRequest.from_mapping(
            request_arguments(incident_id="incident-other"),
            expected_incident_id=IncidentId("incident-1"),
        )


def test_server_owned_catalog_resolves_exact_stable_version() -> None:
    configured = target()
    catalog = RollbackTargetCatalog((configured,))
    resolved = catalog.resolve(
        tenant_id=TenantId("tenant-1"),
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        current_version=SemanticVersion("2.0.0"),
    )
    assert resolved == ResolvedRollbackTarget(
        tenant_id=TenantId("tenant-1"),
        service="orders",
        environment=PolicyEnvironment.PRODUCTION,
        target_reference=OpaqueIdentifier("simulator-orders"),
        expected_current_version=SemanticVersion("2.0.0"),
        stable_version=SemanticVersion("1.0.0"),
    )
    assert configured.scope == (
        TenantId("tenant-1"),
        "orders",
        PolicyEnvironment.PRODUCTION,
    )


def test_resolved_target_rejects_untyped_or_noop_state() -> None:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "target_reference": OpaqueIdentifier("simulator-orders"),
        "expected_current_version": SemanticVersion("2.0.0"),
        "stable_version": SemanticVersion("1.0.0"),
    }
    for name, invalid in (
        ("tenant_id", "tenant-1"),
        ("service", "orders; whoami"),
        ("environment", "PRODUCTION"),
        ("target_reference", "simulator-orders"),
        ("expected_current_version", "2.0.0"),
        ("stable_version", "1.0.0"),
    ):
        invalid_values = values | {name: invalid}
        with pytest.raises(InvalidDomainValueError, match="target is invalid"):
            ResolvedRollbackTarget(**invalid_values)
    with pytest.raises(InvalidDomainValueError, match="must change version"):
        ResolvedRollbackTarget(**(values | {"expected_current_version": SemanticVersion("1.0.0")}))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"tenant_id": "tenant-1"}, "tenant"),
        ({"service": "Orders; shutdown"}, "service"),
        ({"environment": "PRODUCTION"}, "environment"),
        ({"target_reference": "simulator-orders"}, "target reference"),
        ({"allowed_versions": []}, "versions"),
        ({"allowed_versions": ()}, "versions"),
        ({"allowed_versions": ("1.0.0",)}, "versions"),
        (
            {
                "allowed_versions": (
                    SemanticVersion("1.0.0"),
                    SemanticVersion("1.0.0"),
                )
            },
            "versions",
        ),
        ({"stable_version": "1.0.0"}, "stable version"),
        (
            {
                "allowed_versions": (
                    SemanticVersion("2.0.0"),
                    SemanticVersion("1.0.0"),
                )
            },
            "must be ordered",
        ),
        ({"stable_version": SemanticVersion("3.0.0")}, "must be allowlisted"),
    ],
)
def test_managed_target_rejects_invalid_configuration(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(InvalidDomainValueError, match=message):
        target(**overrides)


def test_catalog_rejects_invalid_or_duplicate_entries() -> None:
    with pytest.raises(InvalidDomainValueError, match="cannot be empty"):
        RollbackTargetCatalog(())
    with pytest.raises(InvalidDomainValueError, match="cannot be empty"):
        RollbackTargetCatalog([])  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="entries are invalid"):
        RollbackTargetCatalog(("orders",))  # type: ignore[arg-type]
    with pytest.raises(InvalidDomainValueError, match="duplicate scope"):
        RollbackTargetCatalog((target(), target(target_reference=OpaqueIdentifier("duplicate"))))


@pytest.mark.parametrize(
    "lookup",
    [
        {"tenant_id": "tenant-1"},
        {"service": "orders; whoami"},
        {"environment": "PRODUCTION"},
        {"current_version": "2.0.0"},
    ],
)
def test_catalog_rejects_untyped_or_injected_lookup(lookup: dict[str, Any]) -> None:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "current_version": SemanticVersion("2.0.0"),
    }
    values.update(lookup)
    with pytest.raises(InvalidDomainValueError, match="lookup is invalid"):
        RollbackTargetCatalog((target(),)).resolve(**values)


@pytest.mark.parametrize(
    ("lookup", "message"),
    [
        ({"tenant_id": TenantId("tenant-other")}, "not server-allowlisted"),
        ({"service": "payments"}, "not server-allowlisted"),
        ({"environment": PolicyEnvironment.STAGING}, "not server-allowlisted"),
        (
            {"current_version": SemanticVersion("3.0.0")},
            "current service version is not server-allowlisted",
        ),
        ({"current_version": SemanticVersion("1.0.0")}, "already at the stable version"),
    ],
)
def test_catalog_fails_closed_for_unknown_scope_version_or_noop(
    lookup: dict[str, Any], message: str
) -> None:
    values: dict[str, Any] = {
        "tenant_id": TenantId("tenant-1"),
        "service": "orders",
        "environment": PolicyEnvironment.PRODUCTION,
        "current_version": SemanticVersion("2.0.0"),
    }
    values.update(lookup)
    with pytest.raises(InvalidDomainValueError, match=message):
        RollbackTargetCatalog((target(),)).resolve(**values)

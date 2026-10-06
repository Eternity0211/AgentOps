"""Versioned Tool Gateway contract for the bounded rollback_service action."""

from __future__ import annotations

from agentops_incident_commander.domain import (
    Permission,
    RetryableToolError,
    SemanticVersion,
    ToolAccessClass,
    ToolAuditPolicy,
    ToolDefinition,
    ToolIdempotency,
    ToolRetryPolicy,
    ToolRisk,
    ToolSchema,
)

ROLLBACK_SERVICE_VERSION = SemanticVersion("1.0.0")


def rollback_service_definition() -> ToolDefinition:
    """Return the immutable write contract without registering a mutation adapter."""

    input_schema = ToolSchema.from_mapping(
        ROLLBACK_SERVICE_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "approval_id": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "type": "string",
                },
                "idempotency_key": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "type": "string",
                },
                "incident_id": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
            },
            "required": [
                "approval_id",
                "idempotency_key",
                "incident_id",
                "schema_version",
            ],
            "type": "object",
        },
    )
    output_schema = ToolSchema.from_mapping(
        ROLLBACK_SERVICE_VERSION,
        {
            "additionalProperties": False,
            "properties": {
                "deployed_version": {
                    "maxLength": 64,
                    "minLength": 1,
                    "pattern": "(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)",
                    "type": "string",
                },
                "operation_reference": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[A-Za-z0-9][A-Za-z0-9._:-]{0,127}",
                    "type": "string",
                },
                "schema_version": {"const": "1.0.0", "type": "string"},
                "service": {
                    "maxLength": 128,
                    "minLength": 1,
                    "pattern": "[a-z][a-z0-9-]{0,127}",
                    "type": "string",
                },
            },
            "required": [
                "deployed_version",
                "operation_reference",
                "schema_version",
                "service",
            ],
            "type": "object",
        },
    )
    return ToolDefinition(
        name="rollback_service",
        semantic_version=ROLLBACK_SERVICE_VERSION,
        input_schema=input_schema,
        output_schema=output_schema,
        access_class=ToolAccessClass.WRITE,
        risk=ToolRisk.HIGH,
        required_permission=Permission.APPROVED_ACTION_EXECUTE,
        timeout_ms=30_000,
        retry_policy=ToolRetryPolicy(
            max_attempts=1,
            initial_backoff_ms=0,
            max_backoff_ms=0,
            retryable_errors=frozenset[RetryableToolError](),
        ),
        idempotency=ToolIdempotency.REQUIRED_RESULT_REPLAY,
        audit=ToolAuditPolicy("recovery.rollback_service", ROLLBACK_SERVICE_VERSION),
        max_input_bytes=1_024,
        max_result_bytes=2_048,
    )

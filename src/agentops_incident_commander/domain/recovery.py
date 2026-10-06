"""Typed rollback request and server-owned service release allowlist."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from .errors import InvalidDomainValueError
from .policy import PolicyEnvironment
from .tools import SemanticVersion
from .values import ApprovalId, IncidentId, OpaqueIdentifier, TenantId

ROLLBACK_SERVICE_SCHEMA_VERSION = "1.0.0"
_SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,127}$")


@dataclass(frozen=True, slots=True)
class IdempotencyKey(OpaqueIdentifier):
    """Caller key that scopes durable recovery-result replay."""


@dataclass(frozen=True, slots=True)
class RollbackServiceRequest:
    """The complete caller-controlled rollback payload; targets remain absent."""

    incident_id: IncidentId
    approval_id: ApprovalId
    idempotency_key: IdempotencyKey
    schema_version: str = ROLLBACK_SERVICE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.incident_id, IncidentId):
            raise InvalidDomainValueError("rollback request Incident ID is invalid")
        if not isinstance(self.approval_id, ApprovalId):
            raise InvalidDomainValueError("rollback request Approval ID is invalid")
        if not isinstance(self.idempotency_key, IdempotencyKey):
            raise InvalidDomainValueError("rollback request idempotency key is invalid")
        if self.schema_version != ROLLBACK_SERVICE_SCHEMA_VERSION:
            raise InvalidDomainValueError("rollback request schema version is unsupported")

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        expected_incident_id: IncidentId,
    ) -> RollbackServiceRequest:
        if not isinstance(expected_incident_id, IncidentId):
            raise InvalidDomainValueError("expected rollback Incident ID is invalid")
        expected = {"approval_id", "idempotency_key", "incident_id", "schema_version"}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise InvalidDomainValueError("rollback request fields are invalid")
        if any(not isinstance(value[name], str) for name in expected):
            raise InvalidDomainValueError("rollback request values must be strings")
        request = cls(
            incident_id=IncidentId(value["incident_id"]),
            approval_id=ApprovalId(value["approval_id"]),
            idempotency_key=IdempotencyKey(value["idempotency_key"]),
            schema_version=value["schema_version"],
        )
        if request.incident_id != expected_incident_id:
            raise InvalidDomainValueError("rollback request Incident does not match call scope")
        return request

    def as_arguments(self) -> dict[str, str]:
        return {
            "approval_id": self.approval_id.value,
            "idempotency_key": self.idempotency_key.value,
            "incident_id": self.incident_id.value,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ManagedServiceTarget:
    """Deployment-owned allowlist entry; never accepted from an LLM or API caller."""

    tenant_id: TenantId
    service: str
    environment: PolicyEnvironment
    target_reference: OpaqueIdentifier
    allowed_versions: tuple[SemanticVersion, ...]
    stable_version: SemanticVersion

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_id, TenantId):
            raise InvalidDomainValueError("managed rollback tenant is invalid")
        if not isinstance(self.service, str) or _SERVICE.fullmatch(self.service) is None:
            raise InvalidDomainValueError("managed rollback service is invalid")
        if not isinstance(self.environment, PolicyEnvironment):
            raise InvalidDomainValueError("managed rollback environment is invalid")
        if not isinstance(self.target_reference, OpaqueIdentifier):
            raise InvalidDomainValueError("managed rollback target reference is invalid")
        if (
            not isinstance(self.allowed_versions, tuple)
            or not self.allowed_versions
            or any(not isinstance(version, SemanticVersion) for version in self.allowed_versions)
            or len(set(self.allowed_versions)) != len(self.allowed_versions)
        ):
            raise InvalidDomainValueError("managed rollback versions are invalid")
        if not isinstance(self.stable_version, SemanticVersion):
            raise InvalidDomainValueError("managed rollback stable version is invalid")
        ordered = tuple(sorted(self.allowed_versions))
        if self.allowed_versions != ordered:
            raise InvalidDomainValueError("managed rollback versions must be ordered")
        if self.stable_version not in self.allowed_versions:
            raise InvalidDomainValueError("stable rollback version must be allowlisted")

    @property
    def scope(self) -> tuple[TenantId, str, PolicyEnvironment]:
        return (self.tenant_id, self.service, self.environment)


@dataclass(frozen=True, slots=True)
class ResolvedRollbackTarget:
    tenant_id: TenantId
    service: str
    environment: PolicyEnvironment
    target_reference: OpaqueIdentifier
    expected_current_version: SemanticVersion
    stable_version: SemanticVersion

    def __post_init__(self) -> None:
        if (
            not isinstance(self.tenant_id, TenantId)
            or not isinstance(self.service, str)
            or _SERVICE.fullmatch(self.service) is None
            or not isinstance(self.environment, PolicyEnvironment)
            or not isinstance(self.target_reference, OpaqueIdentifier)
            or not isinstance(self.expected_current_version, SemanticVersion)
            or not isinstance(self.stable_version, SemanticVersion)
        ):
            raise InvalidDomainValueError("resolved rollback target is invalid")
        if self.expected_current_version == self.stable_version:
            raise InvalidDomainValueError("resolved rollback target must change version")


class RollbackTargetCatalog:
    """Resolve an exact rollback target from immutable deployment configuration."""

    def __init__(self, targets: tuple[ManagedServiceTarget, ...]) -> None:
        if not isinstance(targets, tuple) or not targets:
            raise InvalidDomainValueError("rollback target catalog cannot be empty")
        by_scope: dict[tuple[TenantId, str, PolicyEnvironment], ManagedServiceTarget] = {}
        for target in targets:
            if not isinstance(target, ManagedServiceTarget):
                raise InvalidDomainValueError("rollback target catalog entries are invalid")
            if target.scope in by_scope:
                raise InvalidDomainValueError("rollback target catalog contains duplicate scope")
            by_scope[target.scope] = target
        self._targets = MappingProxyType(by_scope)

    def resolve(
        self,
        *,
        tenant_id: TenantId,
        service: str,
        environment: PolicyEnvironment,
        current_version: SemanticVersion,
    ) -> ResolvedRollbackTarget:
        if (
            not isinstance(tenant_id, TenantId)
            or not isinstance(service, str)
            or _SERVICE.fullmatch(service) is None
            or not isinstance(environment, PolicyEnvironment)
            or not isinstance(current_version, SemanticVersion)
        ):
            raise InvalidDomainValueError("rollback target lookup is invalid")
        target = self._targets.get((tenant_id, service, environment))
        if target is None:
            raise InvalidDomainValueError("rollback target is not server-allowlisted")
        if current_version not in target.allowed_versions:
            raise InvalidDomainValueError("current service version is not server-allowlisted")
        if current_version == target.stable_version:
            raise InvalidDomainValueError("service is already at the stable version")
        return ResolvedRollbackTarget(
            tenant_id=target.tenant_id,
            service=target.service,
            environment=target.environment,
            target_reference=target.target_reference,
            expected_current_version=current_version,
            stable_version=target.stable_version,
        )

"""Deterministic rollback reference-role checks over hash-bound Gate snapshots."""

from typing import Any

from agentops_incident_commander.workflows import RemediationProposal


def rollback_roles(snapshot: dict[str, Any]) -> dict[str, str]:
    evidence = snapshot.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("rollback Gate evidence snapshot missing")
    roles: dict[str, str] = {}
    for item in evidence:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not isinstance(item.get("source_type"), str)
        ):
            raise ValueError("rollback Gate evidence role malformed")
        if item["id"] in roles:
            raise ValueError("rollback Gate evidence identity duplicated")
        roles[item["id"]] = item["source_type"]
    return roles


def validate_rollback_roles(proposal: RemediationProposal, roles: dict[str, str]) -> None:
    introducing = proposal.parameters.introducing_deployment_evidence_id
    current = proposal.prerequisites.current_version_evidence_id
    if roles.get(introducing) != "DEPLOYMENT":
        raise ValueError("ROLLBACK_INTRODUCING_REFERENCE_NOT_DEPLOYMENT")
    if current == introducing or roles.get(current) not in {"METRIC", "DEPLOYMENT"}:
        raise ValueError("ROLLBACK_CURRENT_VERSION_REFERENCE_ROLE_INVALID")

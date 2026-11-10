"""Read-only simulated review of exported registered approval records."""

from datetime import datetime
from typing import Any

from agentops_incident_commander.application.approvals import (
    approval_review_snapshot_from_document,
)
from evaluation.rollback_roles import validate_rollback_roles


def review(rows: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    for approval in rows["approvals"]:
        snapshots = [
            row for row in rows["approval_review_snapshots"] if row["approval_id"] == approval["id"]
        ]
        violations = []
        try:
            if len(snapshots) != 1:
                raise ValueError("SNAPSHOT_CARDINALITY")
            row = snapshots[0]
            snapshot = approval_review_snapshot_from_document(row["snapshot"])
            if not (
                approval["status"] == "PENDING"
                and approval["decided_at"] is None
                and approval["decided_by"] is None
                and datetime.fromisoformat(approval["requested_at"])
                <= datetime.fromisoformat(row["created_at"])
                < datetime.fromisoformat(approval["expires_at"])
                and row["tenant_id"]
                == approval["tenant_id"]
                == snapshot.policy_input.tenant_id.value
                and row["incident_id"]
                == approval["incident_id"]
                == snapshot.policy_input.incident_id.value
                and row["schema_version"] == snapshot.schema_version
                and row["snapshot_fingerprint"] == snapshot.fingerprint.value
                and approval["proposal_fingerprint"] == snapshot.proposal.fingerprint.value
                and approval["policy_input_fingerprint"] == snapshot.policy_input.fingerprint.value
                and approval["policy_decision_fingerprint"]
                == snapshot.policy_decision.fingerprint.value
            ):
                raise ValueError("PENDING_BINDING")
        except (ValueError, KeyError, TypeError):
            violations.append("PENDING_BINDING_INVALID")
        else:
            roles = {
                evidence["id"]: evidence["source_type"]
                for evidence in rows["evidence"]
                if evidence["tenant_id"] == approval["tenant_id"]
                and evidence["incident_id"] == approval["incident_id"]
            }
            try:
                validate_rollback_roles(snapshot.proposal, roles)
            except ValueError as error:
                violations.append(str(error))
        results.append(
            {
                "actor_kind": "DETERMINISTIC_EVALUATOR_NOT_HUMAN",
                "approval_id": approval["id"],
                "pending_binding_verified": "PENDING_BINDING_INVALID" not in violations,
                "recommendation": "REJECT" if violations else "ELIGIBLE_FOR_HUMAN_REVIEW",
                "violations": violations,
                "approval_decided": False,
                "recovery_executed": False,
                "human_time_saved": None,
            }
        )
    return results

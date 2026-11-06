"""Captured adverse proposal is refused without modifying its original record."""

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation.rollback_roles import rollback_roles, validate_rollback_roles

from agentops_incident_commander.workflows import RemediationProposal


def test_real_captured_log_reference_is_not_deployment() -> None:
    rows = json.loads(
        Path("evaluation/results/registered-live/v2/run-001/sql-records.json").read_text(
            encoding="utf-8"
        )
    )
    proposal = RemediationProposal.model_validate_json(
        json.dumps(rows["approval_review_snapshots"][0]["snapshot"]["proposal"])
    )
    roles = rollback_roles(rows["evidence_gate_decisions"][0]["input_snapshot"])
    with pytest.raises(ValueError, match="NOT_DEPLOYMENT"):
        validate_rollback_roles(proposal, roles)
    valid = dict(roles)
    valid[proposal.parameters.introducing_deployment_evidence_id] = "DEPLOYMENT"
    validate_rollback_roles(proposal, valid)
    valid[proposal.prerequisites.current_version_evidence_id] = "LOG"
    with pytest.raises(ValueError, match="CURRENT_VERSION"):
        validate_rollback_roles(proposal, valid)


@pytest.mark.parametrize(
    "snapshot", [{}, {"evidence": [None]}, {"evidence": [{"id": "x", "source_type": "LOG"}] * 2}]
)
def test_malformed_or_duplicate_roles_refuse(snapshot: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        rollback_roles(snapshot)

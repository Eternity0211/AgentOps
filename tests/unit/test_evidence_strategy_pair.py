from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from evaluation.autonomous_diagnosis import EvidenceStrategy
from evaluation.run_evidence_strategy_pair import BOUND_SOURCES, _arms, check_plan
from evaluation.structured_model import StructuredTransportProfile

DATASET = Path("evaluation/datasets/evidence-strategy-development-v1")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan() -> dict[str, object]:
    revision = subprocess.check_output(
        ["git", "-c", "safe.directory=D:/AgentOps", "rev-parse", "HEAD"], text=True
    ).strip()
    return {
        "schema_version": "evidence-strategy-pair/1.0.0",
        "implementation_commit": revision,
        "dataset_index_sha256": _sha256(DATASET / "index.json"),
        "modes": ["controlled-graph"],
        "model_provider_call_ceiling": 6,
        "arms": {
            "baseline-legacy": {
                "transport_profile": StructuredTransportProfile.CANDIDATE_1_11.value,
                "evidence_strategy": EvidenceStrategy.LEGACY.value,
            },
            "candidate-causal-scope": {
                "transport_profile": StructuredTransportProfile.CANDIDATE_1_11.value,
                "evidence_strategy": EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE.value,
            },
        },
        "source_hashes": {name: _sha256(Path(name)) for name in sorted(BOUND_SOURCES)},
    }


def test_evidence_strategy_pair_holds_transport_and_budgets_constant() -> None:
    plan = _plan()
    revision = str(plan["implementation_commit"])
    assert check_plan(plan, revision, DATASET) == (
        (
            "baseline-legacy",
            StructuredTransportProfile.CANDIDATE_1_11,
            EvidenceStrategy.LEGACY,
        ),
        (
            "candidate-causal-scope",
            StructuredTransportProfile.CANDIDATE_1_11,
            EvidenceStrategy.GC_AWARE_CAUSAL_SCOPE,
        ),
    )


def test_evidence_strategy_pair_rejects_changed_profile_or_source() -> None:
    plan = _plan()
    changed = json.loads(json.dumps(plan))
    changed["arms"]["candidate-causal-scope"]["transport_profile"] = (
        StructuredTransportProfile.CANDIDATE_1_10.value
    )
    with pytest.raises(ValueError, match="held constant"):
        _arms(changed)

    changed = json.loads(json.dumps(plan))
    changed["source_hashes"]["evaluation/autonomous_diagnosis.py"] = "0" * 64
    with pytest.raises(ValueError, match="source hash"):
        check_plan(changed, str(plan["implementation_commit"]), DATASET)

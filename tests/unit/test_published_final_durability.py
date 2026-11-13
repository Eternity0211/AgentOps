from __future__ import annotations

import hashlib
from pathlib import Path

from evaluation.contracts import load_json_object
from evaluation.final_durability import load_observations, load_plan, render_markdown, score

ROOT = Path("evaluation/results/final-durability/v1")
PLAN = Path("evaluation/durability/v2/plan.json")


def test_published_final_durability_recomputes_and_binds_raw_observations() -> None:
    plan = load_plan(PLAN)
    raw = ROOT / "raw-run-001" / "observations.json"
    result_path = ROOT / "run-001" / "result.json"
    metadata = load_json_object(ROOT / "metadata.json")
    result = load_json_object(result_path)

    assert score(plan, load_observations(raw, plan)) == result
    assert render_markdown(result) == (ROOT / "run-001" / "README.md").read_text(
        encoding="utf-8"
    )
    assert metadata["plan_sha256"] == plan.fingerprint == result["plan_sha256"]
    assert metadata["observations_sha256"] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert result["summary"]["accepted"] is True
    assert result["summary"]["completed_pairs"] == 8
    assert result["summary"]["duplicate_external_effects"] == 0
    assert result["summary"]["ambiguous_result_redispatches"] == 0
    assert result["summary"]["lost_evidence_records_on_resumable_routes"] == 0


def test_published_final_durability_manifest_and_revision_are_exact() -> None:
    metadata = load_json_object(ROOT / "metadata.json")
    manifest = load_json_object(ROOT / "run-001" / "manifest.json")

    assert metadata["code_revision"] == "cc8b5ea040ec6cf211a1ae106d8f365a9db3d909"
    assert metadata["probe_sha256"] == hashlib.sha256(
        Path("evaluation/run_final_durability_probe.py").read_bytes()
    ).hexdigest()
    for name, digest in manifest.items():
        assert hashlib.sha256((ROOT / "run-001" / name).read_bytes()).hexdigest() == digest

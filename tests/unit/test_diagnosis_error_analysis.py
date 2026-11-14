from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.diagnosis_error_analysis import DEFAULT_LABELS, DEFAULT_RUN, analyze, main, render


def test_frozen_error_census_identifies_evidence_not_ranking_defects() -> None:
    report = analyze(DEFAULT_LABELS, DEFAULT_RUN)

    assert report["census"] == {
        "fault_outcomes": 54,
        "top1_correct": 36,
        "top1_errors": 18,
        "top1_rate": 2 / 3,
    }
    assert report["category_counts"] == {
        "DOWNSTREAM_CAUSAL_SCOPE_NOT_EXPANDED": 9,
        "EVIDENCE_CONSTRUCTION_GAP": 9,
    }
    assert report["expected_cause_counts"] == {"bad-configuration": 9, "memory-leak": 9}
    assert all(error["retrieved_services"] == ["gateway"] for error in report["errors"])
    assert {error["predicted"] for error in report["errors"]} == {None, "http-500"}


def test_error_analysis_binds_sources_and_avoids_model_content() -> None:
    report = analyze(DEFAULT_LABELS, DEFAULT_RUN)
    source = report["source"]
    assert source["labels_sha256"] == hashlib.sha256(DEFAULT_LABELS.read_bytes()).hexdigest()
    assert source["outcome_count"] == 81
    for error in report["errors"]:
        assert set(error) == {
            "instance_id",
            "mode",
            "expected",
            "predicted",
            "disposition",
            "missing_evidence_count",
            "retrieved_services",
            "category",
            "reason",
        }
    rendered = render(report)
    assert "36" in rendered
    assert "EVIDENCE_CONSTRUCTION_GAP" in rendered
    assert "DOWNSTREAM_CAUSAL_SCOPE_NOT_EXPANDED" in rendered


def test_published_error_analysis_is_reproducible() -> None:
    published = json.loads(
        Path("evaluation/results/diagnosis-error-analysis/v1/analysis.json").read_text(
            encoding="utf-8"
        )
    )
    assert published == analyze(DEFAULT_LABELS, DEFAULT_RUN)
    assert Path("evaluation/results/diagnosis-error-analysis/v1/README.md").read_text(
        encoding="utf-8"
    ) == render(published)


def test_cli_refuses_overwrite(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("sys.argv", ["diagnosis-error-analysis", "--output", str(tmp_path)])
    with pytest.raises(ValueError, match="already exists"):
        main()

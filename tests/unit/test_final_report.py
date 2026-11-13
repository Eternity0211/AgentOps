from __future__ import annotations

import hashlib
import json
from pathlib import Path

from evaluation.final_report import ALLOWED_COVERAGE, build_report, render_markdown

REPORT = Path("evaluation/results/final-comparative-report/v1/report.json")
README = Path("evaluation/results/final-comparative-report/v1/README.md")
DOC = Path("docs/REAL_EVALUATION_REPORT.md")
REGISTRY = Path("evaluation/closure/v1/registry.json")


def test_published_final_report_is_recomputed_from_hashed_sources() -> None:
    published = json.loads(REPORT.read_text(encoding="utf-8"))

    assert published == build_report()
    assert README.read_text(encoding="utf-8") == render_markdown(published)
    assert DOC.read_text(encoding="utf-8") == render_markdown(published)
    for source in published["source_artifacts"]:
        assert hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest() == source["sha256"]


def test_every_registered_metric_has_one_explicit_supported_disposition() -> None:
    report = build_report()
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    expected = {
        (work["work_id"], metric) for work in registry["experiments"] for metric in work["metrics"]
    }
    actual = [(item["work_id"], item["metric"]) for item in report["coverage"]]

    assert set(actual) == expected
    assert len(actual) == len(set(actual))
    assert {item["status"] for item in report["coverage"]} <= ALLOWED_COVERAGE


def test_all_numeric_comparisons_expose_before_after_deltas_and_interval_field() -> None:
    report = build_report()

    assert report["comparisons"]
    for item in report["comparisons"]:
        assert isinstance(item["baseline"], (int, float))
        assert isinstance(item["candidate"], (int, float))
        assert item["absolute_delta"] == item["candidate"] - item["baseline"]
        expected_relative = (
            None
            if item["baseline"] == 0
            else (item["candidate"] - item["baseline"]) / item["baseline"]
        )
        assert item["relative_delta"] == expected_relative
        assert "delta_95pct_interval" in item
        assert item["denominator"] != "scope-defined"


def test_paired_intervals_are_attached_to_paired_delta_estimands() -> None:
    report = build_report()
    interval_rows = [
        item for item in report["comparisons"] if item["delta_95pct_interval"] is not None
    ]

    assert interval_rows
    assert all(
        item["work_id"] == "FC2" or item["statistic"] == "median-paired-delta"
        for item in interval_rows
    )


def test_external_data_is_not_fabricated_or_silently_omitted() -> None:
    report = build_report()

    assert {item["work_id"] for item in report["external_blockers"]} == {
        "FC4",
        "FC5",
        "FC6",
        "FC7",
        "FC8",
    }
    assert all(item["required_external_data"] for item in report["external_blockers"])
    blocked = [
        item
        for item in report["coverage"]
        if item["work_id"] in {"FC4", "FC5", "FC6", "FC7", "FC8"}
    ]
    assert blocked
    assert {item["status"] for item in blocked} == {"BLOCKED_EXTERNAL_DATA"}

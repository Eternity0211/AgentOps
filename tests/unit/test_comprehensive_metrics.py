"""Comprehensive four-baseline metrics and worker-resilience evidence tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from evaluation.comprehensive_metrics import (
    build_comprehensive_metrics,
    generate_comprehensive_report,
    render_comprehensive_markdown,
)
from evaluation.contracts import EvaluationContractError, load_json_object
from evaluation.run_worker_resilience_evaluation import (
    SuiteExecution,
    execute_worker_resilience_evaluation,
    load_worker_resilience_result,
)

ROOT = Path(__file__).resolve().parents[2]
RESULT_ROOT = ROOT / "evaluation" / "results" / "comprehensive" / "v1" / "run-001"


def _worker_result(path: Path) -> Path:
    times = iter(
        (
            datetime(2026, 10, 29, 13, 0, tzinfo=UTC),
            datetime(2026, 10, 29, 13, 1, tzinfo=UTC),
        )
    )
    fingerprint = execute_worker_resilience_evaluation(
        output_path=path,
        code_revision="e" * 40,
        run_id="worker-resilience-test-001",
        executor=lambda _: SuiteExecution(collected_tests=17, duration_ms=1234),
        clock=lambda: next(times),
    )
    assert len(fingerprint) == 64
    return path


def test_worker_resilience_result_is_closed_create_only_and_tamper_evident(
    tmp_path: Path,
) -> None:
    path = _worker_result(tmp_path / "worker.json")
    result = load_worker_resilience_result(path)
    assert result["summary"] == {"passed_controls": 13, "total_controls": 13}
    assert result["collected_tests"] == 17
    assert result["duration_ms"] == 1234

    with pytest.raises(EvaluationContractError, match="already exists"):
        execute_worker_resilience_evaluation(
            output_path=path,
            code_revision="e" * 40,
            run_id="worker-resilience-test-002",
            executor=lambda _: SuiteExecution(17, 1),
        )

    changed = load_json_object(path)
    changed["controls"][0]["status"] = "skipped"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(EvaluationContractError, match="controls"):
        load_worker_resilience_result(tampered)


def test_comprehensive_metrics_bind_all_four_runs_and_explicit_denominators(
    tmp_path: Path,
) -> None:
    worker = _worker_result(tmp_path / "worker.json")
    result = build_comprehensive_metrics(root=ROOT, worker_result_path=worker)
    baselines = {item["baseline_id"]: item for item in result["baselines"]}

    rules = baselines["baseline-a-rules"]["diagnosis"]
    assert rules["top1_root_cause"] == {"numerator": 0, "denominator": 6, "status": "measured"}
    assert rules["top3_root_cause"] == {"numerator": 0, "denominator": 6, "status": "measured"}
    assert rules["unsupported_conclusions"] == {
        "numerator": 0,
        "denominator": 0,
        "status": "measured",
    }
    assert rules["correct_handoff"]["numerator"] == 6

    single = baselines["baseline-b-single"]["diagnosis"]
    assert single["top1_root_cause"]["numerator"] == 2
    assert single["top3_root_cause"]["numerator"] == 2
    assert single["unsupported_conclusions"]["numerator"] == 4
    assert single["fabricated_references"]["numerator"] == 0
    assert single["fabricated_references"]["denominator"] == 6

    graph = baselines["baseline-c-graph"]["diagnosis"]
    memory = baselines["baseline-d-memory"]["diagnosis"]
    assert graph["tool_calls"] == {"denominator": 6, "total": 12}
    assert graph["input_tokens"]["total"] == 912
    assert memory["input_tokens"]["total"] == 1104
    assert memory["output_tokens"]["total"] == graph["output_tokens"]["total"] == 1484

    for item in baselines.values():
        recovery = item["recovery"]
        assert recovery["proposal_correctness"]["numerator"] == 2
        assert recovery["dangerous_action_blocks"]["numerator"] == 4
        assert recovery["unapproved_executions"] == {
            "numerator": 0,
            "denominator": 2,
            "status": "measured",
        }
        assert recovery["duplicate_executions"] == {
            "numerator": 0,
            "denominator": 0,
            "status": "not_measured",
        }
        assert recovery["eligible_automated_recovery"]["numerator"] == 1
        assert recovery["eligible_automated_recovery"]["denominator"] == 2
        assert recovery["recovery_safe_outcomes"]["numerator"] == 5
        assert recovery["future_compensation_attempts"]["numerator"] == 0
        assert recovery["future_compensation_attempts"]["denominator"] == 6

    assert result["worker_recovery"]["result"] == {
        "numerator": 13,
        "denominator": 13,
        "status": "measured",
    }
    markdown = render_comprehensive_markdown(result)
    assert "not measured (0/0)" in markdown
    assert "no production latency" in markdown


def test_comprehensive_report_is_deterministic_and_create_only(tmp_path: Path) -> None:
    worker = _worker_result(tmp_path / "worker.json")
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_hashes = generate_comprehensive_report(output_dir=first, worker_result_path=worker)
    second_hashes = generate_comprehensive_report(output_dir=second, worker_result_path=worker)
    assert first_hashes == second_hashes
    assert (first / "metrics.json").read_bytes() == (second / "metrics.json").read_bytes()
    assert (first / "README.md").read_bytes() == (second / "README.md").read_bytes()
    with pytest.raises(EvaluationContractError, match="already exists"):
        generate_comprehensive_report(output_dir=first, worker_result_path=worker)


@pytest.mark.parametrize(
    ("revision", "run_id", "expected"),
    (("short", "valid-run", "revision"), ("f" * 40, "INVALID RUN", "run ID")),
)
def test_worker_resilience_rejects_invalid_identity(
    tmp_path: Path, revision: str, run_id: str, expected: str
) -> None:
    with pytest.raises(EvaluationContractError, match=expected):
        execute_worker_resilience_evaluation(
            output_path=tmp_path / "worker.json",
            code_revision=revision,
            run_id=run_id,
            executor=lambda _: SuiteExecution(17, 1),
        )


def test_worker_resilience_rejects_backwards_clock(tmp_path: Path) -> None:
    now = datetime(2026, 10, 29, 13, 0, tzinfo=UTC)
    times = iter((now, now - timedelta(seconds=1)))
    with pytest.raises(EvaluationContractError, match="backwards"):
        execute_worker_resilience_evaluation(
            output_path=tmp_path / "worker.json",
            code_revision="f" * 40,
            run_id="worker-resilience-test-003",
            executor=lambda _: SuiteExecution(17, 1),
            clock=lambda: next(times),
        )


def test_committed_comprehensive_result_reloads_exactly() -> None:
    worker_path = RESULT_ROOT / "worker-resilience-raw.json"
    worker = load_worker_resilience_result(worker_path)
    assert worker["code_revision"] == "5d036744fbe1ce430b4b59e48f54bfc10373baea"
    assert worker["run_id"] == "worker-resilience-20261029-001"
    assert worker["summary"] == {"passed_controls": 13, "total_controls": 13}
    assert worker["collected_tests"] == 20

    rebuilt = build_comprehensive_metrics(root=ROOT, worker_result_path=worker_path)
    committed = load_json_object(RESULT_ROOT / "metrics.json")
    assert rebuilt == committed
    assert render_comprehensive_markdown(rebuilt) == (RESULT_ROOT / "README.md").read_text(
        encoding="utf-8"
    )

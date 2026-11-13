"""Generate the versioned final comparative report from immutable result artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationContractError, load_json_object

REPORT_SCHEMA = "final-comparative-report/1.0.0"
REPORT_DATE = "2026-11-14"
ALLOWED_COVERAGE = frozenset(
    {"MEASURED", "FAILED", "NO_PROVEN_IMPROVEMENT", "NOT_REQUIRED", "BLOCKED_EXTERNAL_DATA"}
)
SOURCE_PATHS = (
    Path("evaluation/closure/v1/registry.json"),
    Path("evaluation/results/structured-reliability/v2/run-001/analysis/score.json"),
    Path("evaluation/results/memory-context/v3/run-001/score.json"),
    Path("evaluation/results/final-durability/v1/run-001/result.json"),
    Path("evaluation/results/final-load/v1/confirmatory-001/confirmatory.json"),
    Path("evaluation/results/database-resource/v1/run-001/result.json"),
    Path("evaluation/results/final-security/v1/run-001/result.json"),
    Path("evaluation/results/architecture-decisions/v1/decisions.json"),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(baseline: float, candidate: float) -> float | None:
    return None if baseline == 0 else (candidate - baseline) / baseline


def _comparison(
    work_id: str,
    metric: str,
    unit: str,
    baseline: float,
    candidate: float,
    *,
    interval: Sequence[float] | None = None,
    statistic: str = "value",
    status: str = "MEASURED",
    scope: str,
    denominator: int | str = "scope-defined",
) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "metric": metric,
        "statistic": statistic,
        "unit": unit,
        "baseline": baseline,
        "candidate": candidate,
        "absolute_delta": candidate - baseline,
        "relative_delta": _relative(baseline, candidate),
        "delta_95pct_interval": list(interval) if interval is not None else None,
        "status": status,
        "scope": scope,
        "denominator": denominator,
    }


def _fc2_comparisons(score: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    paired = score["paired_result"]
    for metric in paired["metrics"]:
        for estimate in metric["estimates"]:
            output.append(
                _comparison(
                    "FC2",
                    str(metric["metric_id"]),
                    "rate" if estimate["statistic"] == "rate" else str(metric["metric_id"]),
                    float(estimate["baseline"]),
                    float(estimate["candidate"]),
                    interval=(
                        float(estimate["absolute_delta_interval"]["lower"]),
                        float(estimate["absolute_delta_interval"]["upper"]),
                    ),
                    statistic=str(estimate["statistic"]),
                    status="NO_PROVEN_IMPROVEMENT",
                    scope="Frozen paired census; cost is a rate-card upper bound, not billing.",
                    denominator=int(metric["pair_count"]),
                )
            )
    audit = score["audit"]
    before = float(audit["baseline-1.5"]["initial_schema_protocol_invalids"])
    after = float(audit["candidate-1.6"]["initial_schema_protocol_invalids"])
    output.append(
        _comparison(
            "FC2",
            "initial-schema-protocol-invalids",
            "outcomes",
            before,
            after,
            status="MEASURED",
            scope="81 outcomes per arm; bounded repair made terminal invalids 0→0.",
            denominator=81,
        )
    )
    return output


def _fc3_comparisons(score: Mapping[str, Any]) -> list[dict[str, Any]]:
    before, after = score["arms"]["baseline-context"], score["arms"]["candidate-context"]
    scope = "Frozen ten-pair designed memory-context set; not an untouched diagnosis study."
    output = [
        _comparison(
            "FC3",
            "correct-diagnosis-rate",
            "rate",
            before["correct"] / before["total"],
            after["correct"] / after["total"],
            status="NO_PROVEN_IMPROVEMENT",
            scope=scope,
            denominator=10,
        ),
        _comparison(
            "FC3",
            "sustained-retention-detection-rate",
            "rate",
            before["sustained_detected"] / 2,
            after["sustained_detected"] / 2,
            status="NO_PROVEN_IMPROVEMENT",
            scope=scope,
            denominator=2,
        ),
        _comparison(
            "FC3",
            "safe-negative-rate",
            "rate",
            before["safe_negatives"] / 8,
            after["safe_negatives"] / 8,
            status="MEASURED",
            scope=scope,
            denominator=8,
        ),
        _comparison(
            "FC3",
            "failure-count",
            "outcomes",
            before["failures"],
            after["failures"],
            status="MEASURED",
            scope=scope,
            denominator=10,
        ),
    ]
    resources = (
        ("duration", "duration_ms", "ms"),
        ("input-tokens", "input_tokens", "tokens"),
        ("output-tokens", "output_tokens", "tokens"),
        ("cost-upper-bound", "cost_upper_bound_nanousd", "nUSD"),
    )
    for metric, key, unit in resources:
        output.append(
            _comparison(
                "FC3",
                metric,
                unit,
                before["resource_totals"][key],
                after["resource_totals"][key],
                status="NO_PROVEN_IMPROVEMENT",
                scope=scope,
                denominator=10,
            )
        )
    return output


def _fc9_comparisons(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    pairs = result["pairs"]
    scope = "Eight frozen local controlled workflow pairs; rate-card cost is not billing."
    output = [
        _comparison(
            "FC9",
            "terminal-route-match-rate",
            "rate",
            1.0,
            result["summary"]["terminal_route_matches"] / 8,
            status="MEASURED",
            scope=scope,
            denominator=8,
        )
    ]
    for metric in (
        "duplicate_external_effects",
        "ambiguous_result_redispatches",
        "lost_evidence_records",
    ):
        before = sum(pair["metrics"][metric]["control"] for pair in pairs)
        after = sum(pair["metrics"][metric]["treatment"] for pair in pairs)
        output.append(
            _comparison(
                "FC9",
                metric,
                "events",
                before,
                after,
                status="MEASURED",
                scope=scope,
                denominator=8,
            )
        )
    total_before = [pair["metrics"]["total_latency_ms"]["control"] for pair in pairs]
    total_after = [pair["metrics"]["total_latency_ms"]["treatment"] for pair in pairs]
    output.append(
        _comparison(
            "FC9",
            "total-latency",
            "ms",
            statistics.median(total_before),
            statistics.median(total_after),
            statistic="arm-median",
            status="NO_PROVEN_IMPROVEMENT",
            scope=scope,
            denominator=8,
        )
    )
    output.append(
        _comparison(
            "FC9",
            "paired-total-latency-delta",
            "ms",
            0,
            result["summary"]["total_latency_delta_median_ms"],
            interval=result["summary"]["total_latency_delta_median_95pct_bootstrap_ms"],
            statistic="median-paired-delta",
            status="NO_PROVEN_IMPROVEMENT",
            scope=scope,
            denominator=8,
        )
    )
    resume_before = [pair["metrics"]["takeover_or_resume_latency_ms"]["control"] for pair in pairs]
    resume_after = [pair["metrics"]["takeover_or_resume_latency_ms"]["treatment"] for pair in pairs]
    output.append(
        _comparison(
            "FC9",
            "resume-latency",
            "ms",
            statistics.median(resume_before),
            statistics.median(resume_after),
            interval=result["summary"]["resume_latency_delta_median_95pct_bootstrap_ms"],
            statistic="median-paired-delta",
            status="MEASURED",
            scope=scope,
            denominator=8,
        )
    )
    for metric, unit in (
        ("model_calls", "calls"),
        ("tool_calls", "calls"),
        ("input_tokens", "tokens"),
        ("output_tokens", "tokens"),
        ("rate_card_upper_bound_nusd", "nUSD"),
    ):
        before = sum(pair["metrics"][metric]["control"] for pair in pairs)
        after = sum(pair["metrics"][metric]["treatment"] for pair in pairs)
        output.append(
            _comparison(
                "FC9",
                metric,
                unit,
                before,
                after,
                status="MEASURED",
                scope=scope,
                denominator=8,
            )
        )
    return output


def _fc10_comparisons(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = {group["workers"]: group for group in result["groups"]}
    baseline = groups[1]
    lease_contentions = {
        workers: sum(
            row["lease_contention_count"] for row in result["rows"] if row["workers"] == workers
        )
        for workers in (1, 2, 4, 8)
    }
    output: list[dict[str, Any]] = []
    fields = (
        ("throughput", "throughput_jobs_per_second_median", "jobs/s"),
        ("queue-wait-p95", "queue_wait_p95_ms_median", "ms"),
        ("workflow-latency-p95", "workflow_latency_p95_ms_median", "ms"),
        ("error-count", "error_count", "events"),
        ("duplicate-job-ownership", "duplicate_job_ownership", "events"),
        ("process-cpu", "process_cpu_ms_median", "ms"),
        ("python-heap-peak", "python_heap_peak_bytes_median", "bytes"),
        ("database-statement-count", "database_statement_count_median", "statements"),
    )
    for workers in (2, 4, 8):
        candidate = groups[workers]
        for metric, key, unit in fields:
            output.append(
                _comparison(
                    "FC10",
                    f"{metric}:1-to-{workers}-workers",
                    unit,
                    baseline[key],
                    candidate[key],
                    statistic="median",
                    status="MEASURED",
                    scope=(
                        "Eleven local repetitions; process metrics exclude "
                        "PostgreSQL/container resources."
                    ),
                    denominator=11,
                )
            )
        output.append(
            _comparison(
                "FC10",
                f"throughput-paired-delta:1-to-{workers}-workers",
                "jobs/s",
                0,
                candidate["throughput_absolute_delta_from_1_worker_median"],
                interval=candidate["throughput_absolute_delta_95pct_bootstrap"],
                statistic="median-paired-delta",
                status="MEASURED",
                scope="Eleven local paired repetitions per worker level.",
                denominator=11,
            )
        )
        output.append(
            _comparison(
                "FC10",
                f"lease-contentions:1-to-{workers}-workers",
                "events",
                lease_contentions[1],
                lease_contentions[workers],
                statistic="11-repetition-total",
                status="MEASURED",
                scope="Eleven local repetitions per worker level.",
                denominator=11,
            )
        )
    return output


def _fc10_database_resource_comparisons(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    scope = (
        "Eleven local paired repetitions; Docker PostgreSQL-container load only, "
        "not application benefit or production capacity."
    )
    units = {
        "postgres_container_cpu_usage_usec": "usec",
        "postgres_container_memory_peak_observed_bytes": "bytes",
        "postgres_container_io_read_bytes": "bytes",
        "postgres_container_io_write_bytes": "bytes",
    }
    for item in result["comparisons"]:
        workers = int(item["workers"])
        metric = str(item["metric"])
        unit = units.get(metric, "counter-delta")
        output.append(
            _comparison(
                "FC10",
                f"{metric}:1-to-{workers}-workers",
                unit,
                float(item["baseline_median"]),
                float(item["candidate_median"]),
                statistic="arm-median",
                status="MEASURED",
                scope=scope,
                denominator=int(item["denominator_pairs"]),
            )
        )
        output.append(
            _comparison(
                "FC10",
                f"{metric}-paired-delta:1-to-{workers}-workers",
                unit,
                0,
                float(item["paired_absolute_delta_median"]),
                interval=item["paired_absolute_delta_median_95pct_bootstrap"],
                statistic="median-paired-delta",
                status="MEASURED",
                scope=scope,
                denominator=int(item["denominator_pairs"]),
            )
        )
    return output


def _rate(pair: Sequence[int]) -> float:
    return float(pair[0]) / float(pair[1])


def _fc11_comparisons(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    scope = "Fixed 13-case local deterministic census; duration includes environment setup."
    for metric in ("attack_block", "safe_handoff", "false_block", "route_correctness"):
        output.append(
            _comparison(
                "FC11",
                metric,
                "rate",
                _rate(result["metrics"]["baseline"][metric]),
                _rate(result["metrics"]["candidate"][metric]),
                status="MEASURED",
                scope=scope,
                denominator=result["metrics"]["baseline"][metric][1],
            )
        )
    for metric, unit in (
        ("critical_failures", "events"),
        ("duration_ms", "ms"),
        ("provider_cost_nusd", "nUSD"),
    ):
        output.append(
            _comparison(
                "FC11",
                metric,
                unit,
                result["metrics"]["baseline"][metric],
                result["metrics"]["candidate"][metric],
                status="MEASURED",
                scope=scope,
                denominator=13,
            )
        )
    return output


def _coverage_status(work_id: str, metric: str, work_status: str) -> tuple[str, str]:
    if work_status == "BLOCKED_EXTERNAL_DATA":
        return "BLOCKED_EXTERNAL_DATA", "Required authorized external observations do not exist."
    if work_id == "FC12":
        return (
            "NOT_REQUIRED",
            "No named current-version requirement justifies the optional capability.",
        )
    if work_id == "FC10" and metric == "database_load":
        return (
            "MEASURED",
            "PostgreSQL-container CPU, memory, block I/O and database counters were measured.",
        )
    if work_id in {"FC2", "FC3"} and metric in {"top1", "memory_top1", "latency", "tokens", "cost"}:
        return "NO_PROVEN_IMPROVEMENT", "Observed deltas do not establish statistical superiority."
    if work_id == "FC9" and metric == "total_latency":
        return "NO_PROVEN_IMPROVEMENT", "The paired 95% delta interval crosses zero."
    return "MEASURED", "Measured or deterministically verified in the cited frozen artifact."


def build_report(root: Path = Path(".")) -> dict[str, Any]:
    sources = [root / path for path in SOURCE_PATHS]
    if any(not path.is_file() for path in sources):
        raise EvaluationContractError("final report source artifact is missing")
    loaded = tuple(load_json_object(path, maximum_bytes=8_388_608) for path in sources)
    (
        registry,
        structured,
        memory,
        durability,
        capacity,
        database_resource,
        security,
        architecture,
    ) = loaded
    comparisons = (
        _fc2_comparisons(structured)
        + _fc3_comparisons(memory)
        + _fc9_comparisons(durability)
        + _fc10_comparisons(capacity)
        + _fc10_database_resource_comparisons(database_resource)
        + _fc11_comparisons(security)
    )
    coverage: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    for work in registry["experiments"]:
        for metric in work["metrics"]:
            status, note = _coverage_status(work["work_id"], metric, work["status"])
            coverage.append(
                {"work_id": work["work_id"], "metric": metric, "status": status, "note": note}
            )
        if work["status"] == "BLOCKED_EXTERNAL_DATA":
            blockers.append(
                {
                    "work_id": work["work_id"],
                    "title": work["title"],
                    "required_external_data": work["external_requirements"],
                    "metrics": work["metrics"],
                }
            )
    if any(item["status"] not in ALLOWED_COVERAGE for item in coverage):
        raise EvaluationContractError("final report contains an unsupported coverage status")
    return {
        "schema_version": REPORT_SCHEMA,
        "report_date": REPORT_DATE,
        "objective": (
            "Reproducible baseline-versus-candidate closure without fabricated external data."
        ),
        "source_artifacts": [
            {"path": path.as_posix(), "sha256": _sha256(root / path)} for path in SOURCE_PATHS
        ],
        "coverage": coverage,
        "comparisons": comparisons,
        "external_blockers": blockers,
        "architecture_decisions": architecture["decisions"],
        "frozen_protocols": {
            "FC2_protocol_sha256": structured["protocol_sha256"],
            "FC2_comparison_request_sha256": structured["paired_result"]["request_sha256"],
            "FC9_plan_sha256": durability["plan_sha256"],
            "FC10_plan_sha256": capacity["plan_sha256"],
            "FC10_database_resource_plan_sha256": database_resource["plan_sha256"],
            "FC11_plan_sha256": security["plan_sha256"],
        },
        "failures": {
            "FC2_provider_error_codes": structured["provider_error_codes"],
            "FC3_baseline_failures": memory["arms"]["baseline-context"]["failures"],
            "FC3_candidate_failures": memory["arms"]["candidate-context"]["failures"],
            "FC9_duplicate_external_effects": durability["summary"]["duplicate_external_effects"],
            "FC10_error_count": sum(group["error_count"] for group in capacity["groups"]),
            "FC10_database_resource_accepted": database_resource["accepted"],
            "FC11_critical_failures": security["metrics"]["candidate"]["critical_failures"],
        },
        "key_results": {
            "structured_acceptance_passed": structured["acceptance"]["passed"],
            "memory_correct_baseline": memory["arms"]["baseline-context"]["correct"],
            "memory_correct_candidate": memory["arms"]["candidate-context"]["correct"],
            "durability_route_matches": durability["summary"]["terminal_route_matches"],
            "durability_pairs": durability["summary"]["completed_pairs"],
            "capacity_broker_decision": capacity["broker_decision"],
            "database_resource_rows": len(database_resource["rows"]),
            "security_accepted": security["accepted"],
        },
        "limitations": [
            (
                "FC4-FC8 remain blocked by explicitly named authorized human, history, "
                "approval or billing data."
            ),
            (
                "No result establishes human labor reduction, MTTR reduction, actual provider "
                "cost savings or production reliability."
            ),
            "Local capacity and database-resource results cannot set production capacity.",
            "Rate-card upper bounds are not provider invoices.",
        ],
        "reproduction": [
            (
                ".venv/Scripts/python -m evaluation.final_report --output "
                "evaluation/results/final-comparative-report/v1 --doc "
                "docs/REAL_EVALUATION_REPORT.md"
            ),
            ".venv/Scripts/pytest -q --no-cov tests/unit/test_final_report.py",
        ],
    }


def _format_number(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float) and math.isfinite(value):
        return f"{value:.6g}"
    return str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# AgentOps final comparative evaluation",
        "",
        (
            f"Generated from immutable artifacts under `{report['schema_version']}` on "
            f"{report['report_date']}."
        ),
        "No externally blocked metric is replaced by simulation or inference.",
        "",
        "## Outcome",
        "",
        (
            "Structured-output acceptance, the eight-pair durability safety gate and the "
            "13-case security census passed. "
            "The designed memory set changed 9/10→10/10, but the ten-pair sample does not prove "
            "superiority. PostgreSQL throughput improved through four local workers and regressed "
            "at eight; the current supported local cap is four."
        ),
        "Human outcomes, approved recovery benefit and actual cost remain externally blocked.",
        "",
        "## Metric coverage",
        "",
        "| Work | Metric | Status | Note |",
        "| --- | --- | --- | --- |",
    ]
    for item in report["coverage"]:
        lines.append(
            f"| {item['work_id']} | `{item['metric']}` | `{item['status']}` | {item['note']} |"
        )
    lines.extend(
        (
            "",
            "## Baseline/candidate comparisons",
            "",
            (
                "| Work | Metric | Statistic | Baseline | Candidate | Absolute delta | "
                "Relative delta | 95% delta interval | Status |"
            ),
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        )
    )
    for item in report["comparisons"]:
        interval = item["delta_95pct_interval"]
        shown_interval = (
            "N/A"
            if interval is None
            else f"[{_format_number(interval[0])}, {_format_number(interval[1])}]"
        )
        relative = item["relative_delta"]
        lines.append(
            f"| {item['work_id']} | `{item['metric']}` ({item['unit']}) | {item['statistic']} | "
            f"{_format_number(item['baseline'])} | {_format_number(item['candidate'])} | "
            f"{_format_number(item['absolute_delta'])} | {_format_number(relative)} | "
            f"{shown_interval} | `{item['status']}` |"
        )
    lines.extend(("", "## External blockers", ""))
    for blocker in report["external_blockers"]:
        requirements = "; ".join(blocker["required_external_data"])
        lines.append(f"- **{blocker['work_id']} — {blocker['title']}:** {requirements}.")
    lines.extend(("", "## Limitations", ""))
    lines.extend(f"- {item}" for item in report["limitations"])
    lines.extend(("", "## Integrity and reproduction", ""))
    lines.append("The JSON publication records SHA-256 for every source artifact. Reproduce with:")
    lines.append("")
    lines.extend(f"- `{command}`" for command in report["reproduction"])
    lines.append("")
    return "\n".join(lines)


def publish(report: Mapping[str, Any], output: Path, doc: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n"
    )
    markdown = render_markdown(report)
    (output / "report.json").write_text(payload, encoding="utf-8", newline="\n")
    (output / "README.md").write_text(markdown, encoding="utf-8", newline="\n")
    doc.write_text(markdown, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--doc", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report()
    publish(report, args.output, args.doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

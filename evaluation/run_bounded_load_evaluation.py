"""Run and report the fixed local bounded-load matrix without production claims."""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object

SCHEMA_VERSION = "1.0"
PLAN_VERSION = "phase12-bounded-load-v1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class LoadWorkload:
    workload_id: str
    operations: int
    concurrency: int
    test_node: str


@dataclass(frozen=True, slots=True)
class LoadPlan:
    workloads: tuple[LoadWorkload, ...]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class LoadExecution:
    durations_ms: Mapping[str, int]
    collected_tests: int


LoadExecutor = Callable[[Path, LoadPlan], LoadExecution]


def junit_name_matches(case_name: str, test_name: str) -> bool:
    """Match pytest's plain or AnyIO-backend-suffixed JUnit case name."""
    return case_name == test_name or case_name.startswith(f"{test_name}[")


def load_plan(path: Path) -> LoadPlan:
    value = load_json_object(path)
    if set(value) != {"plan_version", "schema_version", "workloads"}:
        raise EvaluationContractError("bounded-load plan fields do not match the closed contract")
    if value["schema_version"] != "1.0" or value["plan_version"] != PLAN_VERSION:
        raise EvaluationContractError("unsupported bounded-load plan")
    workloads_value = value["workloads"]
    if not isinstance(workloads_value, list) or len(workloads_value) != 4:
        raise EvaluationContractError("bounded-load plan requires four workloads")
    workloads: list[LoadWorkload] = []
    for item in workloads_value:
        if not isinstance(item, dict) or set(item) != {
            "concurrency",
            "operations",
            "test_node",
            "workload_id",
        }:
            raise EvaluationContractError("bounded-load workload is malformed")
        operations = item["operations"]
        concurrency = item["concurrency"]
        workload_id = item["workload_id"]
        test_node = item["test_node"]
        if (
            type(operations) is not int
            or not 1 <= operations <= 1_000
            or type(concurrency) is not int
            or not 1 <= concurrency <= 64
            or concurrency > operations
            or not isinstance(workload_id, str)
            or not isinstance(test_node, str)
            or "::test_bounded_" not in test_node
        ):
            raise EvaluationContractError("bounded-load workload values are invalid")
        workloads.append(LoadWorkload(workload_id, operations, concurrency, test_node))
    if tuple(item.workload_id for item in workloads) != (
        "api-health",
        "evidence-query",
        "job-leasing",
        "worker-processing",
    ):
        raise EvaluationContractError("bounded-load workloads are incomplete or reordered")
    fingerprint = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return LoadPlan(tuple(workloads), fingerprint)


def _default_executor(root: Path, plan: LoadPlan) -> LoadExecution:
    with tempfile.TemporaryDirectory(prefix="agentops-load-") as directory:
        junit = Path(directory) / "junit.xml"
        command = (
            sys.executable,
            "-m",
            "pytest",
            *(item.test_node for item in plan.workloads),
            "-p",
            "no:cacheprovider",
            "--no-cov",
            "--junitxml",
            str(junit),
        )
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                check=False,
                text=True,
                timeout=240,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise EvaluationContractError("bounded-load suite could not complete") from error
        if completed.returncode != 0:
            raise EvaluationContractError("bounded-load suite failed")
        try:
            document = ET.parse(junit).getroot()
        except (OSError, ET.ParseError) as error:
            raise EvaluationContractError("bounded-load JUnit result is invalid") from error
        suites = list(document) if document.tag == "testsuites" else [document]
        cases = [case for suite in suites for case in suite.findall("testcase")]
        if any(
            case.find("failure") is not None
            or case.find("error") is not None
            or case.find("skipped") is not None
            for case in cases
        ):
            raise EvaluationContractError("bounded-load suite was not an all-pass run")
        durations: dict[str, int] = {}
        for workload in plan.workloads:
            test_name = workload.test_node.rsplit("::", 1)[1]
            matches = [
                case for case in cases if junit_name_matches(case.attrib.get("name", ""), test_name)
            ]
            if len(matches) != 1:
                raise EvaluationContractError("bounded-load JUnit workload set is incomplete")
            try:
                duration_ms = max(1, round(float(matches[0].attrib["time"]) * 1_000))
            except (KeyError, ValueError) as error:
                raise EvaluationContractError("bounded-load JUnit duration is invalid") from error
            durations[workload.workload_id] = duration_ms
    return LoadExecution(durations, len(cases))


def _render(document: Mapping[str, Any]) -> str:
    lines = [
        "# AgentOps bounded local load evaluation",
        "",
        f"- Run: `{document['run_id']}`",
        f"- Code revision: `{document['code_revision']}`",
        f"- Plan: `{document['plan_version']}` (`{document['plan_sha256']}`)",
        (
            f"- Environment: Python {document['python_version']} on "
            f"`{document['platform']}`; {document['hardware_summary']}"
        ),
        f"- Window: {document['started_at']} to {document['finished_at']}",
        f"- Collected tests: {document['collected_tests']}",
        "",
        "| Workload | Completed | Concurrency | Duration ms | Observed ops/s |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for item in document["workloads"]:
        lines.append(
            f"| `{item['workload_id']}` | "
            f"{item['completed_operations']}/{item['configured_operations']} | "
            f"{item['concurrency']} | {item['duration_ms']} | "
            f"{item['operations_per_second_milli'] / 1000:.3f} |"
        )
    lines.extend(
        [
            "",
            "> These are bounded component-level measurements from one local run. PostgreSQL "
            "workloads use a temporary Testcontainer; API and worker workloads run in-process. "
            "The figures are not production throughput, capacity, availability, or reliability "
            "claims and do not justify adding a message broker.",
            "",
        ]
    )
    return "\n".join(lines)


def execute_bounded_load_evaluation(
    *,
    output_dir: Path,
    plan_path: Path,
    code_revision: str,
    run_id: str,
    executor: LoadExecutor = _default_executor,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, str]:
    if _REVISION.fullmatch(code_revision) is None or _RUN_ID.fullmatch(run_id) is None:
        raise EvaluationContractError("bounded-load run identity is invalid")
    plan = load_plan(plan_path)
    started = clock()
    execution = executor(Path(__file__).resolve().parents[1], plan)
    finished = clock()
    if started.tzinfo is None or finished.tzinfo is None or finished < started:
        raise EvaluationContractError("bounded-load timestamps are invalid")
    if set(execution.durations_ms) != {item.workload_id for item in plan.workloads}:
        raise EvaluationContractError("bounded-load execution omitted a workload")
    workloads: list[dict[str, Any]] = []
    for item in plan.workloads:
        duration_ms = execution.durations_ms[item.workload_id]
        if type(duration_ms) is not int or duration_ms <= 0:
            raise EvaluationContractError("bounded-load duration must be positive")
        workloads.append(
            {
                "completed_operations": item.operations,
                "concurrency": item.concurrency,
                "configured_operations": item.operations,
                "duration_ms": duration_ms,
                "operations_per_second_milli": item.operations * 1_000_000 // duration_ms,
                "workload_id": item.workload_id,
            }
        )
    document: dict[str, Any] = {
        "code_revision": code_revision,
        "collected_tests": execution.collected_tests,
        "finished_at": finished.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "hardware_summary": (
            f"machine={platform.machine()};logical_cpu_count={os.cpu_count() or 'unknown'}"
        ),
        "plan_sha256": plan.fingerprint,
        "plan_version": PLAN_VERSION,
        "platform": f"{sys.platform}-{platform.machine().lower()}",
        "python_version": platform.python_version(),
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "started_at": started.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "workloads": workloads,
    }
    payload = f"{canonical_json(document)}\n"
    markdown = _render(document)
    raw_path = output_dir / "load-raw.json"
    report_path = output_dir / "README.md"
    if raw_path.exists() or report_path.exists():
        raise EvaluationContractError("bounded-load output already exists")
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        with raw_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        with report_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(markdown)
    except OSError as error:
        raise EvaluationContractError("bounded-load output cannot be persisted") from error
    return (
        hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest(),
        hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        fingerprints = execute_bounded_load_evaluation(
            output_dir=arguments.output_dir,
            plan_path=arguments.plan,
            code_revision=arguments.code_revision,
            run_id=arguments.run_id,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] bounded load failed reason={error}", file=sys.stderr)
        return 2
    print(
        "[evaluation] bounded load complete "
        f"raw_sha256={fingerprints[0]} report_sha256={fingerprints[1]}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

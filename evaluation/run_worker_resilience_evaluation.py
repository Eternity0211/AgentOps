"""Create-only measured worker-resilience evidence for the comprehensive report."""

from __future__ import annotations

import argparse
import hashlib
import platform
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agentops_incident_commander.dev_tasks import RESILIENCE_TEST_CASES
from evaluation.contracts import EvaluationContractError, canonical_json, load_json_object

SCHEMA_VERSION = "1.0"
SUITE_VERSION = "phase12-worker-resilience-v1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


@dataclass(frozen=True, slots=True)
class SuiteExecution:
    """Content-free outcome from the fixed pytest suite."""

    collected_tests: int
    duration_ms: int


SuiteExecutor = Callable[[Path], SuiteExecution]


def _test_nodes() -> tuple[str, ...]:
    return tuple(dict.fromkeys(node for _, node in RESILIENCE_TEST_CASES))


def _command() -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "pytest",
        *_test_nodes(),
        "-p",
        "no:cacheprovider",
        "--no-cov",
        "--junitxml",
        "<temporary-junit-path>",
    )


def _default_executor(root: Path) -> SuiteExecution:
    started = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix="agentops-resilience-") as directory:
        junit = Path(directory) / "junit.xml"
        command = [*(_command()[:-1]), str(junit)]
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
            raise EvaluationContractError("worker-resilience suite could not complete") from error
        if completed.returncode != 0:
            raise EvaluationContractError("worker-resilience suite failed")
        try:
            suite = ET.parse(junit).getroot()
        except (OSError, ET.ParseError) as error:
            raise EvaluationContractError("worker-resilience JUnit result is invalid") from error
        if suite.tag == "testsuites":
            children = list(suite)
            if len(children) != 1:
                raise EvaluationContractError("worker-resilience JUnit suite is ambiguous")
            suite = children[0]
        counts = {
            name: int(suite.attrib.get(name, "0"))
            for name in ("tests", "failures", "errors", "skipped")
        }
        if counts["tests"] < len(RESILIENCE_TEST_CASES):
            raise EvaluationContractError("worker-resilience suite did not collect every control")
        if any(counts[name] for name in ("failures", "errors", "skipped")):
            raise EvaluationContractError("worker-resilience suite was not an all-pass run")
    duration_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
    return SuiteExecution(counts["tests"], duration_ms)


def _controls() -> list[dict[str, str]]:
    return [
        {"control_id": control_id, "node_id": node_id, "status": "passed"}
        for control_id, node_id in RESILIENCE_TEST_CASES
    ]


def execute_worker_resilience_evaluation(
    *,
    output_path: Path,
    code_revision: str,
    run_id: str,
    executor: SuiteExecutor = _default_executor,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Run the fixed suite and create one hashable result without overwriting."""
    if _REVISION.fullmatch(code_revision) is None:
        raise EvaluationContractError("worker-resilience code revision must be a full Git SHA")
    if _RUN_ID.fullmatch(run_id) is None:
        raise EvaluationContractError("worker-resilience run ID is invalid")
    started_at = clock()
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise EvaluationContractError("worker-resilience clock must be timezone aware")
    root = Path(__file__).resolve().parents[1]
    execution = executor(root)
    finished_at = clock()
    if finished_at < started_at:
        raise EvaluationContractError("worker-resilience clock moved backwards")
    controls = _controls()
    command_sha256 = hashlib.sha256("\0".join(_command()).encode("utf-8")).hexdigest()
    document: dict[str, Any] = {
        "code_revision": code_revision,
        "collected_tests": execution.collected_tests,
        "command_sha256": command_sha256,
        "controls": controls,
        "duration_ms": execution.duration_ms,
        "finished_at": finished_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "platform": f"{sys.platform}-{platform.machine().lower()}",
        "python_version": platform.python_version(),
        "run_id": run_id,
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "suite_version": SUITE_VERSION,
        "summary": {"passed_controls": len(controls), "total_controls": len(controls)},
    }
    payload = f"{canonical_json(document)}\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
    except FileExistsError as error:
        raise EvaluationContractError("worker-resilience result already exists") from error
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


def load_worker_resilience_result(path: Path) -> dict[str, Any]:
    """Reload and validate the closed worker-resilience result."""
    value = load_json_object(path)
    expected_keys = {
        "code_revision",
        "collected_tests",
        "command_sha256",
        "controls",
        "duration_ms",
        "finished_at",
        "platform",
        "python_version",
        "run_id",
        "schema_version",
        "started_at",
        "suite_version",
        "summary",
    }
    if (
        set(value) != expected_keys
        or value["schema_version"] != SCHEMA_VERSION
        or value["suite_version"] != SUITE_VERSION
    ):
        raise EvaluationContractError("worker-resilience result contract mismatch")
    if value["controls"] != _controls():
        raise EvaluationContractError("worker-resilience controls do not match the fixed suite")
    expected_summary = {
        "passed_controls": len(RESILIENCE_TEST_CASES),
        "total_controls": len(RESILIENCE_TEST_CASES),
    }
    if value["summary"] != expected_summary:
        raise EvaluationContractError("worker-resilience summary is not all-pass")
    collected = value["collected_tests"]
    if type(collected) is not int or collected < len(RESILIENCE_TEST_CASES):
        raise EvaluationContractError("worker-resilience collected-test count is invalid")
    if not isinstance(value["command_sha256"], str) or len(value["command_sha256"]) != 64:
        raise EvaluationContractError("worker-resilience command fingerprint is invalid")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        fingerprint = execute_worker_resilience_evaluation(
            output_path=arguments.output,
            code_revision=arguments.code_revision,
            run_id=arguments.run_id,
        )
    except EvaluationContractError as error:
        print(f"[evaluation] worker resilience failed reason={error}", file=sys.stderr)
        return 2
    print(f"[evaluation] worker resilience complete sha256={fingerprint}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

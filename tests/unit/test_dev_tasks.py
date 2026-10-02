"""Tests for the allowlisted cross-platform developer task runner."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentops_incident_commander import dev_tasks


def test_quality_task_has_stable_bounded_order() -> None:
    """The aggregate quality task runs every required gate in a deterministic order."""
    commands = dev_tasks.command_specs("quality")

    assert [command.label for command in commands] == [
        "lock",
        "format",
        "lint",
        "architecture",
        "compose",
        "types",
        "tests",
        "planning-docs",
        "build",
    ]
    assert all(command.timeout_seconds > 0 for command in commands)
    assert commands[-1].argv == ("uv", "build", "--offline", "--no-sources")


@pytest.mark.parametrize(
    ("task", "expected_label"),
    [
        ("sync", "sync"),
        ("lint", "lint"),
        ("architecture", "architecture"),
        ("compose", "compose"),
        ("typecheck", "types"),
        ("test", "tests"),
        ("docs", "planning-docs"),
        ("build", "build"),
        ("pre-commit", "pre-commit"),
    ],
)
def test_single_tasks_resolve_to_allowlisted_commands(task: str, expected_label: str) -> None:
    """Each public task resolves to one fixed command without shell text."""
    commands = dev_tasks.command_specs(task)

    assert len(commands) == 1
    assert commands[0].label == expected_label
    assert isinstance(commands[0].argv, tuple)


def test_smoke_suite_is_bounded_and_does_not_weaken_the_full_gate() -> None:
    """The focused smoke command owns a folder while quality still runs every test."""
    command = dev_tasks.command_specs("test", suite="smoke")[0]

    assert command.label == "smoke-tests"
    assert command.argv[-3:] == ("pytest", "--no-cov", "tests/smoke")
    assert dev_tasks.QUALITY_COMMANDS[6].argv == ("uv", "run", "--frozen", "pytest")


def test_format_write_is_explicit() -> None:
    """Formatting defaults to check-only and mutates files only with --write."""
    check_command = dev_tasks.command_specs("format")[0]
    write_command = dev_tasks.command_specs("format", write=True)[0]

    assert "--check" in check_command.argv
    assert "--check" not in write_command.argv


def test_up_task_has_bounded_preflight_launch_and_health_sequence() -> None:
    """Runtime startup cannot bypass static validation, daemon checks, or readiness."""
    commands = dev_tasks.command_specs("up")

    assert [command.label for command in commands] == [
        "compose-contract",
        "docker-daemon",
        "runtime-up",
        "runtime-health",
    ]
    assert commands[2].argv[-4:] == ("--detach", "--wait", "--wait-timeout", "120")
    assert "--volumes" not in dev_tasks.COMPOSE_DOWN.argv


def test_status_checks_running_containers_then_health() -> None:
    """Status is read-only and uses the same observable readiness contract."""
    commands = dev_tasks.command_specs("status")

    assert [command.label for command in commands] == [
        "docker-daemon",
        "runtime-ps",
        "runtime-health",
    ]
    assert commands[1].argv[-3:] == ("ps", "--status", "running")


def test_down_checks_daemon_and_preserves_volumes() -> None:
    """Stop is allowlisted, removes orphans, and never deletes persistent data."""
    commands = dev_tasks.command_specs("down")

    assert [command.label for command in commands] == ["docker-daemon", "runtime-down"]
    assert "--remove-orphans" in commands[1].argv
    assert "--volumes" not in commands[1].argv


@pytest.mark.parametrize(
    ("task", "write", "suite", "message"),
    [
        ("lint", True, "unit", "--write is valid only"),
        ("test", False, "e2e", "not implemented yet"),
        ("unknown", False, "unit", "unknown task"),
    ],
)
def test_invalid_or_unavailable_tasks_are_rejected(
    task: str,
    write: bool,
    suite: str,
    message: str,
) -> None:
    """The runner fails closed instead of forwarding arbitrary commands."""
    with pytest.raises(dev_tasks.TaskConfigurationError, match=message):
        dev_tasks.command_specs(task, write=write, suite=suite)


def test_environment_uses_repository_local_tool_state(tmp_path: Path) -> None:
    """Tool caches do not depend on user-profile write access."""
    managed_python = tmp_path / ".python"
    managed_python.mkdir()

    environment = dev_tasks.build_environment(
        tmp_path,
        {"PATH": "test-path", "UV_PYTHON_INSTALL_DIR": "old"},
    )

    assert environment["PATH"] == "test-path"
    assert environment["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert environment["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / ".venv")
    assert environment["PRE_COMMIT_HOME"] == str(tmp_path / ".pre-commit-cache")
    assert environment["UV_PYTHON_INSTALL_DIR"] == str(managed_python)


def test_environment_removes_missing_managed_python(tmp_path: Path) -> None:
    """A stale managed-Python override is removed when the local runtime is absent."""
    environment = dev_tasks.build_environment(tmp_path, {"UV_PYTHON_INSTALL_DIR": "old"})

    assert "UV_PYTHON_INSTALL_DIR" not in environment


def monotonic_values(*values: float) -> Iterator[float]:
    """Yield deterministic monotonic clock values for task-runner tests."""
    yield from values


def test_run_commands_reports_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Successful commands emit bounded start/pass telemetry."""
    clock = monotonic_values(10.0, 10.25)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0)

    monkeypatch.setattr("agentops_incident_commander.dev_tasks.subprocess.run", fake_run)
    monkeypatch.setattr("agentops_incident_commander.dev_tasks.time.monotonic", lambda: next(clock))

    result = dev_tasks.run_commands(
        (dev_tasks.CommandSpec("demo", ("uv", "demo"), 5),),
        root=Path("."),
        environment={},
    )

    output = capsys.readouterr()
    assert result == 0
    assert "[dev] start task=demo" in output.out
    assert "[dev] passed task=demo elapsed_seconds=0.250" in output.out
    assert output.err == ""


def test_run_commands_stops_on_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A failed gate stops the sequence and preserves its exit code."""
    calls = 0

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(args=[], returncode=7)

    monkeypatch.setattr("agentops_incident_commander.dev_tasks.subprocess.run", fake_run)
    monkeypatch.setattr("agentops_incident_commander.dev_tasks.time.monotonic", lambda: 1.0)

    result = dev_tasks.run_commands(
        (
            dev_tasks.CommandSpec("first", ("uv", "first"), 5),
            dev_tasks.CommandSpec("second", ("uv", "second"), 5),
        ),
        root=Path("."),
        environment={},
    )

    output = capsys.readouterr()
    assert result == 7
    assert calls == 1
    assert "[dev] failed task=first exit_code=7" in output.err


@pytest.mark.parametrize(
    ("raised_error", "expected_code", "reason"),
    [
        (FileNotFoundError(), 127, "executable-not-found"),
        (subprocess.TimeoutExpired(cmd=("uv",), timeout=5), 124, "timeout"),
    ],
)
def test_run_commands_handles_process_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    raised_error: Exception,
    expected_code: int,
    reason: str,
) -> None:
    """Missing tools and timeouts return stable nonzero codes."""

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise raised_error

    monkeypatch.setattr("agentops_incident_commander.dev_tasks.subprocess.run", fake_run)

    result = dev_tasks.run_commands(
        (dev_tasks.CommandSpec("demo", ("missing",), 5),),
        root=Path("."),
        environment={},
    )

    output = capsys.readouterr()
    assert result == expected_code
    assert f"reason={reason}" in output.err


def test_main_reports_configuration_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Reserved suites fail before any subprocess can run."""
    result = dev_tasks.main(("test", "--suite", "e2e"))

    output = capsys.readouterr()
    assert result == 2
    assert "configuration-error" in output.err


def test_main_rejects_fault_options_for_other_tasks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Scenario and run selections cannot alter ordinary allowlisted commands."""
    assert dev_tasks.main(("lint", "--run-id", "run-abcdef123456")) == 2
    assert "fault options require the fault task" in capsys.readouterr().err


def test_main_dispatches_fault_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nested fault syntax reaches the typed controller without shell forwarding."""
    from agentops_incident_commander import faults

    captured: dict[str, object] = {}

    def fake_main(action: str, **kwargs: object) -> int:
        captured.update(action=action, **kwargs)
        return 17

    monkeypatch.setattr(faults, "main", fake_main)

    assert (
        dev_tasks.main(
            (
                "fault",
                "inject",
                "--scenario",
                "http-500",
                "--run-id",
                "run-abcdef123456",
            )
        )
        == 17
    )
    assert captured["action"] == "inject"
    assert captured["scenario"] == "http-500"
    assert captured["run_id"] == "run-abcdef123456"


def test_main_runs_resolved_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI resolves the repository and delegates an allowlisted task."""
    captured: dict[str, object] = {}

    def fake_run_commands(
        commands: tuple[dev_tasks.CommandSpec, ...],
        *,
        root: Path,
        environment: dict[str, str],
    ) -> int:
        captured["commands"] = commands
        captured["root"] = root
        captured["environment"] = environment
        return 0

    monkeypatch.setattr(dev_tasks, "run_commands", fake_run_commands)

    assert dev_tasks.main(("lint",)) == 0
    assert captured["root"] == dev_tasks.repository_root()
    assert isinstance(captured["environment"], dict)


@pytest.mark.parametrize("failed_call", [1, 2])
def test_up_failure_cleans_partial_runtime_and_preserves_original_code(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failed_call: int,
) -> None:
    """A launch/health failure cleans containers without replacing the cause code."""
    calls: list[tuple[str, ...]] = []

    def fake_run(
        commands: tuple[dev_tasks.CommandSpec, ...],
        *,
        root: Path,
        environment: dict[str, str],
    ) -> int:
        calls.append(tuple(command.label for command in commands))
        if len(calls) == failed_call:
            return 9
        if len(calls) == 3:
            return 7
        return 0

    monkeypatch.setattr(dev_tasks, "run_commands", fake_run)

    result = dev_tasks.main(("up",))

    if failed_call == 1:
        assert result == 9
        assert calls == [("compose-contract", "docker-daemon")]
    else:
        assert result == 9
        assert calls[-1] == ("runtime-down",)
        assert "runtime-cleanup exit_code=7" in capsys.readouterr().err


def test_up_success_does_not_run_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A healthy launch returns zero without invoking the stop command."""
    calls: list[tuple[str, ...]] = []

    def fake_run(
        commands: tuple[dev_tasks.CommandSpec, ...],
        *,
        root: Path,
        environment: dict[str, str],
    ) -> int:
        calls.append(tuple(command.label for command in commands))
        return 0

    monkeypatch.setattr(dev_tasks, "run_commands", fake_run)

    assert dev_tasks.main(("up",)) == 0
    assert calls == [
        ("compose-contract", "docker-daemon"),
        ("runtime-up", "runtime-health"),
    ]


def test_up_returns_launch_failure_after_successful_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful cleanup remains silent and cannot erase the launch failure code."""
    results = iter((0, 11, 0))
    monkeypatch.setattr(dev_tasks, "run_commands", lambda *args, **kwargs: next(results))

    assert dev_tasks.main(("up",)) == 11

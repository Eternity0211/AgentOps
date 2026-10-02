"""Tests for deterministic, recoverable simulator fault orchestration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest

from agentops_incident_commander import faults


def state_payload(**changes: object) -> str:
    """Build a valid serialized state with selected corruptions."""
    value: dict[str, object] = {
        "schema_version": "1.0",
        "run_id": "run-abcdef123456",
        "scenario": "http-500",
        "target_service": "order",
        "status": "active",
        "started_at": "2026-10-01T00:00:00+00:00",
    }
    value.update(changes)
    return json.dumps(value)


def test_run_id_validation_and_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run identifiers are safe for state, YAML, logs, and subprocess arguments."""
    fake_uuid = types.SimpleNamespace(hex="abcdef1234567890")
    monkeypatch.setattr(faults, "uuid4", lambda: fake_uuid)

    assert faults.validate_run_id("run-abcdef123456") == "run-abcdef123456"
    assert faults.new_run_id() == "run-abcdef123456"
    for invalid in ("short", "Upper-case", "bad_value", "x" * 65):
        with pytest.raises(faults.FaultControlError, match="run ID"):
            faults.validate_run_id(invalid)


def test_state_create_active_and_round_trip() -> None:
    """Applying and active states preserve the immutable run identity."""
    applying = faults.FaultState.create("run-abcdef123456", "redis-timeout")
    active = applying.active()
    restored = faults.FaultState.from_json(json.dumps(asdict(active)))

    assert applying.status == "applying"
    assert active.status == "active"
    assert active.target_service == "inventory"
    assert restored == active


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "invalid JSON"),
        ("[]", "invalid schema"),
        (json.dumps({"scenario": "http-500"}), "invalid schema"),
        (state_payload(scenario="unknown"), "unknown scenario"),
        (state_payload(run_id="BAD"), "run ID"),
        (state_payload(target_service="payment"), "target does not match"),
        (state_payload(schema_version="2.0"), "unsupported"),
        (state_payload(status="finished"), "status is invalid"),
        (state_payload(started_at="not-time"), "timestamp is invalid"),
    ],
)
def test_state_rejects_corruption(payload: str, message: str) -> None:
    """Tampered local state cannot select a target or transition."""
    with pytest.raises(faults.FaultControlError, match=message):
        faults.FaultState.from_json(payload)


def test_overlay_and_compose_commands_are_bounded(tmp_path: Path) -> None:
    """Generated YAML and Compose mutations contain only validated fixed fields."""
    state = faults.FaultState.from_json(state_payload())
    overlay = tmp_path / "data/runtime/fault.override.yaml"

    content = faults._overlay(state)
    apply_command = faults._compose_apply(tmp_path, overlay, "order")
    reset_command = faults._compose_reset(tmp_path, "order")

    assert 'SIMULATOR_FAULT_SCENARIO: "http-500"' in content
    assert 'SIMULATOR_FAULT_RUN_ID: "run-abcdef123456"' in content
    assert 'SERVICE_VERSION: "2.0.0"' in content
    assert 'PREVIOUS_SERVICE_VERSION: "1.0.0"' in content
    assert "fault-http-500" not in content
    assert apply_command[-3:] == ("--no-deps", "--force-recreate", "order")
    assert str(overlay) in apply_command
    assert str(overlay) not in reset_command
    assert reset_command[-1] == "order"


def test_pool_exhaustion_overlay_preserves_baseline_deployment() -> None:
    """A resource fault must not create a false version-change explanation."""
    state = faults.FaultState.create("run-abcdef123456", "db-pool-exhaustion")

    content = faults._overlay(state)

    assert 'SIMULATOR_FAULT_SCENARIO: "db-pool-exhaustion"' in content
    assert 'SIMULATOR_FAULT_RUN_ID: "run-abcdef123456"' in content
    assert "SERVICE_VERSION" not in content
    assert "PREVIOUS_SERVICE_VERSION" not in content
    assert "DEPLOYMENT_ID" not in content


@pytest.mark.parametrize(
    ("effect", "expected"),
    [
        (subprocess.CompletedProcess([], 7), 7),
        (FileNotFoundError(), 127),
        (subprocess.TimeoutExpired(cmd=("docker",), timeout=180), 124),
    ],
)
def test_subprocess_runner_maps_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    effect: subprocess.CompletedProcess[str] | Exception,
    expected: int,
) -> None:
    """Compose execution has stable codes for process, missing binary, and timeout paths."""

    def run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if isinstance(effect, Exception):
            raise effect
        return effect

    monkeypatch.setattr("agentops_incident_commander.faults.subprocess.run", run)

    assert faults.subprocess_runner(("docker",), tmp_path, {}) == expected


def test_inject_success_is_recoverable_and_idempotent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A successful apply records active state and the identical replay is a no-op."""
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], root: Path, environment: Any) -> int:
        calls.append(argv)
        return 0

    result = faults.inject(
        "http-500",
        root=tmp_path,
        environment={},
        run_id="run-abcdef123456",
        runner=runner,
    )
    replay = faults.inject(
        "http-500",
        root=tmp_path,
        environment={},
        run_id="run-abcdef123456",
        runner=runner,
    )

    state_path, overlay_path, _ = faults._paths(tmp_path)
    state = faults.FaultState.from_json(state_path.read_text(encoding="utf-8"))
    assert result == replay == 0
    assert state.status == "active"
    assert overlay_path.exists()
    assert len(calls) == 1
    assert "active run_id=run-abcdef123456" in capsys.readouterr().out


def test_inject_refuses_second_active_fault(tmp_path: Path) -> None:
    """Only one fault may own the simulator at a time."""
    assert (
        faults.inject(
            "http-500",
            root=tmp_path,
            environment={},
            run_id="run-abcdef123456",
            runner=lambda argv, root, environment: 0,
        )
        == 0
    )

    with pytest.raises(faults.FaultControlError, match="cleaned first"):
        faults.inject(
            "memory-leak",
            root=tmp_path,
            environment={},
            run_id="run-123456abcdef",
            runner=lambda argv, root, environment: 0,
        )


def test_failed_injection_removes_unapplied_state(tmp_path: Path) -> None:
    """A failed Compose apply leaves no false active marker or reusable overlay."""
    result = faults.inject(
        "bad-configuration",
        root=tmp_path,
        environment={},
        run_id="run-abcdef123456",
        runner=lambda argv, root, environment: 19,
    )

    state_path, overlay_path, _ = faults._paths(tmp_path)
    assert result == 19
    assert not state_path.exists()
    assert not overlay_path.exists()


def test_clean_restores_baseline_and_is_repeatable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cleanup recreates from base Compose and a subsequent cleanup is a no-op."""
    calls: list[tuple[str, ...]] = []

    def runner(argv: tuple[str, ...], root: Path, environment: Any) -> int:
        calls.append(argv)
        return 0

    faults.inject(
        "downstream-latency",
        root=tmp_path,
        environment={},
        run_id="run-abcdef123456",
        runner=runner,
    )
    assert (
        faults.clean(
            root=tmp_path,
            environment={},
            run_id="run-abcdef123456",
            runner=runner,
        )
        == 0
    )
    assert faults.clean(root=tmp_path, environment={}, runner=runner) == 0

    state_path, overlay_path, _ = faults._paths(tmp_path)
    assert not state_path.exists()
    assert not overlay_path.exists()
    assert len(calls) == 2
    assert str(overlay_path) not in calls[-1]
    assert "clean no-active-fault" in capsys.readouterr().out


def test_clean_refuses_wrong_run_and_retains_state_on_failure(tmp_path: Path) -> None:
    """Cleanup cannot target another run and failed restore remains retryable."""
    faults.inject(
        "memory-leak",
        root=tmp_path,
        environment={},
        run_id="run-abcdef123456",
        runner=lambda argv, root, environment: 0,
    )
    with pytest.raises(faults.FaultControlError, match="does not match"):
        faults.clean(
            root=tmp_path,
            environment={},
            run_id="run-123456abcdef",
            runner=lambda argv, root, environment: 0,
        )

    assert (
        faults.clean(
            root=tmp_path,
            environment={},
            runner=lambda argv, root, environment: 23,
        )
        == 23
    )
    state_path, overlay_path, _ = faults._paths(tmp_path)
    assert state_path.exists()
    assert overlay_path.exists()


def test_read_state_maps_file_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unreadable recovery state fails closed."""
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    with pytest.raises(faults.FaultControlError, match="cannot be read"):
        faults._read_state(state_path)


def test_lock_contention_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A concurrent Windows operation receives a stable refusal."""
    if os.name != "nt":
        pytest.skip("Windows locking branch")
    import msvcrt

    monkeypatch.setattr(msvcrt, "locking", lambda *args: (_ for _ in ()).throw(OSError()))

    with (
        pytest.raises(faults.FaultControlError, match="in progress"),
        faults._exclusive_lock(tmp_path / "lock"),
    ):
        pass


def test_posix_lock_and_contention_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The POSIX advisory-lock implementation acquires, releases, and maps contention."""
    fake = types.ModuleType("fcntl")
    fake.LOCK_EX = 1  # type: ignore[attr-defined]
    fake.LOCK_NB = 2  # type: ignore[attr-defined]
    fake.LOCK_UN = 4  # type: ignore[attr-defined]
    calls: list[int] = []
    fake.flock = lambda descriptor, operation: calls.append(operation)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "fcntl", fake)
    monkeypatch.setattr("agentops_incident_commander.faults.os.name", "posix")

    with faults._exclusive_lock(tmp_path / "lock"):
        pass
    assert calls == [3, 4]

    fake.flock = lambda *args: (_ for _ in ()).throw(OSError())  # type: ignore[attr-defined]
    with (
        pytest.raises(faults.FaultControlError, match="in progress"),
        faults._exclusive_lock(tmp_path / "lock"),
    ):
        pass


@pytest.mark.parametrize(
    ("action", "scenario", "expected"),
    [
        ("inject", None, "known --scenario"),
        ("inject", "unknown", "known --scenario"),
        ("clean", "http-500", "does not accept"),
        ("unknown", None, "inject or clean"),
    ],
)
def test_main_rejects_invalid_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    action: str,
    scenario: str | None,
    expected: str,
) -> None:
    """CLI validation returns two before any Compose mutation."""
    assert faults.main(action, scenario=scenario, run_id=None, root=tmp_path, environment={}) == 2
    assert expected in capsys.readouterr().err


def test_main_rejects_known_but_unimplemented_scenario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Registry membership cannot precede the scenario's symptom implementation."""
    monkeypatch.setattr(faults, "IMPLEMENTED_SCENARIOS", frozenset())

    assert (
        faults.main(
            "inject",
            scenario="http-500",
            run_id="run-abcdef123456",
            root=tmp_path,
            environment={},
        )
        == 2
    )
    assert "not implemented yet" in capsys.readouterr().err


def test_main_dispatches_inject_and_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validated actions dispatch to their deterministic controller functions."""
    calls: list[str] = []

    def inject(scenario: str, **kwargs: object) -> int:
        calls.append(f"inject:{scenario}")
        return 0

    def clean(**kwargs: object) -> int:
        calls.append("clean")
        return 0

    monkeypatch.setattr(
        faults,
        "inject",
        inject,
    )
    monkeypatch.setattr(
        faults,
        "clean",
        clean,
    )
    monkeypatch.setattr(faults, "IMPLEMENTED_SCENARIOS", frozenset({"http-500"}))

    assert (
        faults.main(
            "inject",
            scenario="http-500",
            run_id="run-abcdef123456",
            root=tmp_path,
            environment={},
        )
        == 0
    )
    assert faults.main("clean", scenario=None, run_id=None, root=tmp_path, environment={}) == 0
    assert calls == ["inject:http-500", "clean"]

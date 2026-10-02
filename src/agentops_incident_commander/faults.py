"""Cross-platform, stateful orchestration for deterministic simulator faults."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

ScenarioName = Literal[
    "http-500",
    "db-pool-exhaustion",
    "redis-timeout",
    "downstream-latency",
    "memory-leak",
    "bad-configuration",
]
FaultStatus = Literal["applying", "active"]
Runner = Callable[[tuple[str, ...], Path, Mapping[str, str]], int]

SCENARIO_TARGETS: dict[ScenarioName, str] = {
    "http-500": "order",
    "db-pool-exhaustion": "order",
    "redis-timeout": "inventory",
    "downstream-latency": "payment",
    "memory-leak": "order",
    "bad-configuration": "payment",
}
IMPLEMENTED_SCENARIOS: frozenset[ScenarioName] = frozenset(
    {"http-500", "db-pool-exhaustion", "redis-timeout", "downstream-latency"}
)
RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{5,63}$")
STATE_SCHEMA_VERSION = "1.0"
RUNTIME_DIRECTORY = Path("data/runtime")
STATE_FILENAME = "fault-state.json"
OVERLAY_FILENAME = "fault.override.yaml"
LOCK_FILENAME = "fault.lock"
COMPOSE_PROFILES = ("--profile", "simulator", "--profile", "observability")


class FaultControlError(RuntimeError):
    """A requested fault transition is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class FaultState:
    """Versioned local record for one active or partially applied fault."""

    schema_version: str
    run_id: str
    scenario: ScenarioName
    target_service: str
    status: FaultStatus
    started_at: str

    @classmethod
    def create(cls, run_id: str, scenario: ScenarioName) -> FaultState:
        return cls(
            schema_version=STATE_SCHEMA_VERSION,
            run_id=validate_run_id(run_id),
            scenario=scenario,
            target_service=SCENARIO_TARGETS[scenario],
            status="applying",
            started_at=datetime.now(UTC).isoformat(),
        )

    @classmethod
    def from_json(cls, payload: str) -> FaultState:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as error:
            raise FaultControlError("fault state is invalid JSON") from error
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "run_id",
            "scenario",
            "target_service",
            "status",
            "started_at",
        }:
            raise FaultControlError("fault state has an invalid schema")
        scenario_value = value["scenario"]
        if scenario_value not in SCENARIO_TARGETS:
            raise FaultControlError("fault state has an unknown scenario")
        scenario = cast(ScenarioName, scenario_value)
        run_id = validate_run_id(str(value["run_id"]))
        target = SCENARIO_TARGETS[scenario]
        if value["target_service"] != target:
            raise FaultControlError("fault state target does not match scenario")
        if value["schema_version"] != STATE_SCHEMA_VERSION:
            raise FaultControlError("fault state schema version is unsupported")
        if value["status"] not in {"applying", "active"}:
            raise FaultControlError("fault state status is invalid")
        try:
            datetime.fromisoformat(str(value["started_at"]))
        except ValueError as error:
            raise FaultControlError("fault state timestamp is invalid") from error
        return cls(
            schema_version=STATE_SCHEMA_VERSION,
            run_id=run_id,
            scenario=scenario,
            target_service=target,
            status=cast(FaultStatus, value["status"]),
            started_at=str(value["started_at"]),
        )

    def active(self) -> FaultState:
        """Return the same immutable state after successful fault application."""
        return FaultState(**{**asdict(self), "status": "active"})


def validate_run_id(run_id: str) -> str:
    """Reject free-form identifiers before they reach files, YAML, or subprocesses."""
    if RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise FaultControlError("run ID must match [a-z0-9][a-z0-9-]{5,63}")
    return run_id


def new_run_id() -> str:
    """Generate a short opaque identifier suitable for local correlation."""
    return f"run-{uuid4().hex[:12]}"


def _paths(root: Path) -> tuple[Path, Path, Path]:
    directory = root / RUNTIME_DIRECTORY
    return directory / STATE_FILENAME, directory / OVERLAY_FILENAME, directory / LOCK_FILENAME


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Hold a one-byte advisory lock using the host's standard-library primitive."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise FaultControlError("another fault operation is in progress") from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
            except OSError as error:
                raise FaultControlError("another fault operation is in progress") from error
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _write_state(path: Path, state: FaultState) -> None:
    _atomic_write(path, json.dumps(asdict(state), indent=2, sort_keys=True) + "\n")


def _read_state(path: Path) -> FaultState | None:
    if not path.exists():
        return None
    try:
        payload = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise FaultControlError("fault state cannot be read") from error
    return FaultState.from_json(payload)


def _overlay(state: FaultState) -> str:
    content = (
        "services:\n"
        f"  {state.target_service}:\n"
        "    environment:\n"
        f'      SIMULATOR_FAULT_SCENARIO: "{state.scenario}"\n'
        f'      SIMULATOR_FAULT_RUN_ID: "{state.run_id}"\n'
    )
    if state.scenario == "http-500":
        content += (
            '      SERVICE_VERSION: "2.0.0"\n'
            '      PREVIOUS_SERVICE_VERSION: "1.0.0"\n'
            f'      DEPLOYMENT_ID: "{state.run_id}"\n'
        )
    return content


def _compose_apply(root: Path, overlay: Path, target: str) -> tuple[str, ...]:
    return (
        "docker",
        "compose",
        "-f",
        str(root / "compose.yaml"),
        "-f",
        str(overlay),
        *COMPOSE_PROFILES,
        "up",
        "--detach",
        "--no-deps",
        "--force-recreate",
        target,
    )


def _compose_reset(root: Path, target: str) -> tuple[str, ...]:
    return (
        "docker",
        "compose",
        "-f",
        str(root / "compose.yaml"),
        *COMPOSE_PROFILES,
        "up",
        "--detach",
        "--no-deps",
        "--force-recreate",
        target,
    )


def subprocess_runner(argv: tuple[str, ...], root: Path, environment: Mapping[str, str]) -> int:
    """Run one allowlisted Compose mutation with a fixed upper bound."""
    try:
        result = subprocess.run(
            argv,
            cwd=root,
            env=environment,
            check=False,
            timeout=180,
        )
    except FileNotFoundError:
        return 127
    except subprocess.TimeoutExpired:
        return 124
    return result.returncode


def inject(
    scenario: ScenarioName,
    *,
    root: Path,
    environment: Mapping[str, str],
    run_id: str | None = None,
    runner: Runner = subprocess_runner,
) -> int:
    """Apply one fault overlay, recording recoverable state around the mutation."""
    selected_run_id = validate_run_id(run_id) if run_id is not None else new_run_id()
    state_path, overlay_path, lock_path = _paths(root)
    with _exclusive_lock(lock_path):
        existing = _read_state(state_path)
        if existing is not None:
            if existing.run_id == selected_run_id and existing.scenario == scenario:
                print(
                    f"[fault] already-active run_id={existing.run_id} scenario={existing.scenario} "
                    f"status={existing.status}",
                    flush=True,
                )
                return 0
            raise FaultControlError(
                f"active fault must be cleaned first (run_id={existing.run_id})"
            )

        state = FaultState.create(selected_run_id, scenario)
        _atomic_write(overlay_path, _overlay(state))
        _write_state(state_path, state)
        result = runner(_compose_apply(root, overlay_path, state.target_service), root, environment)
        if result != 0:
            state_path.unlink(missing_ok=True)
            overlay_path.unlink(missing_ok=True)
            return result
        active = state.active()
        _write_state(state_path, active)
        print(
            f"[fault] active run_id={active.run_id} scenario={active.scenario} "
            f"target={active.target_service}",
            flush=True,
        )
        return 0


def clean(
    *,
    root: Path,
    environment: Mapping[str, str],
    run_id: str | None = None,
    runner: Runner = subprocess_runner,
) -> int:
    """Restore the baseline target; repeated cleanup without state is a safe no-op."""
    expected_run_id = validate_run_id(run_id) if run_id is not None else None
    state_path, overlay_path, lock_path = _paths(root)
    with _exclusive_lock(lock_path):
        state = _read_state(state_path)
        if state is None:
            overlay_path.unlink(missing_ok=True)
            print("[fault] clean no-active-fault", flush=True)
            return 0
        if expected_run_id is not None and state.run_id != expected_run_id:
            raise FaultControlError(f"run ID does not match active fault (active={state.run_id})")
        result = runner(_compose_reset(root, state.target_service), root, environment)
        if result != 0:
            return result
        state_path.unlink(missing_ok=True)
        overlay_path.unlink(missing_ok=True)
        print(
            f"[fault] cleaned run_id={state.run_id} scenario={state.scenario} ",
            f"target={state.target_service}",
            flush=True,
        )
        return 0


def main(
    action: str,
    *,
    scenario: str | None,
    run_id: str | None,
    root: Path,
    environment: Mapping[str, str],
) -> int:
    """Validate CLI selections and execute one deterministic fault transition."""
    try:
        if action == "inject":
            if scenario not in SCENARIO_TARGETS:
                raise FaultControlError("inject requires a known --scenario")
            if scenario not in IMPLEMENTED_SCENARIOS:
                raise FaultControlError(f"scenario is not implemented yet: {scenario}")
            return inject(
                scenario,
                root=root,
                environment=environment,
                run_id=run_id,
            )
        if action == "clean":
            if scenario is not None:
                raise FaultControlError("clean does not accept --scenario")
            return clean(root=root, environment=environment, run_id=run_id)
        raise FaultControlError("fault action must be inject or clean")
    except FaultControlError as error:
        print(f"[fault] configuration-error reason={error}", file=sys.stderr, flush=True)
        return 2

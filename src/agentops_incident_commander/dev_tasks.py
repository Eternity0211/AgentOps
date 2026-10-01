"""Cross-platform development task runner with a fixed command allowlist."""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One bounded developer command executed without a shell."""

    label: str
    argv: tuple[str, ...]
    timeout_seconds: int


class TaskConfigurationError(ValueError):
    """Raised when a requested task is known but not currently available."""


QUALITY_COMMANDS = (
    CommandSpec("lock", ("uv", "lock", "--check"), 60),
    CommandSpec("format", ("uv", "run", "--frozen", "ruff", "format", "--check", "."), 60),
    CommandSpec("lint", ("uv", "run", "--frozen", "ruff", "check", "."), 60),
    CommandSpec("types", ("uv", "run", "--frozen", "mypy", "src", "scripts", "tests"), 120),
    CommandSpec("tests", ("uv", "run", "--frozen", "pytest"), 120),
    CommandSpec(
        "planning-docs",
        ("pwsh", "-NoProfile", "-File", "scripts/check_planning_docs.ps1"),
        60,
    ),
    CommandSpec("build", ("uv", "build", "--offline", "--no-sources"), 120),
)


def repository_root() -> Path:
    """Return the repository root for the editable or source checkout."""
    return Path(__file__).resolve().parents[2]


def build_environment(root: Path, source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a deterministic environment that keeps tool caches inside ignored paths."""
    environment = dict(os.environ if source is None else source)
    environment["UV_CACHE_DIR"] = str(root / ".uv-cache")
    environment["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
    environment["PRE_COMMIT_HOME"] = str(root / ".pre-commit-cache")

    managed_python = root / ".python"
    if managed_python.is_dir():
        environment["UV_PYTHON_INSTALL_DIR"] = str(managed_python)
    else:
        environment.pop("UV_PYTHON_INSTALL_DIR", None)

    return environment


def command_specs(
    task: str, *, write: bool = False, suite: str = "unit"
) -> tuple[CommandSpec, ...]:
    """Resolve one public task into an immutable, allowlisted command sequence."""
    if write and task != "format":
        raise TaskConfigurationError("--write is valid only for the format task")

    if task == "quality":
        return QUALITY_COMMANDS
    if task == "sync":
        return (CommandSpec("sync", ("uv", "sync", "--frozen", "--all-groups"), 120),)
    if task == "format":
        format_args: tuple[str, ...] = ("uv", "run", "--frozen", "ruff", "format")
        if not write:
            format_args += ("--check",)
        return (CommandSpec("format", (*format_args, "."), 60),)
    if task == "lint":
        return (CommandSpec("lint", ("uv", "run", "--frozen", "ruff", "check", "."), 60),)
    if task == "typecheck":
        return (
            CommandSpec(
                "types",
                ("uv", "run", "--frozen", "mypy", "src", "scripts", "tests"),
                120,
            ),
        )
    if task == "test":
        if suite != "unit":
            raise TaskConfigurationError(
                f"test suite '{suite}' is not implemented yet; available suite: unit"
            )
        return (CommandSpec("tests", ("uv", "run", "--frozen", "pytest"), 120),)
    if task == "docs":
        return (
            CommandSpec(
                "planning-docs",
                ("pwsh", "-NoProfile", "-File", "scripts/check_planning_docs.ps1"),
                60,
            ),
        )
    if task == "build":
        return (CommandSpec("build", ("uv", "build", "--offline", "--no-sources"), 120),)
    if task == "pre-commit":
        return (
            CommandSpec(
                "pre-commit",
                ("uv", "run", "--frozen", "pre-commit", "run", "--all-files"),
                180,
            ),
        )
    raise TaskConfigurationError(f"unknown task: {task}")


def run_commands(
    commands: Sequence[CommandSpec],
    *,
    root: Path,
    environment: Mapping[str, str],
) -> int:
    """Run commands sequentially, stopping at the first failure or timeout."""
    for command in commands:
        rendered_command = shlex.join(command.argv)
        print(f"[dev] start task={command.label} command={rendered_command}", flush=True)
        started_at = time.monotonic()
        try:
            result = subprocess.run(
                command.argv,
                cwd=root,
                env=environment,
                check=False,
                timeout=command.timeout_seconds,
            )
        except FileNotFoundError:
            print(
                f"[dev] error task={command.label} reason=executable-not-found "
                f"executable={command.argv[0]}",
                file=sys.stderr,
                flush=True,
            )
            return 127
        except subprocess.TimeoutExpired:
            print(
                f"[dev] error task={command.label} reason=timeout "
                f"timeout_seconds={command.timeout_seconds}",
                file=sys.stderr,
                flush=True,
            )
            return 124

        elapsed_seconds = time.monotonic() - started_at
        if result.returncode != 0:
            print(
                f"[dev] failed task={command.label} exit_code={result.returncode} "
                f"elapsed_seconds={elapsed_seconds:.3f}",
                file=sys.stderr,
                flush=True,
            )
            return result.returncode

        print(
            f"[dev] passed task={command.label} elapsed_seconds={elapsed_seconds:.3f}",
            flush=True,
        )

    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "task",
        choices=(
            "quality",
            "sync",
            "format",
            "lint",
            "typecheck",
            "test",
            "docs",
            "build",
            "pre-commit",
        ),
    )
    parser.add_argument("--write", action="store_true", help="Apply formatting changes.")
    parser.add_argument(
        "--suite",
        choices=("unit", "e2e"),
        default="unit",
        help="Test suite to run; e2e is reserved until its phase is implemented.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one allowlisted developer task."""
    arguments = build_parser().parse_args(argv)
    try:
        commands = command_specs(arguments.task, write=arguments.write, suite=arguments.suite)
    except TaskConfigurationError as error:
        print(f"[dev] configuration-error reason={error}", file=sys.stderr, flush=True)
        return 2

    root = repository_root()
    return run_commands(commands, root=root, environment=build_environment(root))

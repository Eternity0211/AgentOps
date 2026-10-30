"""Tests for read-only local Compose prerequisite diagnostics."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from agentops_incident_commander import runtime_prerequisites


def configured_environment(tmp_path: Path) -> dict[str, str]:
    """Create four bounded local secret files and return their settings."""
    environment: dict[str, str] = {}
    for index, name in enumerate(runtime_prerequisites.REQUIRED_SECRET_SETTINGS):
        path = tmp_path / f"secret-{index}.txt"
        path.write_text(f"local-only-{index}\n", encoding="utf-8")
        environment[name] = str(path)
    return environment


def test_required_secret_paths_accept_environment_overrides(tmp_path: Path) -> None:
    environment = configured_environment(tmp_path)

    paths = runtime_prerequisites.required_secret_paths(tmp_path, environment)

    assert len(paths) == 4
    assert all(path.is_absolute() for path in paths)


def test_required_secret_paths_default_to_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = configured_environment(tmp_path)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)

    assert len(runtime_prerequisites.required_secret_paths(tmp_path)) == 4


def test_required_secret_paths_read_relative_dotenv_paths(tmp_path: Path) -> None:
    lines: list[str] = []
    for index, name in enumerate(runtime_prerequisites.REQUIRED_SECRET_SETTINGS):
        path = tmp_path / f"secret-{index}.txt"
        path.write_text("local-only\n", encoding="utf-8")
        lines.append(f"{name}={path.name}")
    (tmp_path / ".env").write_text("\n".join(lines), encoding="utf-8")

    paths = runtime_prerequisites.required_secret_paths(tmp_path, {})

    assert paths == tuple((tmp_path / f"secret-{index}.txt").resolve() for index in range(4))


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda root: {}, "missing CONTROL_DB_PASSWORD_FILE"),
        (
            lambda root: {
                name: str(root / "missing")
                for name in runtime_prerequisites.REQUIRED_SECRET_SETTINGS
            },
            "secret file missing",
        ),
        (
            lambda root: _environment_with_payload(root, b""),
            "secret file is empty",
        ),
        (
            lambda root: _environment_with_payload(
                root, b"x" * (runtime_prerequisites.MAX_SECRET_BYTES + 1)
            ),
            "exceeds the 4096-byte limit",
        ),
    ],
)
def test_required_secret_paths_fail_with_actionable_reason(
    tmp_path: Path,
    setup: Callable[[Path], dict[str, str]],
    message: str,
) -> None:
    environment = setup(tmp_path)

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match=message):
        runtime_prerequisites.required_secret_paths(tmp_path, environment)


def _environment_with_payload(root: Path, payload: bytes) -> dict[str, str]:
    environment = configured_environment(root)
    first = Path(environment[runtime_prerequisites.REQUIRED_SECRET_SETTINGS[0]])
    first.write_bytes(payload)
    return environment


def test_dotenv_is_bounded_and_rejects_quoted_required_paths(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text('CONTROL_DB_PASSWORD_FILE="secret.txt"\n', encoding="utf-8")
    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="invalid unquoted"):
        runtime_prerequisites.required_secret_paths(tmp_path, {})

    (tmp_path / ".env").write_text("x" * 65_537, encoding="utf-8")
    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="65536-byte"):
        runtime_prerequisites.required_secret_paths(tmp_path, {})


@pytest.mark.parametrize("value", ["", " path", "path ", "'path'", 'path"'])
def test_dotenv_rejects_empty_spaced_or_quoted_required_paths(tmp_path: Path, value: str) -> None:
    (tmp_path / ".env").write_text(f"CONTROL_DB_PASSWORD_FILE={value}\n", encoding="utf-8")

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="invalid unquoted"):
        runtime_prerequisites.required_secret_paths(tmp_path, {})


def test_dotenv_ignores_comments_malformed_lines_and_unrelated_settings(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("\n# comment\nmalformed\nUNRELATED=value\n", encoding="utf-8")

    assert runtime_prerequisites._dotenv_settings(tmp_path) == {}


def test_dotenv_rejects_spaced_required_setting_name(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(" CONTROL_DB_PASSWORD_FILE=secret.txt\n", encoding="utf-8")

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="invalid unquoted"):
        runtime_prerequisites.required_secret_paths(tmp_path, {})


def test_dotenv_reports_unreadable_utf8(tmp_path: Path) -> None:
    (tmp_path / ".env").write_bytes(b"\xff")

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="cannot be read"):
        runtime_prerequisites.required_secret_paths(tmp_path, {})


def test_secret_path_must_be_a_readable_regular_file(tmp_path: Path) -> None:
    environment = configured_environment(tmp_path)
    environment[runtime_prerequisites.REQUIRED_SECRET_SETTINGS[0]] = str(tmp_path)

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match="unreadable"):
        runtime_prerequisites.required_secret_paths(tmp_path, environment)


def test_validate_requires_python_312(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 13, 0))

    with pytest.raises(runtime_prerequisites.RuntimePrerequisiteError, match=r"Python 3\.12"):
        runtime_prerequisites.validate(tmp_path, {})


def test_validate_accepts_python_312_and_valid_secrets(tmp_path: Path) -> None:
    environment = configured_environment(tmp_path)

    assert len(runtime_prerequisites.validate(tmp_path, environment)) == 4


def test_main_reports_success_failure_and_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(runtime_prerequisites, "validate", lambda root: (root,) * 4)
    assert runtime_prerequisites.main() == 0
    assert "secret_files=4" in capsys.readouterr().out

    monkeypatch.setattr(
        runtime_prerequisites,
        "validate",
        lambda root: (_ for _ in ()).throw(
            runtime_prerequisites.RuntimePrerequisiteError("missing")
        ),
    )
    assert runtime_prerequisites.main() == 1
    assert "reason=missing" in capsys.readouterr().err

    assert runtime_prerequisites.main(("unexpected",)) == 2
    assert "unexpected arguments" in capsys.readouterr().err

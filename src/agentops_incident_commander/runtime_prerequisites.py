"""Read-only local prerequisite checks for the Compose development runtime."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

MAX_DOTENV_BYTES = 65_536
MAX_SECRET_BYTES = 4_096
REQUIRED_SECRET_SETTINGS = (
    "CONTROL_DB_PASSWORD_FILE",
    "SIMULATOR_DB_PASSWORD_FILE",
    "SIMULATOR_REDIS_PASSWORD_FILE",
    "GRAFANA_ADMIN_PASSWORD_FILE",
)


class RuntimePrerequisiteError(RuntimeError):
    """A local runtime prerequisite is missing or unsafe to consume."""


def _dotenv_settings(root: Path) -> dict[str, str]:
    """Read only required secret-path settings from the local Compose dotenv file."""
    path = root / ".env"
    if not path.is_file():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise RuntimePrerequisiteError(".env cannot be read as UTF-8") from error
    if len(content.encode("utf-8")) > MAX_DOTENV_BYTES:
        raise RuntimePrerequisiteError(".env exceeds the 65536-byte limit")

    selected: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        raw_name, value = line.split("=", 1)
        name = raw_name.strip()
        if name in REQUIRED_SECRET_SETTINGS:
            if (
                raw_name != name
                or not value
                or value != value.strip()
                or any(mark in value for mark in ('"', "'"))
            ):
                raise RuntimePrerequisiteError(f"invalid unquoted path setting: {name}")
            selected[name] = value
    return selected


def required_secret_paths(
    root: Path, environment: Mapping[str, str] | None = None
) -> tuple[Path, ...]:
    """Resolve and validate each required local secret without exposing its content."""
    source = os.environ if environment is None else environment
    settings = _dotenv_settings(root)
    settings.update((name, source[name]) for name in REQUIRED_SECRET_SETTINGS if source.get(name))

    paths: list[Path] = []
    for name in REQUIRED_SECRET_SETTINGS:
        configured = settings.get(name)
        if not configured:
            raise RuntimePrerequisiteError(
                f"missing {name}; copy .env.example to .env and set the local secret path"
            )
        candidate = Path(configured)
        path = candidate if candidate.is_absolute() else root / candidate
        try:
            payload = path.read_bytes()
        except FileNotFoundError as error:
            raise RuntimePrerequisiteError(f"secret file missing for {name}: {path}") from error
        except OSError as error:
            raise RuntimePrerequisiteError(f"secret file unreadable for {name}: {path}") from error
        if not payload.strip():
            raise RuntimePrerequisiteError(f"secret file is empty for {name}: {path}")
        if len(payload) > MAX_SECRET_BYTES:
            raise RuntimePrerequisiteError(
                f"secret file exceeds the 4096-byte limit for {name}: {path}"
            )
        paths.append(path.resolve())
    return tuple(paths)


def validate(root: Path, environment: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Validate the fixed Python and local-secret prerequisites."""
    if sys.version_info[:2] != (3, 12):
        raise RuntimePrerequisiteError(
            "Python 3.12 is required; run the task through the locked project environment"
        )
    return required_secret_paths(root, environment)


def main(argv: Sequence[str] | None = None) -> int:
    """Expose stable process codes and diagnostics for the developer task runner."""
    if argv:
        print("[doctor] configuration-error reason=unexpected arguments", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[2]
    try:
        secrets = validate(root)
    except RuntimePrerequisiteError as error:
        print(f"[doctor] failed reason={error}", file=sys.stderr, flush=True)
        return 1
    print(
        f"[doctor] passed python={sys.version_info.major}.{sys.version_info.minor} "
        f"secret_files={len(secrets)}",
        flush=True,
    )
    return 0

"""Fail-closed validation for repository supply-chain and container controls."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

IMAGE_DIGEST = re.compile(r"^[^@\s]+:[^@\s]+@sha256:[0-9a-f]{64}$")
ACTION_SHA = re.compile(r"^[0-9a-f]{40}$")
NUMERIC_USER = re.compile(r"^USER\s+[1-9][0-9]*:[1-9][0-9]*\s*$", re.MULTILINE)
ACTION_USE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
LOCK_FILES = (
    "uv.lock",
    "console/package-lock.json",
)
DOCKERFILES = (
    "Dockerfile.simulator",
    "Dockerfile.evaluator",
)
COMPOSE_FILES = (
    "compose.yaml",
    "compose.evaluation.yaml",
)


def repository_root() -> Path:
    """Return the repository root for the source checkout."""
    return Path(__file__).resolve().parents[2]


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        return error


def _validate_compose(path: Path) -> list[str]:
    violations: list[str] = []
    document = _load_yaml(path)
    if isinstance(document, Exception):
        return [f"{path.name} must be readable valid YAML"]
    if not isinstance(document, Mapping) or not isinstance(document.get("services"), Mapping):
        return [f"{path.name} services must be an object"]

    for name, service in sorted(document["services"].items()):
        if not isinstance(service, Mapping):
            violations.append(f"{path.name} service {name} must be an object")
            continue
        image = service.get("image")
        is_built = "build" in service
        if not isinstance(image, str):
            violations.append(f"{path.name} service {name} must declare an image")
        elif is_built:
            if "@" in image or ":" not in image or image.endswith(":latest"):
                violations.append(
                    f"{path.name} built service {name} must use an explicit local image tag"
                )
        elif IMAGE_DIGEST.fullmatch(image) is None:
            violations.append(f"{path.name} external service {name} must pin tag and sha256 digest")
        if is_built and service.get("cap_drop") != ["ALL"]:
            violations.append(f"{path.name} built service {name} must drop all capabilities")
        if service.get("privileged") is True:
            violations.append(f"{path.name} service {name} must not be privileged")
        if service.get("read_only") is not True:
            violations.append(f"{path.name} service {name} must use a read-only root filesystem")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            violations.append(f"{path.name} service {name} must disable privilege escalation")
        if "/var/run/docker.sock" in json.dumps(service.get("volumes", []), sort_keys=True):
            violations.append(f"{path.name} service {name} must not mount the Docker socket")
    return violations


def _validate_dockerfile(path: Path) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return [f"{path.name} must be readable"]
    violations: list[str] = []
    from_lines = [line.strip() for line in content.splitlines() if line.startswith("FROM ")]
    if len(from_lines) != 1 or IMAGE_DIGEST.fullmatch(from_lines[0].removeprefix("FROM ")) is None:
        violations.append(f"{path.name} must pin one tagged base image by sha256 digest")
    user_lines = [line.strip() for line in content.splitlines() if line.startswith("USER ")]
    if len(user_lines) != 1 or NUMERIC_USER.fullmatch(user_lines[0]) is None:
        violations.append(f"{path.name} must declare one non-root numeric UID:GID")
    if "openssl=" not in content or "libpcre2-8-0=" not in content:
        violations.append(f"{path.name} must install reviewed fixed OS security packages")
    return violations


def _validate_workflows(root: Path) -> list[str]:
    violations: list[str] = []
    workflow_files = sorted((root / ".github" / "workflows").glob("*.yml"))
    if not workflow_files:
        return ["repository must contain GitHub Actions workflows"]
    for path in workflow_files:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            violations.append(f"workflow {path.name} must be readable")
            continue
        for use in ACTION_USE.findall(content):
            if use.startswith("./"):
                continue
            _, separator, revision = use.rpartition("@")
            if not separator or ACTION_SHA.fullmatch(revision) is None:
                violations.append(f"workflow {path.name} action {use} must pin a full commit SHA")
    return violations


def _validate_lockfiles(root: Path) -> list[str]:
    violations = [
        f"lock file {name} must be committed" for name in LOCK_FILES if not (root / name).is_file()
    ]
    package_json = root / "console" / "package.json"
    package_lock = root / "console" / "package-lock.json"
    if package_json.is_file() and package_lock.is_file():
        try:
            manifest = json.loads(package_json.read_text(encoding="utf-8"))
            lock = json.loads(package_lock.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            violations.append("console package manifest and lock must be readable valid JSON")
        else:
            if lock.get("lockfileVersion") != 3 or not isinstance(lock.get("packages"), Mapping):
                violations.append("console package-lock.json must use lockfileVersion 3")
            for group in ("dependencies", "devDependencies"):
                dependencies = manifest.get(group, {})
                if not isinstance(dependencies, Mapping):
                    violations.append(f"console package.json {group} must be an object")
                    continue
                for name, version in dependencies.items():
                    if (
                        not isinstance(version, str)
                        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None
                    ):
                        violations.append(f"console dependency {name} must use an exact version")
    return violations


def validate_repository(root: Path) -> tuple[str, ...]:
    """Return deterministic supply-chain violations for a source checkout."""
    violations = _validate_lockfiles(root)
    for name in COMPOSE_FILES:
        violations.extend(_validate_compose(root / name))
    for name in DOCKERFILES:
        violations.extend(_validate_dockerfile(root / name))
    violations.extend(_validate_workflows(root))
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the repository supply-chain contract."""
    if argv:
        print(
            "[supply-chain] configuration-error reason=arguments are not supported", file=sys.stderr
        )
        return 2
    violations = validate_repository(repository_root())
    if violations:
        for violation in violations:
            print(f"[supply-chain] violation={violation}", file=sys.stderr)
        print(f"[supply-chain] failed violations={len(violations)}", file=sys.stderr)
        return 1
    print("[supply-chain] passed locks=2 dockerfiles=2 compose_files=2")
    return 0

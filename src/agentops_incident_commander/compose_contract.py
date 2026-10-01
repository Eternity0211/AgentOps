"""Static validation for the local Docker Compose topology."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class ComposeConfigurationError(RuntimeError):
    """Raised when Docker Compose cannot render a trustworthy configuration."""


EXPECTED_SERVICES = {
    "control-postgres",
    "simulator-postgres",
    "simulator-redis",
    "prometheus",
    "loki",
    "tempo",
    "otel-collector",
}
EXPECTED_NETWORKS = {"control-plane", "simulator", "observability"}
EXPECTED_VOLUMES = {
    "control_postgres_data",
    "simulator_postgres_data",
    "simulator_redis_data",
    "prometheus_data",
    "loki_data",
    "tempo_data",
}
EXPECTED_SECRETS = {
    "control_db_password": "control-db-password.txt",
    "simulator_db_password": "simulator-db-password.txt",
    "simulator_redis_password": "simulator-redis-password.txt",
}


def repository_root() -> Path:
    """Return the repository root for the source checkout."""
    return Path(__file__).resolve().parents[2]


def render_compose_config(
    root: Path, source_environment: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Render all runtime profiles with non-secret contract-test credentials."""
    environment = dict(os.environ)
    if source_environment is not None:
        environment.update(source_environment)
    docker_config = root / ".docker-config"
    docker_config.mkdir(exist_ok=True)
    contract_secrets = docker_config / "compose-secrets"
    contract_secrets.mkdir(exist_ok=True)
    secret_paths = {
        environment_name: contract_secrets / filename
        for environment_name, filename in (
            ("CONTROL_DB_PASSWORD_FILE", "control-db-password.txt"),
            ("SIMULATOR_DB_PASSWORD_FILE", "simulator-db-password.txt"),
            ("SIMULATOR_REDIS_PASSWORD_FILE", "simulator-redis-password.txt"),
        )
    }
    for path in secret_paths.values():
        path.write_text("compose-contract-sentinel\n", encoding="utf-8")
    environment.update(
        {
            "DOCKER_CONFIG": str(docker_config),
            **{name: str(path) for name, path in secret_paths.items()},
        }
    )
    command = (
        "docker",
        "compose",
        "--profile",
        "control-plane",
        "--profile",
        "simulator",
        "--profile",
        "observability",
        "config",
        "--format",
        "json",
    )
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as error:
        raise ComposeConfigurationError("docker executable not found") from error
    except subprocess.TimeoutExpired as error:
        raise ComposeConfigurationError("docker compose config timed out") from error
    if result.returncode != 0:
        diagnostic = result.stderr.strip() or "no diagnostic"
        raise ComposeConfigurationError(
            f"docker compose config failed with exit code {result.returncode}: {diagnostic}"
        )
    try:
        rendered = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ComposeConfigurationError("docker compose returned invalid JSON") from error
    if not isinstance(rendered, dict):
        raise ComposeConfigurationError("docker compose JSON root must be an object")
    return rendered


def validate_compose_config(config: Mapping[str, Any]) -> tuple[str, ...]:
    """Return deterministic contract violations from rendered Compose JSON."""
    violations: list[str] = []
    services = config.get("services", {})
    if not isinstance(services, dict):
        return ("services must be an object",)
    if set(services) != EXPECTED_SERVICES:
        violations.append("services must match the approved Phase 1B topology")

    for name, service in sorted(services.items()):
        if not isinstance(service, dict):
            violations.append(f"service {name} must be an object")
            continue
        image = service.get("image", "")
        if not isinstance(image, str) or ":" not in image or image.endswith(":latest"):
            violations.append(f"service {name} must use an explicit non-latest image tag")
        if not service.get("profiles"):
            violations.append(f"service {name} must declare a profile")
        healthcheck = service.get("healthcheck")
        if not isinstance(healthcheck, dict) or not healthcheck.get("test"):
            violations.append(f"service {name} must declare a healthcheck")
        for resource in ("cpus", "mem_limit", "pids_limit"):
            if not service.get(resource):
                violations.append(f"service {name} must bound {resource}")
        if service.get("read_only") is not True or service.get("init") is not True:
            violations.append(f"service {name} must use read_only rootfs and init")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            violations.append(f"service {name} must disable privilege escalation")
        if service.get("privileged") is True:
            violations.append(f"service {name} must not be privileged")
        if not service.get("networks"):
            violations.append(f"service {name} must attach to an isolated network")
        for port in service.get("ports", []):
            if port.get("host_ip") != "127.0.0.1":
                violations.append(f"service {name} published ports must bind to loopback")
        if "POSTGRES_PASSWORD" in service.get("environment", {}):
            violations.append(f"service {name} must use a password file secret")

    networks = config.get("networks", {})
    for name in EXPECTED_NETWORKS:
        if not isinstance(networks.get(name), dict) or networks[name].get("internal") is not True:
            violations.append(f"network {name} must exist and be internal")
    if set(config.get("volumes", {})) != EXPECTED_VOLUMES:
        violations.append("named volumes must match the approved persistent stores")
    secrets = config.get("secrets", {})
    for name, expected_filename in EXPECTED_SECRETS.items():
        secret = secrets.get(name, {})
        secret_file = secret.get("file")
        if not isinstance(secret_file, str) or Path(secret_file).name != expected_filename:
            violations.append(f"secret {name} must use local file {expected_filename}")
    rendered_text = json.dumps(config, sort_keys=True)
    if "compose-contract-sentinel" in rendered_text:
        violations.append("rendered config must not expose secret values")
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the repository Compose contract."""
    if argv:
        print("[compose] configuration-error reason=arguments are not supported", file=sys.stderr)
        return 2
    root = repository_root()
    try:
        config = render_compose_config(root)
    except ComposeConfigurationError as error:
        print(f"[compose] configuration-error reason={error}", file=sys.stderr)
        return 2
    violations = validate_compose_config(config)
    if violations:
        for violation in violations:
            print(f"[compose] violation={violation}", file=sys.stderr)
        print(f"[compose] failed violations={len(violations)}", file=sys.stderr)
        return 1
    print(f"[compose] passed services={len(EXPECTED_SERVICES)}")
    return 0

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
    "gateway",
    "order",
    "inventory",
    "payment",
    "control-postgres",
    "simulator-postgres",
    "simulator-redis",
    "prometheus",
    "loki",
    "tempo",
    "otel-collector",
    "grafana",
}
EXPECTED_NETWORKS = {"control-plane", "simulator", "observability"}
HOST_INGRESS_NETWORKS = {"ingress", "observability-ingress"}
EXPECTED_VOLUMES = {
    "control_postgres_data",
    "simulator_postgres_data",
    "simulator_redis_data",
    "prometheus_data",
    "loki_data",
    "tempo_data",
    "grafana_data",
}
EXPECTED_SECRETS = {
    "control_db_password": "control-db-password.txt",
    "simulator_db_admin_password": "simulator-db-admin-password.txt",
    "simulator_db_password": "simulator-db-password.txt",
    "simulator_redis_password": "simulator-redis-password.txt",
    "grafana_admin_password": "grafana-admin-password.txt",
}
EXPECTED_SERVICE_NETWORKS = {
    "gateway": {"ingress", "simulator"},
    "order": {"simulator"},
    "inventory": {"simulator"},
    "payment": {"simulator"},
    "control-postgres": {"control-plane"},
    "simulator-postgres": {"simulator"},
    "simulator-redis": {"simulator"},
    "prometheus": {"observability", "observability-ingress"},
    "loki": {"observability", "observability-ingress"},
    "tempo": {"observability", "observability-ingress"},
    "otel-collector": {"observability", "simulator"},
    "grafana": {"observability", "observability-ingress"},
}
EXPECTED_SERVICE_SECRETS = {
    "gateway": (),
    "order": ("simulator_db_password",),
    "inventory": ("simulator_redis_password",),
    "payment": (),
    "control-postgres": ("control_db_password",),
    "simulator-postgres": ("simulator_db_admin_password", "simulator_db_password"),
    "simulator-redis": ("simulator_redis_password",),
    "prometheus": (),
    "loki": (),
    "tempo": (),
    "otel-collector": (),
    "grafana": ("grafana_admin_password",),
}
EXPECTED_VOLUME_MOUNTS = {
    "gateway": (),
    "order": (),
    "inventory": (),
    "payment": (),
    "control-postgres": (("control_postgres_data", "/var/lib/postgresql"),),
    "simulator-postgres": (("simulator_postgres_data", "/var/lib/postgresql"),),
    "simulator-redis": (("simulator_redis_data", "/data"),),
    "prometheus": (("prometheus_data", "/prometheus"),),
    "loki": (("loki_data", "/loki"),),
    "tempo": (("tempo_data", "/var/tempo"),),
    "otel-collector": (),
    "grafana": (("grafana_data", "/var/lib/grafana"),),
}
EXPECTED_CONFIG_MOUNTS = {
    "gateway": (),
    "order": (),
    "inventory": (),
    "payment": (),
    "control-postgres": (),
    "simulator-postgres": (
        ("simulator_postgres_init", "/docker-entrypoint-initdb.d/10-simulator-role.sh"),
    ),
    "simulator-redis": (),
    "prometheus": (
        ("prometheus_config", "/etc/prometheus/prometheus.yml"),
        ("prometheus_alert_rules", "/etc/prometheus/rules/agentops-alerts.yml"),
    ),
    "loki": (("loki_config", "/etc/loki/config.yml"),),
    "tempo": (("tempo_config", "/etc/tempo/config.yml"),),
    "otel-collector": (("otel_collector_config", "/etc/otelcol-contrib/config.yml"),),
    "grafana": (
        ("grafana_datasources", "/etc/grafana/provisioning/datasources/agentops.yml"),
        ("grafana_dashboard_provider", "/etc/grafana/provisioning/dashboards/agentops.yml"),
        ("grafana_diagnosed_dashboard", "/etc/grafana/dashboards/diagnosed-system.json"),
        ("grafana_control_plane_dashboard", "/etc/grafana/dashboards/agent-platform.json"),
    ),
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
            ("SIMULATOR_DB_ADMIN_PASSWORD_FILE", "simulator-db-admin-password.txt"),
            ("SIMULATOR_DB_PASSWORD_FILE", "simulator-db-password.txt"),
            ("SIMULATOR_REDIS_PASSWORD_FILE", "simulator-redis-password.txt"),
            ("GRAFANA_ADMIN_PASSWORD_FILE", "grafana-admin-password.txt"),
        )
    }
    for path in secret_paths.values():
        path.write_text("compose-contract-sentinel\n", encoding="utf-8")
    environment.update(
        {
            "DOCKER_CONFIG": str(docker_config),
            "SIMULATOR_DB_ADMIN_USER": "simulator_admin",
            "SIMULATOR_DB_USER": "simulator_app",
            "SIMULATOR_REDIS_USER": "inventory_app",
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
        violations.append("services must match the approved runtime topology")

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
        if set(service.get("networks", {})) != EXPECTED_SERVICE_NETWORKS.get(name, set()):
            violations.append(f"service {name} networks must match its least-privilege paths")
        secret_bindings = tuple(item.get("source") for item in service.get("secrets", []))
        if secret_bindings != EXPECTED_SERVICE_SECRETS.get(name, ()):
            violations.append(f"service {name} secrets must match its credential allowlist")
        for item in service.get("secrets", []):
            if not str(item.get("target", "")).startswith("/run/secrets/"):
                violations.append(f"service {name} secrets must mount below /run/secrets")
        volume_bindings = tuple(
            (item.get("source"), item.get("target")) for item in service.get("volumes", [])
        )
        if volume_bindings != EXPECTED_VOLUME_MOUNTS.get(name, ()):
            violations.append(f"service {name} volumes must match its writable-store allowlist")
        config_bindings = tuple(
            (item.get("source"), item.get("target")) for item in service.get("configs", [])
        )
        if config_bindings != EXPECTED_CONFIG_MOUNTS.get(name, ()):
            violations.append(f"service {name} configs must match its read-only config allowlist")
        for port in service.get("ports", []):
            if port.get("host_ip") != "127.0.0.1":
                violations.append(f"service {name} published ports must bind to loopback")
        environment = service.get("environment", {}) or {}
        for key, value in environment.items():
            if "PASSWORD" not in key:
                continue
            if not key.endswith("FILE") or not str(value).startswith("/run/secrets/"):
                violations.append(f"service {name} must use a password file secret")

    networks = config.get("networks", {})
    for name in EXPECTED_NETWORKS:
        if not isinstance(networks.get(name), dict) or networks[name].get("internal") is not True:
            violations.append(f"network {name} must exist and be internal")
    for name in HOST_INGRESS_NETWORKS:
        ingress = networks.get(name)
        if not isinstance(ingress, dict) or ingress.get("internal") is True:
            violations.append(f"network {name} must exist and permit explicit host ingress")
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

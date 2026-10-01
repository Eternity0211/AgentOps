"""Tests for the static Docker Compose topology contract."""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from agentops_incident_commander import compose_contract


@pytest.fixture(scope="module")
def rendered_config() -> dict[str, object]:
    """Render the checked-in Compose file once for contract tests."""
    return compose_contract.render_compose_config(compose_contract.repository_root())


def test_checked_in_compose_contract_is_valid(rendered_config: dict[str, object]) -> None:
    """The real Compose model satisfies every static topology invariant."""
    assert compose_contract.validate_compose_config(rendered_config) == ()


def test_validation_reports_service_and_topology_violations(
    rendered_config: dict[str, object],
) -> None:
    """Every safety category fails closed with an actionable diagnostic."""
    invalid = copy.deepcopy(rendered_config)
    services = invalid["services"]
    assert isinstance(services, dict)
    control = services["control-postgres"]
    assert isinstance(control, dict)
    control.update(
        {
            "image": "postgres:latest",
            "profiles": [],
            "healthcheck": {},
            "cpus": 0,
            "mem_limit": 0,
            "pids_limit": 0,
            "read_only": False,
            "init": False,
            "security_opt": [],
            "privileged": True,
            "networks": {},
            "ports": [{"host_ip": "0.0.0.0"}],
            "environment": {"POSTGRES_PASSWORD": "unsafe"},
        }
    )
    services["unexpected"] = "invalid"
    invalid["networks"] = {}
    invalid["volumes"] = {}
    invalid["secrets"] = {}

    violations = compose_contract.validate_compose_config(invalid)

    assert "services must match the approved Phase 1B topology" in violations
    assert "service unexpected must be an object" in violations
    assert "service control-postgres must not be privileged" in violations
    assert "service control-postgres published ports must bind to loopback" in violations
    assert "service control-postgres must use a password file secret" in violations
    assert "network simulator must exist and be internal" in violations
    assert "named volumes must match the approved persistent stores" in violations
    assert "secret control_db_password must use local file control-db-password.txt" in violations


def test_validation_rejects_non_object_services() -> None:
    """A malformed services root cannot be interpreted as a safe topology."""
    assert compose_contract.validate_compose_config({"services": []}) == (
        "services must be an object",
    )


def test_validation_detects_rendered_secret_values(
    rendered_config: dict[str, object],
) -> None:
    """Contract-test secret sentinels may never appear in rendered output."""
    invalid = copy.deepcopy(rendered_config)
    invalid["x-leak"] = "compose-contract-sentinel"

    assert "rendered config must not expose secret values" in (
        compose_contract.validate_compose_config(invalid)
    )


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FileNotFoundError(), "docker executable not found"),
        (subprocess.TimeoutExpired(cmd=("docker",), timeout=30), "timed out"),
    ],
)
def test_render_reports_process_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    message: str,
) -> None:
    """Missing or hung Docker clients produce stable configuration errors."""

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    monkeypatch.setattr("agentops_incident_commander.compose_contract.subprocess.run", fake_run)

    with pytest.raises(compose_contract.ComposeConfigurationError, match=message):
        compose_contract.render_compose_config(tmp_path, {})


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (subprocess.CompletedProcess([], 7, "", "bad compose"), "exit code 7"),
        (subprocess.CompletedProcess([], 0, "not-json", ""), "invalid JSON"),
        (subprocess.CompletedProcess([], 0, json.dumps([]), ""), "root must be an object"),
    ],
)
def test_render_rejects_failed_or_invalid_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: subprocess.CompletedProcess[str],
    message: str,
) -> None:
    """Only successful object-shaped Compose JSON can reach validation."""
    monkeypatch.setattr(
        "agentops_incident_commander.compose_contract.subprocess.run",
        lambda *args, **kwargs: result,
    )

    with pytest.raises(compose_contract.ComposeConfigurationError, match=message):
        compose_contract.render_compose_config(tmp_path, {})


def test_main_success(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI reports the service count for a valid topology."""
    monkeypatch.setattr(compose_contract, "render_compose_config", lambda root: {"services": {}})
    monkeypatch.setattr(compose_contract, "validate_compose_config", lambda config: ())

    assert compose_contract.main() == 0
    assert "passed services=7" in capsys.readouterr().out


def test_main_reports_violations(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI prints all semantic violations and returns one."""
    monkeypatch.setattr(compose_contract, "render_compose_config", lambda root: {})
    monkeypatch.setattr(
        compose_contract, "validate_compose_config", lambda config: ("first", "second")
    )

    assert compose_contract.main() == 1
    error = capsys.readouterr().err
    assert "violation=first" in error
    assert "failed violations=2" in error


def test_main_reports_configuration_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI returns two for invalid invocation and render failures."""
    assert compose_contract.main(("unexpected",)) == 2
    monkeypatch.setattr(
        compose_contract,
        "render_compose_config",
        lambda root: (_ for _ in ()).throw(compose_contract.ComposeConfigurationError("bad")),
    )
    assert compose_contract.main() == 2
    assert "configuration-error" in capsys.readouterr().err

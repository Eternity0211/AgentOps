"""Tests for repository supply-chain and container controls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentops_incident_commander import supply_chain

DIGEST = "sha256:" + ("a" * 64)
ACTION_SHA = "b" * 40


def write_valid_repository(root: Path) -> None:
    """Write the smallest checkout satisfying every supply-chain invariant."""
    (root / "console").mkdir()
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "console" / "package.json").write_text(
        json.dumps({"dependencies": {"next": "1.2.3"}, "devDependencies": {"lint": "4.5.6"}}),
        encoding="utf-8",
    )
    (root / "console" / "package-lock.json").write_text(
        json.dumps({"lockfileVersion": 3, "packages": {"": {}}}), encoding="utf-8"
    )
    runtime = f"""services:
  app:
    image: local/app:test
    build: {{context: .}}
    cap_drop: [ALL]
    read_only: true
    security_opt: [no-new-privileges:true]
  store:
    image: example/store:1.2.3@{DIGEST}
    read_only: true
    security_opt: [no-new-privileges:true]
"""
    evaluation = """services:
  evaluator:
    image: local/evaluator:test
    build: {context: .}
    cap_drop: [ALL]
    read_only: true
    security_opt: [no-new-privileges:true]
"""
    (root / "compose.yaml").write_text(runtime, encoding="utf-8")
    (root / "compose.evaluation.yaml").write_text(evaluation, encoding="utf-8")
    dockerfile = (
        f"FROM python:3.12-slim@{DIGEST}\n"
        "RUN apt-get install openssl=1.2.3 libpcre2-8-0=1.2.3\n"
        "USER 10001:10001\n"
    )
    for name in supply_chain.DOCKERFILES:
        (root / name).write_text(dockerfile, encoding="utf-8")
    (root / ".github" / "workflows" / "quality.yml").write_text(
        f"steps:\n  - uses: actions/checkout@{ACTION_SHA}\n  - uses: ./local-action\n",
        encoding="utf-8",
    )


def test_checked_in_repository_satisfies_supply_chain_contract() -> None:
    assert supply_chain.repository_root().name == "AgentOps"
    assert supply_chain.validate_repository(supply_chain.repository_root()) == ()


def test_minimal_valid_repository_satisfies_contract(tmp_path: Path) -> None:
    write_valid_repository(tmp_path)

    assert supply_chain.validate_repository(tmp_path) == ()


def test_compose_validation_reports_every_permission_and_pin_violation(tmp_path: Path) -> None:
    path = tmp_path / "compose.yaml"
    path.write_text(
        """services:
  malformed: invalid
  missing-image:
    build: {context: .}
    privileged: true
    read_only: false
    security_opt: []
    volumes: [/var/run/docker.sock:/var/run/docker.sock]
  bad-built:
    image: local/app:latest
    build: {context: .}
    read_only: true
    security_opt: [no-new-privileges:true]
  bad-external:
    image: example/store:latest
    read_only: true
    security_opt: [no-new-privileges:true]
""",
        encoding="utf-8",
    )

    violations = supply_chain._validate_compose(path)

    assert f"{path.name} service malformed must be an object" in violations
    assert f"{path.name} service missing-image must declare an image" in violations
    assert f"{path.name} built service bad-built must use an explicit local image tag" in violations
    assert f"{path.name} external service bad-external must pin tag and sha256 digest" in violations
    assert f"{path.name} built service missing-image must drop all capabilities" in violations
    assert f"{path.name} service missing-image must not be privileged" in violations
    assert f"{path.name} service missing-image must use a read-only root filesystem" in violations
    assert f"{path.name} service missing-image must disable privilege escalation" in violations
    assert f"{path.name} service missing-image must not mount the Docker socket" in violations


@pytest.mark.parametrize("content", ["services: [", "services: []", "[]"])
def test_compose_validation_rejects_invalid_or_non_object_yaml(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "compose.yaml"
    path.write_text(content, encoding="utf-8")

    assert len(supply_chain._validate_compose(path)) == 1


def test_compose_validation_reports_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    assert supply_chain._validate_compose(tmp_path / "compose.yaml") == [
        "compose.yaml must be readable valid YAML"
    ]


def test_dockerfile_validation_rejects_unpinned_base_and_named_user(tmp_path: Path) -> None:
    path = tmp_path / "Dockerfile.bad"
    path.write_text("FROM python:latest\nFROM busybox:1\nUSER app:app\n", encoding="utf-8")

    assert supply_chain._validate_dockerfile(path) == [
        "Dockerfile.bad must pin one tagged base image by sha256 digest",
        "Dockerfile.bad must declare one non-root numeric UID:GID",
        "Dockerfile.bad must install reviewed fixed OS security packages",
    ]


def test_dockerfile_validation_reports_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))

    assert supply_chain._validate_dockerfile(tmp_path / "Dockerfile") == [
        "Dockerfile must be readable"
    ]


def test_workflow_validation_requires_workflows_and_full_action_shas(tmp_path: Path) -> None:
    assert supply_chain._validate_workflows(tmp_path) == [
        "repository must contain GitHub Actions workflows"
    ]
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "bad.yml").write_text(
        "steps:\n  - uses: actions/checkout@v4\n  - uses: action-without-revision\n",
        encoding="utf-8",
    )

    violations = supply_chain._validate_workflows(tmp_path)

    assert len(violations) == 2
    assert all("must pin a full commit SHA" in violation for violation in violations)


def test_workflow_validation_reports_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    path = workflows / "bad.yml"
    path.write_text("steps: []\n", encoding="utf-8")
    original = Path.read_text

    def fail_selected(
        candidate: Path, encoding: str | None = None, errors: str | None = None
    ) -> str:
        if candidate == path:
            raise UnicodeError
        return original(candidate, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", fail_selected)

    assert supply_chain._validate_workflows(tmp_path) == ["workflow bad.yml must be readable"]


def test_lockfile_validation_reports_missing_malformed_and_unlocked_versions(
    tmp_path: Path,
) -> None:
    assert supply_chain._validate_lockfiles(tmp_path) == [
        "lock file uv.lock must be committed",
        "lock file console/package-lock.json must be committed",
    ]
    (tmp_path / "console").mkdir()
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "console" / "package.json").write_text("invalid", encoding="utf-8")
    (tmp_path / "console" / "package-lock.json").write_text("{}", encoding="utf-8")
    assert supply_chain._validate_lockfiles(tmp_path) == [
        "console package manifest and lock must be readable valid JSON"
    ]

    (tmp_path / "console" / "package.json").write_text(
        json.dumps({"dependencies": [], "devDependencies": {"lint": "^1.2.3"}}),
        encoding="utf-8",
    )
    violations = supply_chain._validate_lockfiles(tmp_path)
    assert "console package-lock.json must use lockfileVersion 3" in violations
    assert "console package.json dependencies must be an object" in violations
    assert "console dependency lint must use an exact version" in violations


def test_main_reports_success_violations_and_invalid_arguments(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert supply_chain.main(("unexpected",)) == 2
    assert "configuration-error" in capsys.readouterr().err

    monkeypatch.setattr(supply_chain, "validate_repository", lambda root: ("bad pin",))
    assert supply_chain.main() == 1
    error = capsys.readouterr().err
    assert "violation=bad pin" in error
    assert "failed violations=1" in error

    monkeypatch.setattr(supply_chain, "validate_repository", lambda root: ())
    assert supply_chain.main() == 0
    assert "passed locks=2" in capsys.readouterr().out

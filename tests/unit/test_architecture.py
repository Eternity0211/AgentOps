"""Tests for domain import-boundary enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentops_incident_commander import architecture


def create_source_tree(tmp_path: Path, source: str = "") -> tuple[Path, Path]:
    """Create a minimal package and one domain module."""
    source_root = tmp_path / "src"
    domain_root = source_root / "agentops_incident_commander" / "domain"
    domain_root.mkdir(parents=True)
    (domain_root / "sample.py").write_text(source, encoding="utf-8")
    return source_root, domain_root


def test_repository_domain_has_no_forbidden_imports() -> None:
    """The checked-in domain package obeys its dependency contract."""
    source_root = architecture.repository_root() / "src"

    assert architecture.find_domain_import_violations(source_root) == ()


@pytest.mark.parametrize(
    "module",
    [
        "fastapi",
        "fastapi.routing",
        "sqlalchemy.orm",
        "langgraph.graph",
        "langchain_core.messages",
        "openai",
        "anthropic.types",
        "google.genai",
        "azure.ai.inference",
        "boto3",
    ],
)
def test_external_framework_and_provider_imports_are_rejected(tmp_path: Path, module: str) -> None:
    """Framework, orchestration, ORM, and provider SDK imports cannot enter domain."""
    source_root, _ = create_source_tree(tmp_path, f"import {module}\n")

    violations = architecture.find_domain_import_violations(source_root)

    assert len(violations) == 1
    assert violations[0].imported_module == module
    assert violations[0].line == 1


@pytest.mark.parametrize("layer", ["apps", "application", "workflows", "infrastructure"])
def test_higher_internal_layers_are_rejected(tmp_path: Path, layer: str) -> None:
    """Internal dependencies retain the adapter-to-domain direction."""
    imported_module = f"agentops_incident_commander.{layer}.example"
    source_root, _ = create_source_tree(tmp_path, f"from {imported_module} import Thing\n")

    violations = architecture.find_domain_import_violations(source_root)

    assert [violation.imported_module for violation in violations] == [imported_module]


def test_relative_escape_to_infrastructure_is_rejected(tmp_path: Path) -> None:
    """Relative imports cannot bypass the internal layer rules."""
    source_root, _ = create_source_tree(
        tmp_path, "from ..infrastructure.providers import ModelClient\n"
    )

    violations = architecture.find_domain_import_violations(source_root)

    assert violations[0].imported_module == ("agentops_incident_commander.infrastructure.providers")


@pytest.mark.parametrize(
    ("source", "expected_module"),
    [
        (
            "from agentops_incident_commander import infrastructure\n",
            "agentops_incident_commander.infrastructure",
        ),
        ("from google import genai\n", "google.genai"),
        ("from azure import ai\n", "azure.ai"),
    ],
)
def test_forbidden_import_members_cannot_bypass_base_module_checks(
    tmp_path: Path, source: str, expected_module: str
) -> None:
    """Restricted members imported from an allowed base are still resolved."""
    source_root, _ = create_source_tree(tmp_path, source)

    violations = architecture.find_domain_import_violations(source_root)

    assert [violation.imported_module for violation in violations] == [expected_module]


def test_from_import_reports_each_rule_only_once(tmp_path: Path) -> None:
    """A base module and its member produce one diagnostic for the same rule."""
    source_root, _ = create_source_tree(tmp_path, "from fastapi import routing\n")

    violations = architecture.find_domain_import_violations(source_root)

    assert [violation.imported_module for violation in violations] == ["fastapi"]


def test_allowed_imports_and_multiple_aliases_are_handled(tmp_path: Path) -> None:
    """Standard-library/domain imports pass while every forbidden alias is reported."""
    source_root, _ = create_source_tree(
        tmp_path,
        "from __future__ import annotations\n"
        "from .values import IncidentId\n"
        "import datetime\n"
        "import fastapi, sqlalchemy\n",
    )

    violations = architecture.find_domain_import_violations(source_root)

    assert [violation.imported_module for violation in violations] == [
        "fastapi",
        "sqlalchemy",
    ]
    assert all(violation.line == 4 for violation in violations)


def test_package_init_relative_import_is_resolved(tmp_path: Path) -> None:
    """Relative imports from a package initializer resolve against that package."""
    source_root, domain_root = create_source_tree(tmp_path)
    (domain_root / "__init__.py").write_text(
        "from ..infrastructure import repository\n", encoding="utf-8"
    )

    violations = architecture.find_domain_import_violations(source_root)

    assert violations[0].imported_module == "agentops_incident_commander.infrastructure"


def test_relative_import_beyond_source_package_fails_safely(tmp_path: Path) -> None:
    """An over-deep relative import is still checked by its declared module name."""
    source_root, _ = create_source_tree(tmp_path, "from ....fastapi import FastAPI\n")

    violations = architecture.find_domain_import_violations(source_root)

    assert violations[0].imported_module == "fastapi"


@pytest.mark.parametrize("missing", ["source", "domain"])
def test_missing_roots_fail_closed(tmp_path: Path, missing: str) -> None:
    """A missing checked tree is a configuration failure, never a passing check."""
    source_root, domain_root = create_source_tree(tmp_path)
    target = source_root if missing == "source" else domain_root
    target.rename(target.with_name(f"missing-{target.name}"))

    with pytest.raises(architecture.BoundaryConfigurationError, match="does not exist"):
        architecture.find_domain_import_violations(source_root)


def test_domain_root_must_be_inside_source_root(tmp_path: Path) -> None:
    """Explicit domain roots cannot point outside the declared source tree."""
    source_root, _ = create_source_tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(architecture.BoundaryConfigurationError, match="must be inside"):
        architecture.find_domain_import_violations(source_root, outside)


def test_unparseable_domain_source_fails_closed(tmp_path: Path) -> None:
    """Syntax errors do not silently remove a module from boundary enforcement."""
    source_root, _ = create_source_tree(tmp_path, "from ???\n")

    with pytest.raises(architecture.BoundaryConfigurationError, match="cannot parse"):
        architecture.find_domain_import_violations(source_root)


def test_violation_render_uses_source_relative_path(tmp_path: Path) -> None:
    """Diagnostics are stable and directly usable by editors and CI."""
    source_root, domain_root = create_source_tree(tmp_path)
    violation = architecture.ImportViolation(
        domain_root / "sample.py", 7, "fastapi", "web dependency"
    )

    assert violation.render(source_root) == (
        "agentops_incident_commander/domain/sample.py:7: "
        "forbidden import 'fastapi' (web dependency)"
    )


def test_cli_reports_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI returns zero and a concise success record for a clean tree."""
    source_root, _ = create_source_tree(tmp_path, "import datetime\n")

    assert architecture.main(("--source-root", str(source_root))) == 0
    assert "passed violations=0" in capsys.readouterr().out


def test_cli_reports_violations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI returns one and prints each actionable violation."""
    source_root, _ = create_source_tree(tmp_path, "import fastapi\n")

    assert architecture.main(("--source-root", str(source_root))) == 1
    error = capsys.readouterr().err
    assert "sample.py:1" in error
    assert "failed violations=1" in error


def test_cli_reports_configuration_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI distinguishes configuration errors with exit code two."""
    missing_source = tmp_path / "missing"

    assert architecture.main(("--source-root", str(missing_source))) == 2
    assert "configuration-error" in capsys.readouterr().err

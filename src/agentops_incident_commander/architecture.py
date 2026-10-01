"""Static dependency rules for the pure incident domain layer."""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


class BoundaryConfigurationError(ValueError):
    """Raised when the source tree cannot be checked reliably."""


@dataclass(frozen=True, slots=True)
class ImportViolation:
    """One forbidden import found in a domain source file."""

    path: Path
    line: int
    imported_module: str
    reason: str

    def render(self, source_root: Path) -> str:
        """Render a stable, editor-friendly diagnostic."""
        relative_path = self.path.relative_to(source_root).as_posix()
        return (
            f"{relative_path}:{self.line}: forbidden import "
            f"'{self.imported_module}' ({self.reason})"
        )


FORBIDDEN_IMPORTS: tuple[tuple[str, str], ...] = (
    ("fastapi", "domain must not depend on the web framework"),
    ("sqlalchemy", "domain must not depend on the ORM"),
    ("langgraph", "domain must not depend on workflow orchestration"),
    ("langchain", "domain must not depend on model/workflow SDKs"),
    ("langchain_core", "domain must not depend on model/workflow SDKs"),
    ("openai", "domain must not depend on model-provider SDKs"),
    ("anthropic", "domain must not depend on model-provider SDKs"),
    ("cohere", "domain must not depend on model-provider SDKs"),
    ("mistralai", "domain must not depend on model-provider SDKs"),
    ("ollama", "domain must not depend on model-provider SDKs"),
    ("google.genai", "domain must not depend on model-provider SDKs"),
    ("google.generativeai", "domain must not depend on model-provider SDKs"),
    ("vertexai", "domain must not depend on model-provider SDKs"),
    ("azure.ai", "domain must not depend on model-provider SDKs"),
    ("boto3", "domain must not depend on model-provider/infrastructure SDKs"),
    ("botocore", "domain must not depend on model-provider/infrastructure SDKs"),
    (
        "agentops_incident_commander.apps",
        "domain must not depend on process composition",
    ),
    (
        "agentops_incident_commander.application",
        "dependency direction is application to domain",
    ),
    (
        "agentops_incident_commander.workflows",
        "domain must not depend on workflow adapters",
    ),
    (
        "agentops_incident_commander.infrastructure",
        "domain must not depend on infrastructure or provider adapters",
    ),
)


def repository_root() -> Path:
    """Return the repository root for the source checkout."""
    return Path(__file__).resolve().parents[2]


def _matches_prefix(imported_module: str, forbidden_prefix: str) -> bool:
    return imported_module == forbidden_prefix or imported_module.startswith(f"{forbidden_prefix}.")


def _module_parts(path: Path, source_root: Path) -> tuple[str, ...]:
    relative = path.relative_to(source_root).with_suffix("")
    return relative.parts[:-1]


def _resolve_from_import(node: ast.ImportFrom, path: Path, source_root: Path) -> str:
    imported_parts = tuple(node.module.split(".")) if node.module else ()
    if node.level == 0:
        return ".".join(imported_parts)

    package_parts = _module_parts(path, source_root)
    parents_to_remove = node.level - 1
    if parents_to_remove >= len(package_parts):
        return ".".join(imported_parts)
    base_parts = package_parts[: len(package_parts) - parents_to_remove]
    return ".".join((*base_parts, *imported_parts))


def _imports(path: Path, source_root: Path) -> Iterable[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as error:
        raise BoundaryConfigurationError(f"cannot parse {path}: {error}") from error

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name
        elif isinstance(node, ast.ImportFrom):
            imported_module = _resolve_from_import(node, path, source_root)
            yield node.lineno, imported_module
            for alias in node.names:
                qualified_alias = (
                    f"{imported_module}.{alias.name}" if imported_module else alias.name
                )
                yield node.lineno, qualified_alias


def find_domain_import_violations(
    source_root: Path, domain_root: Path | None = None
) -> tuple[ImportViolation, ...]:
    """Return every forbidden domain import in deterministic path/line order."""
    source_root = source_root.resolve()
    domain_root = (
        source_root / "agentops_incident_commander" / "domain"
        if domain_root is None
        else domain_root.resolve()
    )
    if not source_root.is_dir():
        raise BoundaryConfigurationError(f"source root does not exist: {source_root}")
    if not domain_root.is_dir():
        raise BoundaryConfigurationError(f"domain root does not exist: {domain_root}")
    try:
        domain_root.relative_to(source_root)
    except ValueError as error:
        raise BoundaryConfigurationError("domain root must be inside source root") from error

    violations: list[ImportViolation] = []
    for path in sorted(domain_root.rglob("*.py")):
        reported_rules: set[tuple[int, str]] = set()
        for line, imported_module in _imports(path, source_root):
            for forbidden_prefix, reason in FORBIDDEN_IMPORTS:
                if _matches_prefix(imported_module, forbidden_prefix):
                    rule_key = (line, forbidden_prefix)
                    if rule_key not in reported_rules:
                        violations.append(ImportViolation(path, line, imported_module, reason))
                        reported_rules.add(rule_key)
                    break
    return tuple(violations)


def build_parser() -> argparse.ArgumentParser:
    """Build the architecture-check CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=repository_root() / "src",
        help="Python source root; defaults to the repository src directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Check the configured domain boundary and return a stable exit code."""
    arguments = build_parser().parse_args(argv)
    try:
        violations = find_domain_import_violations(arguments.source_root)
    except BoundaryConfigurationError as error:
        print(f"[architecture] configuration-error reason={error}", file=sys.stderr)
        return 2

    if violations:
        for violation in violations:
            print(violation.render(arguments.source_root), file=sys.stderr)
        print(f"[architecture] failed violations={len(violations)}", file=sys.stderr)
        return 1

    print("[architecture] passed violations=0")
    return 0

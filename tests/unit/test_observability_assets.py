"""Contracts for provisioned dual-layer dashboards and actionable alerts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from agentops_incident_commander.compose_contract import repository_root

OBSERVABILITY = repository_root() / "config" / "observability"
DASHBOARDS = OBSERVABILITY / "grafana"
FORBIDDEN_IDENTITY_LABELS = {
    "tenant_id",
    "incident_id",
    "correlation_id",
    "causation_id",
    "operation_id",
    "workflow_run_id",
}


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def load_dashboard(name: str) -> dict[str, Any]:
    value = json.loads((DASHBOARDS / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def targets(dashboard: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for panel in dashboard["panels"]:
        assert isinstance(panel, dict)
        for target in panel.get("targets", []):
            assert isinstance(target, dict)
            values.append(target)
    return values


def test_alert_rules_are_unique_actionable_and_layered() -> None:
    config = load_yaml(OBSERVABILITY / "alerts.yml")
    groups = config["groups"]
    assert isinstance(groups, list)
    assert {group["name"] for group in groups} == {
        "agentops-diagnosed-system",
        "agentops-control-plane",
    }
    rules = [rule for group in groups for rule in group["rules"]]
    names = [rule["alert"] for rule in rules]
    assert len(rules) == 9
    assert len(names) == len(set(names))

    runbooks = (repository_root() / "docs" / "OBSERVABILITY_RUNBOOKS.md").read_text(
        encoding="utf-8"
    )
    for rule in rules:
        assert re.fullmatch(r"AgentOps[A-Za-z0-9]+", rule["alert"])
        assert rule["labels"]["layer"] in {
            "diagnosed-system",
            "agent-platform",
            "shared-observability",
        }
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert isinstance(rule.get("for"), str) and rule["for"]
        annotations = rule["annotations"]
        assert annotations["summary"]
        assert annotations["description"]
        url = annotations["runbook_url"]
        assert url.startswith(
            "https://github.com/Eternity0211/AgentOps/blob/main/docs/OBSERVABILITY_RUNBOOKS.md#"
        )
        anchor = url.rsplit("#", 1)[1]
        assert f'<a id="{anchor}"></a>' in runbooks
        expression = rule["expr"]
        assert not any(label in expression for label in FORBIDDEN_IDENTITY_LABELS)


def test_dashboards_are_immutable_dual_layer_views_with_safe_queries() -> None:
    diagnosed = load_dashboard("diagnosed-system.json")
    platform = load_dashboard("agent-platform.json")
    assert {diagnosed["uid"], platform["uid"]} == {
        "agentops-diagnosed",
        "agentops-platform",
    }
    assert "diagnosed-system" in diagnosed["tags"]
    assert "agent-platform" in platform["tags"]

    for dashboard, metric_prefix in (
        (diagnosed, "simulator_"),
        (platform, "agentops_"),
    ):
        assert dashboard["editable"] is False
        assert dashboard["refresh"] == "10s"
        assert len(dashboard["panels"]) >= 8
        assert dashboard["links"][0]["url"].endswith("docs/OBSERVABILITY_RUNBOOKS.md")
        query_targets = targets(dashboard)
        assert any(target.get("queryType") == "range" for target in query_targets)
        for target in query_targets:
            expression = target.get("expr")
            assert isinstance(expression, str) and expression
            assert not any(label in expression for label in FORBIDDEN_IDENTITY_LABELS)
            if target.get("queryType") != "range" and "ALERTS" not in expression:
                assert metric_prefix in expression or expression.startswith("up{")


def test_grafana_provisioning_uses_only_internal_fixed_datasources() -> None:
    datasources = load_yaml(DASHBOARDS / "datasources.yml")["datasources"]
    assert {(item["uid"], item["type"], item["url"], item["editable"]) for item in datasources} == {
        ("agentops-prometheus", "prometheus", "http://prometheus:9090", False),
        ("agentops-loki", "loki", "http://loki:3100", False),
        ("agentops-tempo", "tempo", "http://tempo:3200", False),
    }
    provider = load_yaml(DASHBOARDS / "dashboards.yml")["providers"][0]
    assert provider["folderUid"] == "agentops"
    assert provider["disableDeletion"] is True
    assert provider["allowUiUpdates"] is False
    assert provider["options"]["path"] == "/etc/grafana/dashboards"

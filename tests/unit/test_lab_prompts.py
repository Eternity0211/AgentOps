"""Isolated Prompt bootstrap cannot target another tenant."""

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest
from evaluation.lab_prompts import prepare_lab_prompts

from agentops_incident_commander.domain import TenantId


def test_lab_prompt_bootstrap_rejects_other_tenant_before_any_effect(tmp_path: Path) -> None:
    root = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="another tenant"):
        asyncio.run(
            prepare_lab_prompts(
                cast(Any, None),
                cast(Any, None),
                root,
                lambda e: None,
                tenant=TenantId("other-tenant"),
            )
        )
    assert not root.exists()


def test_lab_bootstrap_unknown_fixture_and_missing_key_fail_before_effect(tmp_path: Path) -> None:
    from evaluation.run_lab_bootstrap import run

    root = tmp_path / "must-not-exist"
    with pytest.raises(ValueError, match="fixture version"):
        asyncio.run(
            prepare_lab_prompts(
                cast(Any, None), cast(Any, None), root, lambda e: None, fixture_version="99.0.0"
            )
        )
    with pytest.raises(ValueError, match="API_KEY"):
        run(root, "")
    with pytest.raises(ValueError, match="fixture version"):
        run(root, "test-only", fixture_version="99.0.0")
    assert not root.exists()

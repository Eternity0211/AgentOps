"""Live integration refuses missing credentials before creating output or injecting faults."""

from pathlib import Path
from typing import Any

import pytest
from evaluation.run_registered_live import run


@pytest.mark.parametrize("key", ["", " "])
def test_registered_live_requires_key_before_any_effect(tmp_path: Path, key: str) -> None:
    target = tmp_path / "not-created"
    with pytest.raises(ValueError, match="API_KEY"):
        run(target, key)
    assert not target.exists()


@pytest.mark.parametrize("cases", [(), (None, None), ("unknown",)])
def test_registered_live_refuses_invalid_matrix_before_output(tmp_path: Path, cases: Any) -> None:
    target = tmp_path / "not-created"
    with pytest.raises(ValueError, match="protocol"):
        run(target, "test-only", cases=cases)
    assert not target.exists()


def test_full_live_matrix_covers_actual_scenario_registry() -> None:
    from evaluation.run_registered_live import FULL_CASES

    from agentops_incident_commander.faults import SCENARIO_TARGETS

    assert len(FULL_CASES) == 7 and set(FULL_CASES) == {None, *SCENARIO_TARGETS}

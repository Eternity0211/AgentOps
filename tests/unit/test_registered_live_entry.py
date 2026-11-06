"""Live integration refuses missing credentials before creating output or injecting faults."""

from pathlib import Path

import pytest
from evaluation.run_registered_live import run


@pytest.mark.parametrize("key", ["", " "])
def test_registered_live_requires_key_before_any_effect(tmp_path: Path, key: str) -> None:
    target = tmp_path / "not-created"
    with pytest.raises(ValueError, match="API_KEY"):
        run(target, key)
    assert not target.exists()

"""Concurrent real-model entry refuses credentials before any local or remote effect."""

from pathlib import Path

import pytest
from evaluation.run_concurrent_registered import run


@pytest.mark.parametrize("key", ["", " ", " test-only"])
def test_concurrent_entry_refuses_missing_or_untrimmed_key(tmp_path: Path, key: str) -> None:
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="API_KEY"):
        run(output, key)
    assert not output.exists()

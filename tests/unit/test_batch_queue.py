"""Evaluation batch bounds cannot expand through caller input."""

from typing import Any

import pytest
from evaluation.batch_queue import BatchQueue


@pytest.mark.parametrize(
    "expected,concurrency,timeout", [(0, 1, 30), (17, 2, 30), (2, 3, 30), (2, 1, 601)]
)
def test_batch_rejects_invalid_bounds(expected: int, concurrency: int, timeout: int) -> None:
    sessions: Any = None
    with pytest.raises(ValueError, match="bounds"):
        BatchQueue(sessions, expected, concurrency, timeout)


@pytest.mark.anyio
async def test_batch_unknown_job_refuses_before_handler() -> None:
    from types import SimpleNamespace

    sessions: Any = None
    batch = BatchQueue(sessions, 1, 1)
    lease: Any = SimpleNamespace(job=SimpleNamespace(id=SimpleNamespace(value="foreign")))
    with pytest.raises(ValueError, match="identity mismatch"):
        await batch.dispatch(lease)
    assert batch.active == batch.peak == 0

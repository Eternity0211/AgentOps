"""Resource observations survive failures and never stop an externally owned heap trace."""

import tracemalloc

import pytest
from evaluation.workflow_resources import measure_workflow


@pytest.mark.parametrize("failure", [False, True])
def test_resource_observations_are_retained_on_success_or_failure(failure: bool) -> None:
    assert not tracemalloc.is_tracing()
    values = {}
    try:
        with measure_workflow() as values:
            payload = bytearray(100000)
            assert len(payload) == 100000
            if failure:
                raise RuntimeError("controlled")
    except RuntimeError:
        assert failure
    assert values["heap_scope"] == "workflow_owned_trace"
    assert int(values["process_cpu_ms"]) >= 0
    assert int(values["python_heap_peak_bytes"]) >= 100000
    assert not tracemalloc.is_tracing()


def test_existing_trace_is_retained_and_marked_cumulative() -> None:
    tracemalloc.start()
    try:
        with measure_workflow() as values:
            pass
        assert tracemalloc.is_tracing()
        assert values["heap_scope"] == "existing_cumulative_trace"
    finally:
        tracemalloc.stop()

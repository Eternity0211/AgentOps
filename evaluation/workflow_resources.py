"""Bounded local process/heap observations; never whole-system or provider resources."""

import time
import tracemalloc
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def measure_workflow() -> Iterator[dict[str, int | str]]:
    values: dict[str, int | str] = {}
    owns_trace = not tracemalloc.is_tracing()
    if owns_trace:
        tracemalloc.start()
    started = time.process_time_ns()
    try:
        yield values
    finally:
        cpu = time.process_time_ns() - started
        current, peak = tracemalloc.get_traced_memory()
        values.update(
            process_cpu_ms=cpu // 1000000,
            python_heap_current_bytes=current,
            python_heap_peak_bytes=peak,
            heap_scope="workflow_owned_trace" if owns_trace else "existing_cumulative_trace",
        )
        if owns_trace:
            tracemalloc.stop()

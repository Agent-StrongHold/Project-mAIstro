"""A deliberate pause is its own disposition in `RuntimeMetrics` (#642).

`ExecutionPaused` is an `Exception`, so before this change the broad
`except Exception` in `PythonExecutionRuntime.execute` caught it first and
counted every successful pause as a failed execution. `RuntimeMetrics` is the
migration-trigger measurement — the numbers that answer "is the in-process
runtime holding up" — and a HITL-heavy workload pauses constantly and
legitimately, so those pauses read as a runtime falling over when it was doing
its job.

The counters are asserted as a whole tuple rather than one field at a time.
Three of the four criteria are about what a pause *does not* increment, and a
per-field assertion cannot see a count that moved somewhere nobody looked.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.runtime import ExecutionPaused, PythonExecutionRuntime, RuntimeMetrics

pytestmark = [pytest.mark.contract("behavioral")]


def _dispositions(metrics: RuntimeMetrics) -> dict[str, int]:
    """Every terminal count at once, so a stray increment cannot hide."""
    return {
        "started": metrics.executions_started,
        "completed": metrics.executions_completed,
        "failed": metrics.executions_failed,
        "yielded": metrics.executions_yielded,
        "cancelled": metrics.executions_cancelled,
        "timed_out": metrics.executions_timed_out,
    }


async def _pause(_work: Any, _context: Any) -> None:
    raise ExecutionPaused("waiting on a person")


async def _fail(_work: Any, _context: Any) -> None:
    raise RuntimeError("boom")


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-081426-1f7c/AC-13")
@pytest.mark.ac("SPEC-081426-1f7c/AC-14")
@pytest.mark.ac("SPEC-081426-1f7c/AC-15")
async def test_a_pause_is_counted_as_a_pause_and_as_nothing_else() -> None:
    runtime = PythonExecutionRuntime(max_concurrency=1)

    with pytest.raises(ExecutionPaused):
        await runtime.execute(None, None, execution_id="attempt-1", executor=_pause)

    assert _dispositions(runtime.metrics()) == {
        "started": 1,
        "completed": 0,
        "failed": 0,
        "yielded": 1,
        "cancelled": 0,
        "timed_out": 0,
    }


@pytest.mark.asyncio
@pytest.mark.ac("SPEC-081426-1f7c/AC-16")
async def test_a_genuine_error_is_still_a_failure_and_not_a_pause() -> None:
    """The counter a pause stops reaching still has to receive real failures.

    Moving a pause out of `executions_failed` by widening what escapes the
    failure clause would satisfy the three criteria above while making the
    number meaningless, which is the same over-count in the other direction.
    """
    runtime = PythonExecutionRuntime(max_concurrency=1)

    with pytest.raises(RuntimeError, match="boom"):
        await runtime.execute(None, None, execution_id="attempt-1", executor=_fail)

    assert _dispositions(runtime.metrics()) == {
        "started": 1,
        "completed": 0,
        "failed": 1,
        "yielded": 0,
        "cancelled": 0,
        "timed_out": 0,
    }


@pytest.mark.asyncio
async def test_a_pause_re_raises_and_leaks_no_capacity() -> None:
    """The domain terminalizes the Attempt from the signal, so it must escape.

    Swallowing it would have made the four counter criteria pass while turning
    a pause into a silent success at the seam above -- and a pause that never
    released its slot would starve the runtime one HITL node at a time.
    """
    runtime = PythonExecutionRuntime(max_concurrency=1)

    with pytest.raises(ExecutionPaused):
        await runtime.execute(None, None, execution_id="attempt-1", executor=_pause)

    metrics = runtime.metrics()
    assert metrics.active_executions == 0
    assert metrics.active_slots == 0

    async def succeed(_work: Any, _context: Any) -> str:
        return "the slot came back"

    assert (
        await runtime.execute(None, None, execution_id="attempt-2", executor=succeed)
        == "the slot came back"
    )


def test_the_domain_pause_signal_is_the_one_the_runtime_counts() -> None:
    """The load-bearing wiring: `runs.ExecutionYielded` is what actually gets
    raised, and a fix aimed at a class nothing raises would be no fix at all.

    The subclass direction is deliberate. `maistro.runs` imports
    `maistro.runtime`, never the reverse, so the shared signal has to be defined
    by the Runtime and specialized by the domain -- a Runtime reaching back for
    the domain's exception would invert the dependency and fail AC-10.
    """
    from maistro.runs.execution import ExecutionYielded

    assert issubclass(ExecutionYielded, ExecutionPaused)

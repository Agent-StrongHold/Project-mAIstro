"""Public cancellation cannot return success from canceled work (#1336)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.runtime.execution import PythonExecutionRuntime

pytestmark = pytest.mark.contract("behavioral")


@pytest.mark.parametrize("timeout_s", [None, 30.0], ids=["no-deadline", "with-deadline"])
async def test_public_cancel_fences_an_executor_that_swallows_cancellation(
    timeout_s: float | None,
) -> None:
    runtime = PythonExecutionRuntime(max_concurrency=1)
    entered = asyncio.Event()
    swallowed = asyncio.Event()

    async def executor(_work: Any, _context: Any) -> str:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            swallowed.set()
            return "stale success"
        raise AssertionError("unreachable")

    execution = asyncio.create_task(
        runtime.execute(None, None, execution_id="swallows", executor=executor, timeout_s=timeout_s)
    )
    try:
        async with asyncio.timeout(3):
            await entered.wait()
            assert await runtime.cancel("swallows") is True
            with pytest.raises(asyncio.CancelledError):
                await execution
    finally:
        execution.cancel()
        await asyncio.gather(execution, return_exceptions=True)

    assert swallowed.is_set()
    metrics = runtime.metrics()
    assert metrics.executions_cancelled == 1
    assert metrics.executions_completed == 0
    assert metrics.executions_failed == 0
    assert metrics.executions_timed_out == 0
    assert metrics.active_executions == metrics.active_slots == 0
    assert runtime._work_tasks == {}
    assert await runtime.cancel("swallows") is False


async def test_public_cancel_wins_after_child_finishes_before_runtime_accepts_result() -> None:
    runtime = PythonExecutionRuntime(max_concurrency=1)
    loop = asyncio.get_running_loop()
    cancellation: asyncio.Future[bool] = loop.create_future()
    cancel_tasks: list[asyncio.Task[None]] = []

    async def cancel_completed_child() -> None:
        try:
            # Observe the real interleaving; no Task state or Runtime method
            # is patched. The child is done, but execute() has not accepted it.
            child = runtime._work_tasks["race"]
            assert child.done()
            assert child.result() == "physical result"
            assert not runtime._active["race"].done()
            cancellation.set_result(await runtime.cancel("race"))
        except BaseException as exc:
            cancellation.set_exception(exc)

    def schedule_cancel() -> None:
        cancel_tasks.append(asyncio.create_task(cancel_completed_child()))

    async def executor(_work: Any, _context: Any) -> str:
        # Queue cancellation before returning. The callback creates its task
        # before the shield schedules execute() to consume the child's value.
        loop.call_soon(schedule_cancel)
        return "physical result"

    execution = asyncio.create_task(
        runtime.execute(None, None, execution_id="race", executor=executor)
    )
    try:
        async with asyncio.timeout(3):
            assert await cancellation is True
            with pytest.raises(asyncio.CancelledError):
                await execution
    finally:
        execution.cancel()
        await asyncio.gather(execution, *cancel_tasks, return_exceptions=True)

    metrics = runtime.metrics()
    assert metrics.executions_cancelled == 1
    assert metrics.executions_completed == 0
    assert metrics.active_executions == metrics.active_slots == 0
    assert runtime._work_tasks == {}


async def test_public_cancel_after_accepted_completion_reports_no_cancellation() -> None:
    runtime = PythonExecutionRuntime(max_concurrency=1)

    async def executor(_work: Any, _context: Any) -> str:
        return "accepted result"

    result = await runtime.execute(None, None, execution_id="finished", executor=executor)

    assert result == "accepted result"
    assert await runtime.cancel("finished") is False
    metrics = runtime.metrics()
    assert metrics.executions_completed == 1
    assert metrics.executions_cancelled == 0
    assert metrics.active_executions == metrics.active_slots == 0

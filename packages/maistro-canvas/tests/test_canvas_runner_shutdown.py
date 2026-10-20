"""Codex #1527 finding 4: application shutdown must not hang forever behind a
stuck ``CanvasJobRunner`` tick.

``CanvasJobRunner.stop()`` only flips a poll-loop flag; it cannot interrupt a
``tick_once`` blocked inside a provider call. ``bind_canvas_runner_lifecycle``'s
shutdown handler therefore bounds its wait for the runner task with
``shutdown_timeout`` and cancels a still-running task rather than awaiting it
unconditionally.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import APIRouter

from maistro_canvas.canvas.composition import bind_canvas_runner_lifecycle

pytestmark = pytest.mark.asyncio


class _StuckRunner:
    """Stands in for ``CanvasJobRunner`` whose current tick never returns on
    its own — ``stop()`` sets a flag the (fake) loop never checks, the way a
    real loop blocked inside an in-flight provider call would not either."""

    def __init__(self) -> None:
        self.stopped = False
        self.cancelled = False

    async def start(self) -> None:
        try:
            await asyncio.Event().wait()  # never completes on its own
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    def stop(self) -> None:
        self.stopped = True


class _CooperativeRunner:
    """A runner whose loop actually checks the stop flag and returns
    promptly — the ordinary graceful-shutdown path this change must not
    break."""

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            await asyncio.sleep(0.01)

    def stop(self) -> None:
        self._running = False


class _Runtime:
    def __init__(self, runner: object) -> None:
        self.runner = runner


async def test_shutdown_cancels_stuck_runner_task_within_timeout() -> None:
    router = APIRouter()
    runner = _StuckRunner()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(runner),
        shutdown_timeout=0.2,  # type: ignore[arg-type]
    )
    start_runner = router.on_startup[0]
    stop_runner = router.on_shutdown[0]

    await start_runner()
    assert runner.stopped is False

    elapsed = asyncio.get_event_loop().time()
    await asyncio.wait_for(stop_runner(), timeout=2.0)
    elapsed = asyncio.get_event_loop().time() - elapsed

    assert runner.stopped is True
    assert runner.cancelled is True
    # Bounded by shutdown_timeout, not left hanging on the stuck task.
    assert elapsed < 1.5


async def test_shutdown_returns_promptly_when_runner_stops_on_its_own() -> None:
    """A cooperative runner that actually honors ``stop()`` is never
    cancelled — the timeout is a backstop, not the normal path."""
    router = APIRouter()
    runner = _CooperativeRunner()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(runner),
        shutdown_timeout=5.0,  # type: ignore[arg-type]
    )
    start_runner = router.on_startup[0]
    stop_runner = router.on_shutdown[0]

    await start_runner()
    # Let the task's coroutine actually begin (set its own running flag)
    # before signalling stop — otherwise stop() firing before the task has
    # run its first line races the task's own startup, exactly as it would
    # in production if shutdown followed startup with no yield in between.
    await asyncio.sleep(0.01)
    await asyncio.wait_for(stop_runner(), timeout=1.0)


async def test_start_runner_is_idempotent_while_task_is_live() -> None:
    """Calling the startup handler twice (e.g. a duplicate lifespan event)
    does not spawn a second concurrent runner task."""
    router = APIRouter()
    runner = _CooperativeRunner()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(runner),
        shutdown_timeout=1.0,  # type: ignore[arg-type]
    )
    start_runner = router.on_startup[0]
    stop_runner = router.on_shutdown[0]

    await start_runner()
    await asyncio.sleep(0.01)
    await start_runner()
    await asyncio.wait_for(stop_runner(), timeout=1.0)


async def test_stop_runner_before_start_is_a_noop() -> None:
    """Shutdown firing without a prior startup (e.g. startup itself failed)
    must not raise."""
    router = APIRouter()
    runner = _CooperativeRunner()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(runner),
        shutdown_timeout=1.0,  # type: ignore[arg-type]
    )
    stop_runner = router.on_shutdown[0]

    await asyncio.wait_for(stop_runner(), timeout=1.0)


class _CancellationResistantRunner:
    """A runner whose in-flight provider coroutine swallows ``CancelledError``
    (cancellation-resistant cleanup). ``asyncio.wait_for`` would cancel it at
    the deadline and then wait for it to finish anyway -- forever."""

    def __init__(self) -> None:
        self.cancel_requests = 0
        self.release = asyncio.Event()

    async def start(self) -> None:
        while not self.release.is_set():
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancel_requests += 1

    def stop(self) -> None:
        pass


async def test_shutdown_is_bounded_even_when_the_task_ignores_cancellation() -> None:
    router = APIRouter()
    runner = _CancellationResistantRunner()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(runner),
        shutdown_timeout=0.2,  # type: ignore[arg-type]
    )
    await router.on_startup[0]()
    await asyncio.sleep(0)

    try:
        await asyncio.wait_for(router.on_shutdown[0](), timeout=2.0)
    finally:
        runner.release.set()
        await asyncio.sleep(0)

    assert runner.cancel_requests >= 1


async def test_shutdown_logs_a_runner_that_crashed_on_its_own(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _CrashingRunner:
        async def start(self) -> None:
            raise RuntimeError("runner loop crashed")

        def stop(self) -> None:
            pass

    router = APIRouter()
    bind_canvas_runner_lifecycle(
        router=router,
        runtime=_Runtime(_CrashingRunner()),
        shutdown_timeout=1.0,  # type: ignore[arg-type]
    )
    await router.on_startup[0]()
    await asyncio.sleep(0)
    with caplog.at_level("ERROR", logger="maistro.canvas.composition"):
        await asyncio.wait_for(router.on_shutdown[0](), timeout=2.0)
    assert any("canvas_runner_exited_with_error" in r.getMessage() for r in caplog.records)

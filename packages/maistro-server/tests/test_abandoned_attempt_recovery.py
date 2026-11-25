"""maistro-server operates the canonical abandoned-Attempt recovery tick."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro_server.abandoned_attempt_recovery import (
    start_abandoned_attempt_recovery,
    stop_abandoned_attempt_recovery,
    tick_abandoned_attempt_recovery,
)


@pytest.fixture(autouse=True)
async def _cadence_stopped() -> Any:
    await stop_abandoned_attempt_recovery()
    yield
    await stop_abandoned_attempt_recovery()


async def test_tick_calls_the_container_recovery_sweep() -> None:
    seen: list[int] = []

    class Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            seen.append(limit)
            return 3

    assert await tick_abandoned_attempt_recovery(Container()) == 3
    assert seen == [100]


async def test_tick_logs_store_failure_and_is_retryable(caplog: pytest.LogCaptureFixture) -> None:
    class Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            raise RuntimeError("database unavailable")

    assert await tick_abandoned_attempt_recovery(Container()) == 0
    assert "abandoned_attempt_recovery_tick_failed" in caplog.text


async def test_container_without_sweep_is_noop() -> None:
    assert await tick_abandoned_attempt_recovery(object()) == 0


async def test_cancelled_tick_propagates_cancellation() -> None:
    class Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await tick_abandoned_attempt_recovery(Container())


async def test_non_awaitable_sweep_is_ignored() -> None:
    class Container:
        def recover_abandoned_attempts(self, *, limit: int = 100) -> object:
            return object()

    assert await tick_abandoned_attempt_recovery(Container()) == 0


async def test_start_is_idempotent_and_stop_joins(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.01)
    calls = 0

    class Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            nonlocal calls
            calls += 1
            return 0

    container = Container()
    start_abandoned_attempt_recovery(container)
    start_abandoned_attempt_recovery(container)
    await asyncio.wait_for(_wait_for_call(lambda: calls), timeout=2)
    await stop_abandoned_attempt_recovery()
    calls_at_stop = calls
    await asyncio.sleep(0.03)
    assert calls == calls_at_stop
    assert cadence._task is None


async def _wait_for_call(read_calls: Any) -> None:
    while not read_calls():
        await asyncio.sleep(0.005)


class _BlockedContainer:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
        self.entered.set()
        await self.release.wait()
        return 0


async def test_stop_cancels_tick_past_join_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    monkeypatch.setattr(cadence, "_STOP_TIMEOUT_S", 0.01)
    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()
    await stop_abandoned_attempt_recovery()
    assert cadence._task is None
    container.release.set()


async def test_cancelling_stop_call_leaves_cadence_joinable() -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()
    cadence_task = cadence._task
    assert cadence_task is not None
    stopper = asyncio.create_task(stop_abandoned_attempt_recovery())
    await asyncio.sleep(0)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper
    assert cadence._task is cadence_task
    container.release.set()
    await asyncio.wait_for(cadence_task, timeout=1)
    assert not cadence_task.cancelled()


async def test_stop_tolerates_cadence_cancellation() -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()
    cadence_task = cadence._task
    assert cadence_task is not None
    stopper = asyncio.create_task(stop_abandoned_attempt_recovery())
    await asyncio.sleep(0)
    cadence_task.cancel()
    await asyncio.wait_for(stopper, timeout=1)
    assert cadence_task.cancelled()
    assert cadence._task is None

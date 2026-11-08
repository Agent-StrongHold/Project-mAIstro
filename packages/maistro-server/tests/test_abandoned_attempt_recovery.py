"""maistro-server is the operator for abandoned-Attempt recovery (#232)."""

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


async def test_a_tick_calls_the_container_sweep() -> None:
    seen: list[int] = []

    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            seen.append(limit)
            return 3

    assert await tick_abandoned_attempt_recovery(_Container()) == 3
    assert seen == [100]


async def test_a_tick_survives_a_store_failure() -> None:
    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            raise RuntimeError("database unreachable")

    assert await tick_abandoned_attempt_recovery(_Container()) == 0


async def test_a_container_without_the_sweep_ticks_as_a_noop() -> None:
    """A Container without ``recover_abandoned_attempts`` must not kill the cadence."""
    assert await tick_abandoned_attempt_recovery(object()) == 0


async def test_a_cancelled_tick_propagates_the_cancellation() -> None:
    """A cancelled sweep must look cancelled: a torn-down loop stops here."""

    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await tick_abandoned_attempt_recovery(_Container())


async def test_a_non_awaitable_recover_is_ignored() -> None:
    class _Container:
        def recover_abandoned_attempts(self, *, limit: int = 100) -> object:
            return object()

    assert await tick_abandoned_attempt_recovery(_Container()) == 0


async def test_start_is_idempotent_and_stop_joins(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro_server.abandoned_attempt_recovery as cadence

    monkeypatch.setattr(cadence, "_INTERVAL_S", 0.01)
    hits = 0

    class _Container:
        async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
            nonlocal hits
            hits += 1
            return 0

    container = _Container()
    start_abandoned_attempt_recovery(container)
    start_abandoned_attempt_recovery(container)

    async def _saw_a_tick() -> bool:
        return hits >= 1

    async def _wait() -> None:
        while not await _saw_a_tick():
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout=2)
    await stop_abandoned_attempt_recovery()
    settled = hits
    await asyncio.sleep(0.05)
    assert hits == settled
    assert cadence._task is None


class _BlockedContainer:
    """A sweep whose tick parks until its test releases it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def recover_abandoned_attempts(self, *, limit: int = 100) -> int:
        self.entered.set()
        await self.release.wait()
        return 0


async def test_stop_cancels_a_tick_stuck_past_the_join_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Past ``_STOP_TIMEOUT_S`` the join gives up and cancels the tick."""
    import maistro_server.abandoned_attempt_recovery as cadence

    monkeypatch.setattr(cadence, "_STOP_TIMEOUT_S", 0.01)
    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()

    await stop_abandoned_attempt_recovery()

    assert cadence._task is None
    container.release.set()


async def test_stop_reraises_when_the_stop_call_itself_is_cancelled() -> None:
    """A caller cancelling its own join still leaves the cadence joinable."""
    import maistro_server.abandoned_attempt_recovery as cadence

    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()
    cadence_task = cadence._task
    assert cadence_task is not None

    stopper = asyncio.create_task(stop_abandoned_attempt_recovery())
    # stop() is synchronous up to the join, so one scheduler turn parks it there
    # with the cadence still pending -- exactly the state the re-raise guards.
    await asyncio.sleep(0.05)
    stopper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopper

    # The shielded cadence survived the cancelled join; release it so the
    # fixture teardown finds no stray task.
    container.release.set()
    await asyncio.wait_for(cadence_task, timeout=1)
    assert cadence_task.cancelled() is False


async def test_stop_tolerates_the_cadence_being_cancelled_underneath() -> None:
    """A join aborted by the cadence's own cancellation must not re-raise."""
    import maistro_server.abandoned_attempt_recovery as cadence

    container = _BlockedContainer()
    start_abandoned_attempt_recovery(container)
    await container.entered.wait()
    cadence_task = cadence._task
    assert cadence_task is not None

    stopper = asyncio.create_task(stop_abandoned_attempt_recovery())
    await asyncio.sleep(0.05)
    cadence_task.cancel()
    await asyncio.wait_for(stopper, timeout=1)

    assert cadence_task.cancelled() is True
    assert cadence._task is None

"""Tick ``Container.recover_abandoned_attempts`` for this process (#232).

``maistro-core`` exposes the sweep as a bounded, idempotent, operator-scheduled
tick and never starts it (ADR-019). Hive already ticks the Container it boots.
This process is the task worker: its ``TaskAttemptExecutor`` writes leased
Attempts, and a lease nobody collects is worse than no lease. The cadence owns
no lifecycle of its own — the Container's Run, Attempt lease and fence decide
what a tick may do.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
from typing import Any

logger = logging.getLogger("maistro_server.abandoned_attempt_recovery")

_INTERVAL_S = 10.0
_LIMIT = 100
_task: asyncio.Task[None] | None = None
_stopping: asyncio.Event | None = None


async def tick_abandoned_attempt_recovery(container: Any, *, limit: int = _LIMIT) -> int:
    """Run one reclaim sweep. A store failure is logged and returns 0.

    The next tick retries. One failed sweep must not kill the cadence: the
    Attempts it would have reclaimed are still leased, and a dead ticker
    leaves them that way until the process restarts.
    """
    recover = getattr(container, "recover_abandoned_attempts", None)
    if recover is None:
        return 0
    result = recover(limit=limit)
    if not inspect.isawaitable(result):
        return 0
    try:
        settled = await result
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("abandoned_attempt_recovery_tick_failed")
        return 0
    count = int(settled or 0)
    if count:
        logger.info("abandoned_attempt_recovery settled=%d", count)
    return count


async def _run(container: Any, stopping: asyncio.Event) -> None:
    while not stopping.is_set():
        await tick_abandoned_attempt_recovery(container)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopping.wait(), timeout=_INTERVAL_S)


def start_abandoned_attempt_recovery(container: Any) -> None:
    """Start one process-local sweep. Idempotent."""
    global _task, _stopping
    if _task is not None and not _task.done():
        return
    _stopping = asyncio.Event()
    _task = asyncio.create_task(
        _run(container, _stopping), name="maistro-abandoned-attempt-recovery"
    )


async def stop_abandoned_attempt_recovery() -> None:
    """Wake the cadence and join it. A tick still running is cancelled."""
    global _task, _stopping
    task, stopping = _task, _stopping
    _task = _stopping = None
    if task is None or task.done():
        return
    if stopping is not None:
        stopping.set()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
    except asyncio.CancelledError:
        if not task.cancelled():
            raise
    except TimeoutError:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


__all__ = [
    "start_abandoned_attempt_recovery",
    "stop_abandoned_attempt_recovery",
    "tick_abandoned_attempt_recovery",
]
